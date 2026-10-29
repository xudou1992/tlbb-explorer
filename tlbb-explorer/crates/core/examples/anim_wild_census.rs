//! 动作「野度」普查：最狠帧上，相对第 0 帧转 >90° 的骨占全部可动骨的比例。
//!
//! 用途：把「看起来正常」与「整副骨架乱转」分开，估计 MIN2 问题在库里波及多少资产。
//! 已知锚点：慕容复 `walk` = 0/189（正常）；魔法蜜蜂 `idle02` = 127/142（散架）。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example anim_wild_census [份数上限=60]
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{attach_bone_skin, parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose};

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
    let limit: usize = std::env::args()
        .nth(1)
        .and_then(|s| s.parse().ok())
        .unwrap_or(60);

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
            meshes.insert(
                (dir, name.trim_end_matches(".mesh").to_string()),
                (pak, u64::from_str_radix(&hash, 16).unwrap_or(0)),
            );
        }
    }
    let mut anis: Vec<(String, String, u64, String)> = Vec::new();
    {
        let mut st = con
            .prepare("SELECT coalesce(dir,''), name, hash, coalesce(pak,'') FROM resources WHERE ext='.ani' AND coalesce(pak,'') <> '' ORDER BY hash")
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
            anis.push((
                dir,
                name.trim_end_matches(".ani").to_string(),
                u64::from_str_radix(&hash, 16).unwrap_or(0),
                pak,
            ));
        }
    }
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut done = 0usize;
    let mut wild = 0usize;
    let mut rows: Vec<(f64, usize, usize, String, String)> = Vec::new();
    let mut rates: Vec<(f64, usize, usize, String)> = Vec::new();
    for (dir, stem, ah, apak) in &anis {
        if done >= limit {
            break;
        }
        let dir2 = dir.trim_end_matches("/ani").trim_end_matches('/').to_string();
        let mut found = None;
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
        let Some(mr) = mp.records().find(|r| r.hash == mh && r.stored > 0) else { continue };
        let Ok(mraw) = payload::decode(mp, &mr).map(|d| d.bytes) else { continue };
        let (Ok(layout), Some(h), Some(a)) =
            (parse_mesh(&mraw), parse_hierarchy(&mraw), parse_ani(&araw))
        else {
            continue;
        };
        if h.bones.len() != a.bones || a.frames < 2 {
            continue;
        }
        let nodes = attach_bone_skin(&h, &parse_nodes(&mraw), &mraw);
        let g = &layout.geometry;
        if g.positions.is_empty() || g.indices.is_empty() {
            continue;
        }
        // 逐帧：撕边 + 相对第 0 帧转 >90° 的骨比例，取撕边最大的那帧。
        let (mut worst_tear, mut worst_frac) = (0usize, 0f64);
        for f in 0..a.frames {
            let Some(pal) = pose::reanchored_palette(&h, &a, f) else { continue };
            let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
            let t = pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
            if t >= worst_tear {
                worst_tear = t;
                let mut big = 0usize;
                let mut n = 0usize;
                for tr in &a.tracks {
                    if tr.rotations.len() <= f || tr.rotations.is_empty() {
                        continue;
                    }
                    n += 1;
                    let q0 = tr.rotations[0];
                    let q1 = tr.rotations[f];
                    let dot: f32 = (0..4).map(|k| q0[k] * q1[k]).sum::<f32>().abs().min(1.0);
                    if 2.0 * dot.acos().to_degrees() > 90.0 {
                        big += 1;
                    }
                }
                worst_frac = if n == 0 { 0.0 } else { big as f64 / n as f64 };
            }
        }
        done += 1;
        if worst_frac > 0.5 {
            wild += 1;
        }
        // 权重和<1 的顶点数（差额挂根骨那批）。
        let mut sumw: Vec<f32> = vec![0.0; g.positions.len()];
        for nd in &nodes {
            if let Some(sk) = &nd.skin {
                for (k, &v) in sk.vertices.iter().enumerate() {
                    let vi = v as usize;
                    if vi < sumw.len() {
                        sumw[vi] += sk.weights.get(k).copied().unwrap_or(0.0);
                    }
                }
            }
        }
        let partial = sumw.iter().filter(|w| **w > 0.0 && **w < 0.999).count();
        // 每帧撕边占「三角形边数」的比例：三只样本显示它能区分「正常(≤7%)」与「散架(≥25%)」。
        let edges = (g.indices.len() / 3) * 3;
        let rate = if a.frames == 0 || edges == 0 { 0.0 } else { worst_tear as f64 / a.frames as f64 / edges as f64 };
        rows.push((worst_frac, worst_tear, a.bones, stem.clone(), apak.clone()));
        rates.push((rate, worst_tear, a.frames, format!("{} [partial {}/{}]", stem, partial, g.positions.len())));
    }
    rows.sort_by(|a, b| b.0.total_cmp(&a.0));
    println!("量到 {done} 条动作 · 最狠帧 >90° 骨占比 >50% 的 {wild} 条（{:.0}%）", if done == 0 { 0.0 } else { wild as f64 * 100.0 / done as f64 });
    println!("占比最高的 10 条：");
    for (frac, tear, bones, stem, pak) in rows.iter().take(10) {
        println!("  {:5.1}% 骨{bones:<4} 撕边{tear:<7} {stem}（{pak}）", frac * 100.0);
    }
    rates.sort_by(|a, b| b.0.total_cmp(&a.0));
    let bad = rates.iter().filter(|r| r.0 > 0.20).count();
    println!("每帧撕边/边数 >20%（疑似散架）的 {} 条 / {}；>7% 的 {} 条", bad, rates.len(), rates.iter().filter(|r| r.0 > 0.07).count());
    println!("比例最高的 10 条：");
    for (rate, tear, frames, stem) in rates.iter().take(10) {
        println!("  {:5.1}% 撕边{tear:<7} 帧{frames:<4} {stem}", rate * 100.0);
    }
    println!("占比最低的 5 条：");
    for (frac, tear, bones, stem, pak) in rows.iter().rev().take(5) {
        println!("  {:5.1}% 骨{bones:<4} 撕边{tear:<7} {stem}（{pak}）", frac * 100.0);
    }
}
