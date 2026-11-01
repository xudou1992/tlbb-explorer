//! 逐骨拖拽与裂缝定位：一份网格 + 一条动作 + 一帧，报「谁把顶点搬走了、缝在哪两根骨之间裂开」。
//!
//! 撕边指标只给一个总数，看不出病灶。这里把裂开的边按两端**主导骨**归因，并给出
//! 两根骨在骨架里的层级距离：距离 1（父子）是正常关节拉伸，距离 ≥3 说明顶点挂到了
//! 不相干的骨上——那是配错，不是动作幅度。
//!
//! 用法（crates/core 下）：
//! ```text
//! cargo run --offline --release --example part_drag_report -- <网格包> <网格哈希> <动作包> <动作哈希> [帧号=10]
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{
    attach_bone_skin, parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose,
};

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 4 {
        eprintln!("需要：网格包 网格哈希 动作包 动作哈希 [帧号]");
        return;
    }
    let frame: usize = a.get(4).and_then(|s| s.parse().ok()).unwrap_or(10);
    let root = PathBuf::from("D:/TLGL");
    let open = |n: &str| Pak::open(root.join(format!("{n}.pak"))).expect("包打不开");
    let (mp, ap) = (open(&a[0]), open(&a[2]));
    let mh = u64::from_str_radix(&a[1], 16).expect("网格哈希");
    let ah = u64::from_str_radix(&a[3], 16).expect("动作哈希");
    let rm = mp.records().find(|r| r.hash == mh && r.stored > 0).expect("网格不在包里");
    let ra = ap.records().find(|r| r.hash == ah && r.stored > 0).expect("动作不在包里");
    let mraw = payload::decode(&mp, &rm).expect("网格解压失败").bytes;
    let araw = payload::decode(&ap, &ra).expect("动作解压失败").bytes;
    let layout = parse_mesh(&mraw).expect("网格解析失败");
    let h = parse_hierarchy(&mraw).expect("骨架解析失败");
    let nodes = attach_bone_skin(&h, &parse_nodes(&mraw), &mraw);
    let anim = parse_ani(&araw).expect("动作解析失败");
    let g = &layout.geometry;
    let bind = &g.positions;
    let f = frame.min(anim.frames.saturating_sub(1));
    let pal = pose::reanchored_palette(&h, &anim, f).expect("调色板算不出");
    let posed = pose::posed_vertices(&h, &pal, &nodes, bind).expect("蒙皮算不出");

    // 与 posed_vertices 同口径重建逐骨影响，用来做归因。
    let mut idx: HashMap<&str, usize> = HashMap::new();
    for (i, b) in h.bones.iter().enumerate() {
        idx.insert(b.name.as_str(), i);
    }
    let skroot = h.bones.iter().position(|b| b.parent.is_none()).unwrap_or(0);
    let mut lists: Vec<Vec<(usize, f32)>> = vec![Vec::new(); bind.len()];
    for nd in &nodes {
        let Some(skin) = &nd.skin else { continue };
        let Some(&bi) = idx.get(nd.name.as_str()) else { continue };
        for (&v, &w) in skin.vertices.iter().zip(skin.weights.iter()) {
            let vi = v as usize;
            if vi < lists.len() && w.is_finite() && w > 0.0 {
                lists[vi].push((bi, w));
            }
        }
    }
    let dom: Vec<usize> = lists
        .iter()
        .map(|l| {
            if l.is_empty() {
                return skroot;
            }
            l.iter().max_by(|x, y| x.1.partial_cmp(&y.1).unwrap()).map(|(b, _)| *b).unwrap_or(skroot)
        })
        .collect();
    let dist = |i: usize| -> f64 {
        let d = [
            posed[i][0] as f64 - bind[i][0] as f64,
            posed[i][1] as f64 - bind[i][1] as f64,
            posed[i][2] as f64 - bind[i][2] as f64,
        ];
        (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
    };

    println!("第 {f} 帧 · 骨 {} · 顶点 {} · 三角形 {}", h.bones.len(), bind.len(), g.indices.len() / 3);
    println!("逐骨（主导骨归因）：顶点数 · 位移中位 · 位移最大 · 该骨调色板转角");
    let mut rows: Vec<(String, usize, f64, f64)> = Vec::new();
    for bi in 0..h.bones.len() {
        let vs: Vec<usize> = (0..bind.len()).filter(|v| dom[*v] == bi).collect();
        if vs.is_empty() {
            continue;
        }
        let mut d: Vec<f64> = vs.iter().map(|v| dist(*v)).collect();
        d.sort_by(|x, y| x.total_cmp(y));
        rows.push((h.bones[bi].name.clone(), vs.len(), d[d.len() / 2], *d.last().unwrap()));
    }
    rows.sort_by(|x, y| y.3.partial_cmp(&x.3).unwrap());
    for (n, c, med, mx) in rows.iter().take(14) {
        println!("  {n:<28} {c:>4} 顶点 · 中位 {med:.3} · 最大 {mx:.3}");
    }

    // 裂缝：逐边量 posed/bind 长度比，两端主导骨 + 层级距离一起报。
    let depth = |mut b: usize| -> usize {
        let mut k = 0;
        while let Some(p) = h.bones[b].parent {
            b = p;
            k += 1;
        }
        k
    };
    let lca_dist = |x: usize, y: usize| -> usize {
        let (mut a, mut b2, mut k) = (x, y, 0usize);
        while a != b2 && k < 64 {
            if depth(a) > depth(b2) { a = h.bones[a].parent.unwrap_or(a); } else { b2 = h.bones[b2].parent.unwrap_or(b2); }
            k += 1;
        }
        depth(x) + depth(y) - 2 * depth(a)
    };
    let mut edges: Vec<(f64, usize, usize, usize, usize)> = Vec::new();
    let mut seen: HashMap<(u32, u32), ()> = HashMap::new();
    for tri in g.indices.chunks(3) {
        if tri.len() != 3 { continue; }
        for k in 0..3 {
            let (i, j) = (tri[k] as usize, tri[(k + 1) % 3] as usize);
            let key = (i.min(j) as u32, i.max(j) as u32);
            if seen.insert(key, ()).is_some() { continue; }
            let bl = {
                let d = [
                    bind[i][0] as f64 - bind[j][0] as f64,
                    bind[i][1] as f64 - bind[j][1] as f64,
                    bind[i][2] as f64 - bind[j][2] as f64,
                ];
                (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
            };
            let pl = {
                let d = [
                    posed[i][0] as f64 - posed[j][0] as f64,
                    posed[i][1] as f64 - posed[j][1] as f64,
                    posed[i][2] as f64 - posed[j][2] as f64,
                ];
                (d[0] * d[0] + d[1] * d[1] + d[2] * d[2]).sqrt()
            };
            if bl > 1e-6 {
                edges.push((pl / bl, i, j, dom[i], dom[j]));
            }
        }
    }
    let total = edges.len();
    edges.sort_by(|x, y| y.0.partial_cmp(&x.0).unwrap());
    let over = edges.iter().filter(|e| e.0 > 1.5).count();
    println!("边 {total} 条 · 拉长 >1.5 倍 {over} 条 · 最大 {:.1} 倍", edges.first().map(|e| e.0).unwrap_or(0.0));
    println!("拉得最长的 12 条边：倍数 · 两端主导骨 · 层级距离");
    for (r, i, j, bi, bj) in edges.iter().take(12) {
        println!(
            "  {r:>5.1}x  {i}->{j}  {} ↔ {}  层级 {}",
            h.bones[*bi].name, h.bones[*bj].name, lca_dist(*bi, *bj)
        );
    }
    let mut far: Vec<(f64, String, String)> = edges
        .iter()
        .filter(|(r, _, _, bi, bj)| *r > 1.5 && lca_dist(*bi, *bj) >= 3)
        .map(|(r, _, _, bi, bj)| (*r, h.bones[*bi].name.clone(), h.bones[*bj].name.clone()))
        .collect();
    far.sort_by(|x, y| y.0.partial_cmp(&x.0).unwrap());
    println!("其中两端层级 ≥3（挂错骨的特征，不是关节幅度）：{} 条", far.len());
    for (r, x, y) in far.iter().take(10) {
        println!("  {r:.1}x {x} ↔ {y}");
    }
}
