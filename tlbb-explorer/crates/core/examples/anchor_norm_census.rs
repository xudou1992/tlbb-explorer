//! 「锚口径 × 权重和<1 的处理」四组合普查。
//!
//! 目的：归一化（和<1 按比例归一）会缩小「bind 锚比第 0 帧锚更差」的差距（见 2026-10-29 第一百一十轮），
//! 需要先确认在归一化语义下，「第 0 帧锚优于 bind 锚」是否仍然普遍成立，再决定要不要改语义、以及护栏阈值怎么定。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example anchor_norm_census [份数上限=60]
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{attach_bone_skin, parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose, Anim, Node, SkeletonHierarchy};

fn posed(
    h: &SkeletonHierarchy,
    anim: &Anim,
    frame: usize,
    anchor_bind: bool,
    normalize: bool,
    nodes: &[Node],
    pos: &[[f32; 3]],
) -> Option<Vec<[f32; 3]>> {
    let world = pose::pose_frame(h, anim, frame);
    let anchor = if anchor_bind { pose::bind_worlds(h) } else { pose::pose_frame(h, anim, 0) };
    let pal = pose::skin_palette(h, &anchor, &world)?;
    // 顶点 → (骨, 权重) 列表
    let mut idx: HashMap<&str, usize> = HashMap::new();
    for (i, b) in h.bones.iter().enumerate() {
        idx.insert(b.name.as_str(), i);
    }
    let root = h.bones.iter().position(|b| b.parent.is_none()).unwrap_or(0);
    let mut lists: Vec<Vec<(usize, f32)>> = vec![Vec::new(); pos.len()];
    for nd in nodes {
        let Some(sk) = &nd.skin else { continue };
        let Some(&bi) = idx.get(nd.name.as_str()) else { continue };
        for (&v, &w) in sk.vertices.iter().zip(sk.weights.iter()) {
            if (v as usize) < lists.len() && w > 0.0 {
                lists[v as usize].push((bi, w));
            }
        }
    }
    let mut out = pos.to_vec();
    for (vi, list) in lists.iter_mut().enumerate() {
        let sum: f32 = list.iter().map(|(_, w)| *w).sum();
        if sum <= f32::EPSILON {
            continue;
        }
        let p = pos[vi];
        let mut acc = [0f32; 3];
        for &(j, w) in list.iter() {
            // 与 unify_weights 同口径：和>1 一律按和归一；和<1 时看模式（归一 或 差额挂根骨）。
            let ww = if normalize || sum > 1.0 { w / sum } else { w };
            let m = &pal[j];
            acc[0] += ww * (p[0] * m[0] + p[1] * m[4] + p[2] * m[8] + m[12]);
            acc[1] += ww * (p[0] * m[1] + p[1] * m[5] + p[2] * m[9] + m[13]);
            acc[2] += ww * (p[0] * m[2] + p[1] * m[6] + p[2] * m[10] + m[14]);
        }
        if !normalize && sum < 1.0 {
            let m = &pal[root];
            let ww = 1.0 - sum;
            acc[0] += ww * (p[0] * m[0] + p[1] * m[4] + p[2] * m[8] + m[12]);
            acc[1] += ww * (p[0] * m[1] + p[1] * m[5] + p[2] * m[9] + m[13]);
            acc[2] += ww * (p[0] * m[2] + p[1] * m[6] + p[2] * m[10] + m[14]);
        }
        out[vi] = acc;
    }
    Some(out)
}

