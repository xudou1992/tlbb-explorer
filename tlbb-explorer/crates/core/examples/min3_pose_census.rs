//! MIN3 全库「能不能摆」普查：解析成功 ≠ 画布能摆出来。
//! 对每份 MIN3 动作，找同目录同茎的 `.mesh`，真跑一遍 `pose_frame` → `skin_palette`
//! → `posed_vertices`，报成功/失败与失败原因。只读库，不落字节。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example min3_pose_census
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose};

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

    // 网格按「同目录同茎」索引：dir + stem
    let mut meshes: HashMap<(String, String), (String, u64, String)> = HashMap::new();
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
            meshes.insert((dir, stem), (pak, u64::from_str_radix(&hash, 16).unwrap_or(0), name));
        }
    }

    let mut anis: Vec<(String, String, u64, String)> = Vec::new(); // dir, stem, hash, pak
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
            // 动作名 = 网格茎 + _动作名
            anis.push((dir, stem, u64::from_str_radix(&hash, 16).unwrap_or(0), pak));
        }
    }

    let mut paks: HashMap<String, Pak> = HashMap::new();
    let (mut min3, mut no_mesh, mut parse_fail, mut posed_ok, mut posed_fail) = (0usize, 0usize, 0usize, 0usize, 0usize);
    let want = std::env::args().nth(1).unwrap_or_else(|| "MIN3".to_string());
    let mut reasons: HashMap<String, usize> = HashMap::new();
    let mut examples: Vec<String> = Vec::new();
    let mut mesh_cache: HashMap<(String, String), Option<(Vec<u8>, Vec<tlbb_core::preview::Node>)>> = HashMap::new();

    for (dir, stem, ah, apak) in &anis {
        // 找网格：动作在 `.../<茎>/ani/` 下，网格在同一 `<茎>` 目录；动作名以网格茎开头。
        let dir2 = dir.trim_end_matches("/ani").trim_end_matches('/').to_string();
        let mut found: Option<(String, u64, String)> = None;
        let mut cut = stem.as_str();
        for _ in 0..4 {
            if let Some((g, _)) = cut.rsplit_once('_') {
                cut = g;
                if let Some(m) = meshes.get(&(dir2.clone(), cut.to_string())) {
                    found = Some(m.clone());
                    break;
                }
            } else {
                break;
            }
        }
        let Some((mpak, mh, mname)) = found else { continue };
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
        let want = std::env::args().nth(1).unwrap_or_else(|| "MIN3".to_string());
        if araw.get(0x8c..0x90) != Some(want.as_bytes()) {
            continue;
        }
        min3 += 1;
        let Some(mr) = mp.records().find(|r| r.hash == mh && r.stored > 0) else {
            no_mesh += 1;
            continue;
        };
        let mraw = mesh_cache
            .entry((dir2.clone(), stem.clone()))
            .or_insert_with(|| payload::decode(mp, &mr).ok().map(|d| (d.bytes, Vec::new())));
        let Some((mesh_bytes, _)) = mraw.as_mut() else {
            no_mesh += 1;
            continue;
        };
        let Some(h) = parse_hierarchy(mesh_bytes) else {
            *reasons.entry("骨架解不出".to_string()).or_insert(0) += 1;
            if examples.len() < 6 {
                examples.push(format!("{dir2}/{stem} ← {mname}"));
            }
            continue;
        };
        let nodes = parse_nodes(mesh_bytes);
        let Some(a) = parse_ani(&araw) else {
            parse_fail += 1;
            continue;
        };
        let mut layout = parse_mesh(mesh_bytes).ok();
        let g = match layout.as_mut() {
            Some(l) if !l.geometry.positions.is_empty() => &l.geometry,
            _ => {
                *reasons.entry("网格没有几何".to_string()).or_insert(0) += 1;
                continue;
            }
        };
        let bind = pose::bind_worlds(&h);
        let mut ok = true;
        for f in 0..a.frames.min(3) {
            let world = pose::pose_frame(&h, &a, f);
            let Some(pal) = pose::skin_palette(&h, &bind, &world) else {
                *reasons.entry("调色板算不出".to_string()).or_insert(0) += 1;
                ok = false;
                break;
            };
            if pose::posed_vertices(&h, &pal, &nodes, &g.positions).is_none() {
                *reasons.entry("摆顶点失败".to_string()).or_insert(0) += 1;
                ok = false;
                break;
            }
        }
        if ok {
            posed_ok += 1;
        } else {
            posed_fail += 1;
        }
    }
    let mut rs: Vec<(String, usize)> = reasons.into_iter().collect();
    rs.sort_by(|a, b| b.1.cmp(&a.1));
    println!(
        "{want} {min3} 份 · 有同茎网格 {}/{} · 能摆出来 {posed_ok} · 摆失败 {posed_fail} · 动作解析失败 {parse_fail} · 找不到网格 {no_mesh}",
        min3 - no_mesh,
        min3
    );
    for e in &examples {
        println!("  骨架解不出的例子：{e}");
    }
    if !rs.is_empty() {
        println!(
            "失败原因：{}",
            rs.iter().map(|(k, v)| format!("{k}×{v}")).collect::<Vec<_>>().join("  ")
        );
    }
}
