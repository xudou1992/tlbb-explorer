//! MIN3「骨 → 通道块按索引表间接」这条修复的跨文件 A/B。
//!
//! A = 现口径（解析器按索引表把块挂到骨）；
//! B = 改前口径（数据块按顺序贴 δ=1 的名字，即「第 k 块归第 k+1 根骨」）。
//! 同一份数据、同一把尺子（页面同款锚 `reanchored_palette`），只换骨名。
//! 分开报「有哨兵（骨数 > 块数）」与「恒等表」两族，因为修复只该影响前者。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example min3_idx_ab
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose, Anim};

const NAMES_AT: usize = 0xd2;
const STRIDE: usize = 30;

fn slot_name(raw: &[u8], at: usize) -> String {
    let Some(b) = raw.get(at..at + STRIDE) else {
        return String::new();
    };
    let end = b.iter().position(|&c| c == 0).unwrap_or(STRIDE);
    let bytes = &b[..end];
    let clean = !bytes.is_empty()
        && bytes
            .iter()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.'));
    if clean {
        String::from_utf8_lossy(bytes).into_owned()
    } else {
        String::new()
    }
}

/// 改前口径：把有数据的轨道按顺序贴 δ=1 的名字（`0xD2 + 30 + 30k`）。
fn old_labelling(a: &Anim, raw: &[u8]) -> Anim {
    let mut b = a.clone();
    let mut k = 0usize;
    for t in b.tracks.iter_mut() {
        if t.rotations.is_empty() {
            t.bone = String::new();
            continue;
        }
        t.bone = slot_name(raw, NAMES_AT + STRIDE + k * STRIDE);
        k += 1;
    }
    b
}

fn total_tears(
    h: &tlbb_core::preview::SkeletonHierarchy,
    a: &Anim,
    nodes: &[tlbb_core::preview::Node],
    g: &tlbb_core::preview::MeshGeometry,
) -> Option<usize> {
    let mut sum = 0usize;
    for f in 0..a.frames {
        let pal = pose::reanchored_palette(h, a, f)?;
        let posed = pose::posed_vertices(h, &pal, nodes, &g.positions)?;
        sum += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
    }
    Some(sum)
}

fn main() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    let con = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("清单打不开");
    let mut meshes: HashMap<(String, String), (String, u64)> = HashMap::new();
    {
        let mut st = con
            .prepare("SELECT coalesce(dir,''), name, hash, coalesce(pak,'') FROM resources WHERE ext='.mesh' AND coalesce(pak,'') <> ''")
            .unwrap();
        let it = st
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                ))
            })
            .unwrap();
        for (dir, name, hash, pak) in it.flatten() {
            let stem = name.trim_end_matches(".mesh").to_string();
            meshes.insert((dir, stem), (pak, u64::from_str_radix(&hash, 16).unwrap_or(0)));
        }
    }
    let mut anis: Vec<(String, String, u64, String)> = Vec::new();
    {
        let mut st = con
            .prepare("SELECT coalesce(dir,''), name, hash, coalesce(pak,'') FROM resources WHERE ext='.ani' AND coalesce(pak,'') <> ''")
            .unwrap();
        let it = st
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                ))
            })
            .unwrap();
        for (dir, name, hash, pak) in it.flatten() {
            let stem = name.trim_end_matches(".ani").to_string();
            anis.push((dir, stem, u64::from_str_radix(&hash, 16).unwrap_or(0), pak));
        }
    }
    let limit: usize = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(40);
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let (mut done, mut shown) = (0usize, 0usize);
    let (mut a_sum_sent, mut b_sum_sent, mut a_win_sent, mut n_sent) = (0u64, 0u64, 0usize, 0usize);
    let (mut a_sum_id, mut b_sum_id, mut a_win_id, mut n_id) = (0u64, 0u64, 0usize, 0usize);
    for (dir, stem, ah, apak) in &anis {
        if done >= limit {
            break;
        }
        let dir2 = dir.trim_end_matches("/ani").trim_end_matches('/').to_string();
        let mut found: Option<(String, u64)> = None;
        let mut cut = stem.as_str();
        for _ in 0..4 {
            let Some((g, _)) = cut.rsplit_once('_') else { break };
            cut = g;
            if let Some(m) = meshes.get(&(dir2.clone(), cut.to_string())) {
                found = Some(m.clone());
                break;
            }
        }
        let Some((mpak, mh)) = found else { continue };
        for k in [apak, &mpak] {
            if !paks.contains_key(k) {
                if let Ok(p) = Pak::open(root.join(format!("{k}.pak"))) {
                    paks.insert(k.clone(), p);
                }
            }
        }
        let (Some(ap), Some(mp)) = (paks.get(apak), paks.get(&mpak)) else { continue };
        let Some(ar) = ap.records().find(|r| r.hash == *ah && r.stored > 0) else { continue };
        let Ok(araw) = payload::decode(ap, &ar).map(|d| d.bytes) else { continue };
        if araw.get(0x8c..0x90) != Some(&b"MIN3"[..]) {
            continue;
        }
        let Some(mr) = mp.records().find(|r| r.hash == mh && r.stored > 0) else { continue };
        let Ok(mraw) = payload::decode(mp, &mr).map(|d| d.bytes) else { continue };
        let (Ok(layout), Some(h), Some(a)) =
            (parse_mesh(&mraw), parse_hierarchy(&mraw), parse_ani(&araw))
        else {
            continue;
        };
        let g = &layout.geometry;
        let nodes = parse_nodes(&mraw);
        if g.positions.is_empty() || g.indices.is_empty() || a.frames == 0 {
            continue;
        }
        let bones = u32::from_le_bytes(araw[0xba..0xbe].try_into().unwrap()) as usize;
        let bones2 = u32::from_le_bytes(araw[0xbe..0xc2].try_into().unwrap()) as usize;
        let (Some(ta), Some(tb)) = (total_tears(&h, &a, &nodes, g), total_tears(&h, &old_labelling(&a, &araw), &nodes, g)) else {
            continue;
        };
        done += 1;
        let holes = bones > bones2;
        if holes {
            n_sent += 1;
            a_sum_sent += ta as u64;
            b_sum_sent += tb as u64;
            if ta < tb {
                a_win_sent += 1;
            }
        } else {
            n_id += 1;
            a_sum_id += ta as u64;
            b_sum_id += tb as u64;
            if ta < tb {
                a_win_id += 1;
            }
        }
        if shown < 12 {
            println!(
                "{} 骨{bones}/块{bones2} 帧{} · 索引表映射 {:8} · 旧的顺序贴名 {:8}",
                if holes { "有空洞" } else { "恒等表" },
                a.frames,
                ta,
                tb
            );
            shown += 1;
        }
    }
    println!("---");
    println!(
        "有空洞族 {n_sent} 份：新 {a_sum_sent} · 旧 {b_sum_sent} · 新更好的 {a_win_sent} 份"
    );
    println!(
        "恒等表族 {n_id} 份：新 {a_sum_id} · 旧 {b_sum_id} · 新更好的 {a_win_id} 份"
    );
}