fn main() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    let con = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .expect("清单打不开");
    let limit: usize = std::env::args().nth(1).and_then(|s| s.parse().ok()).unwrap_or(60);

    let mut meshes: HashMap<(String, String), (String, u64)> = HashMap::new();
    {
        let mut st = con.prepare("SELECT coalesce(dir,''), name, hash, coalesce(pak,'') FROM resources WHERE ext='.mesh' AND coalesce(pak,'') <> ''").unwrap();
        for (dir, name, hash, pak) in st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?))).unwrap().flatten() {
            meshes.insert((dir, name.trim_end_matches(".mesh").to_string()), (pak, u64::from_str_radix(&hash, 16).unwrap_or(0)));
        }
    }
    let mut anis: Vec<(String, String, u64, String)> = Vec::new();
    {
        let mut st = con.prepare("SELECT coalesce(dir,''), name, hash, coalesce(pak,'') FROM resources WHERE ext='.ani' AND coalesce(pak,'') <> '' ORDER BY hash").unwrap();
        for (dir, name, hash, pak) in st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?, r.get::<_, String>(3)?))).unwrap().flatten() {
            anis.push((dir, name.trim_end_matches(".ani").to_string(), u64::from_str_radix(&hash, 16).unwrap_or(0), pak));
        }
    }
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let (mut done, mut f0_wins_fill, mut f0_wins_norm) = (0usize, 0usize, 0usize);
    let (mut a_fill, mut b_fill, mut a_norm, mut b_norm) = (0f64, 0f64, 0f64, 0f64);
    for (dir, stem, ah, apak) in &anis {
        if done >= limit { break; }
        let dir2 = dir.trim_end_matches("/ani").trim_end_matches('/').to_string();
        let mut found = None;
        let mut cut = stem.as_str();
        for _ in 0..4 {
            let Some((g, _)) = cut.rsplit_once('_') else { break };
            cut = g;
            if let Some(m) = meshes.get(&(dir2.clone(), cut.to_string())) { found = Some(m.clone()); break; }
        }
        let Some((mpak, mh)) = found else { continue };
        for k in [apak, &mpak] {
            if !paks.contains_key(k) {
                if let Ok(p) = Pak::open(root.join(format!("{k}.pak"))) { paks.insert(k.clone(), p); }
            }
        }
        let (Some(ap), Some(mp)) = (paks.get(apak), paks.get(&mpak)) else { continue };
        let Some(ar) = ap.records().find(|r| r.hash == *ah && r.stored > 0) else { continue };
        let Ok(araw) = payload::decode(ap, &ar).map(|d| d.bytes) else { continue };
        let Some(mr) = mp.records().find(|r| r.hash == mh && r.stored > 0) else { continue };
        let Ok(mraw) = payload::decode(mp, &mr).map(|d| d.bytes) else { continue };
        let (Ok(layout), Some(h), Some(anim)) = (parse_mesh(&mraw), parse_hierarchy(&mraw), parse_ani(&araw)) else { continue };
        if h.bones.len() != anim.bones { continue; }
        let g = &layout.geometry;
        if g.positions.is_empty() { continue; }
        let nodes = attach_bone_skin(&h, &parse_nodes(&mraw), &mraw);
        let total = |bind_anchor: bool, norm: bool| -> Option<usize> {
            let mut s = 0usize;
            for f in 0..anim.frames {
                let out = posed(&h, &anim, f, bind_anchor, norm, &nodes, &g.positions)?;
                s += pose::edge_stretch(&g.positions, &out, &g.indices).over15;
            }
            Some(s)
        };
        let (Some(f0f), Some(bf), Some(f0n), Some(bn)) = (total(false, false), total(true, false), total(false, true), total(true, true)) else { continue };
        done += 1;
        if f0f < bf { f0_wins_fill += 1; }
        if f0n < bn { f0_wins_norm += 1; }
        a_fill += f0f as f64; b_fill += bf as f64; a_norm += f0n as f64; b_norm += bn as f64;
    }
    println!("量到 {done} 条动作");
    println!("现语义（差额挂根骨）：第0帧锚合计 {a_fill:.0} · bind 锚 {b_fill:.0} · 第0帧更低的 {f0_wins_fill}/{done}");
    println!("归一化：第0帧锚合计 {a_norm:.0} · bind 锚 {b_norm:.0} · 第0帧更低的 {f0_wins_norm}/{done}");
}
