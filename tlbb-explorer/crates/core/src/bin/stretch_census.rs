//! 全库边长尺普查（探针，不改判据）：把「非锚帧按边长仍然撕」推成一族的数，
//! 并且**一次量两种口径**：现口径（轨道当局部、沿父链复合）与试错口径（轨道直接当世界）。
//!
//! 要回答的问题：世界口径的好坏，是不是跟着「带影响表的骨 / 骨架骨」这个覆盖率走
//! （daishu 15/47≈32% 变好、machao 63/83≈76% 变差，正好落在两端）。
//!
//! 用法：
//! ```text
//! stretch_census --root=D:\TLGL\.scratch\out\sidecar_tree [--limit=120]
//! ```

use std::path::{Path, PathBuf};

use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose};
use tlbb_core::preview::{Anim, Node, SkeletonHierarchy};

fn arg(argv: &[String], name: &str) -> Option<String> {
    let want = format!("--{name}=");
    argv.iter()
        .skip(1)
        .find_map(|a| a.strip_prefix(&want))
        .map(|s| s.trim_matches('"').to_string())
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    let Ok(rd) = std::fs::read_dir(dir) else { return };
    for e in rd.flatten() {
        let p = e.path();
        if p.is_dir() {
            walk(&p, out);
        } else if p.extension().and_then(|x| x.to_str()) == Some("mesh") {
            out.push(p);
        }
    }
}

/// 给这份网格找一条动作：先同目录的 `ani/` 子目录，再同目录任何 `.ani`。
fn first_ani(mesh: &Path) -> Option<PathBuf> {
    let dir = mesh.parent()?;
    let sub = dir.join("ani");
    for d in [sub.as_path(), dir] {
        let Ok(rd) = std::fs::read_dir(d) else { continue };
        let mut cands: Vec<PathBuf> = rd
            .flatten()
            .map(|e| e.path())
            .filter(|p| p.extension().and_then(|x| x.to_str()) == Some("ani"))
            .collect();
        cands.sort();
        if let Some(p) = cands.into_iter().next() {
            return Some(p);
        }
    }
    None
}

/// 一种口径下的撕账。
#[derive(Clone)]
struct Row {
    name: String,
    verts: usize,
    skinned_bones: usize,
    bones: usize,
    over2: usize,
    edges: usize,
    worst: f64,
}

fn measure(
    h: &SkeletonHierarchy,
    nodes: &[Node],
    pos: &[[f32; 3]],
    idx: &[u16],
    anchor: &[[f32; 16]],
    world_at: &dyn Fn(usize) -> Vec<[f32; 16]>,
    frames: &[usize],
) -> Option<(usize, usize, f64)> {
    let (mut o2, mut ed, mut worst) = (0usize, 0usize, 0f64);
    for &fr in frames {
        let world = world_at(fr);
        let pal = pose::skin_palette(h, anchor, &world)?;
        let posed = pose::posed_vertices(h, &pal, nodes, pos)?;
        let s = pose::edge_stretch(pos, &posed, idx);
        o2 += s.over20;
        ed += s.edges;
        worst = worst.max(s.max_ratio);
    }
    if ed == 0 {
        return None;
    }
    Some((o2, ed, worst))
}

/// 世界口径的「这一帧的世界矩阵」：轨道值直接当世界，没轨道的骨用 bind 世界矩阵兜底。
fn world_direct(
    h: &SkeletonHierarchy,
    a: &Anim,
    bindw: &[[f32; 16]],
    fr: usize,
) -> Vec<[f32; 16]> {
    let mut out = bindw.to_vec();
    for t in &a.tracks {
        if t.bone.is_empty() || t.rotations.is_empty()
            || t.positions.is_empty() || t.scales.is_empty()
        {
            continue;
        }
        if let Some(i) = h.bones.iter().position(|x| x.name == t.bone) {
            let k = fr.min(t.rotations.len() - 1)
                .min(t.positions.len() - 1)
                .min(t.scales.len() - 1);
            out[i] = pose::trs_matrix(&t.rotations[k], t.positions[k], t.scales[k]);
        }
    }
    out
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let root = PathBuf::from(arg(&argv, "root").unwrap_or_else(|| {
        eprintln!("用法：stretch_census --root=DIR [--limit=N]");
        std::process::exit(2);
    }));
    let limit: usize = arg(&argv, "limit").map_or(120, |s| s.parse().unwrap_or(120));

    let mut files = Vec::new();
    walk(&root, &mut files);
    files.sort();
    files.truncate(limit);
    println!("== 边长尺普查（双口径）：{}（取前 {} 份 .mesh）", root.display(), files.len());

    let mut cur: Vec<Row> = Vec::new();
    let mut wor: Vec<Row> = Vec::new();
    let mut mix: Vec<Row> = Vec::new();
    // 混口径这条臂到底动了什么：数一下「没有 bind 记录、但有轨道」的骨——
    // 只有这批骨在两条口径下取值不同，其它骨两条臂本来就一样。
    let (mut acc_none_bone, mut acc_none_track) = (0usize, 0usize);
    let (mut no_hier, mut no_nodes, mut no_skin, mut no_ani) = (0, 0, 0, 0);

    for f in &files {
        let Ok(raw) = std::fs::read(f) else { continue };
        let Ok(layout) = parse_mesh(&raw) else { continue };
        let Some(h) = parse_hierarchy(&raw) else { no_hier += 1; continue };
        let nodes = parse_nodes(&raw);
        if nodes.is_empty() { no_nodes += 1; continue; }
        let with_skin = nodes.iter().filter(|n| n.skin.is_some()).count();
        if with_skin == 0 { no_skin += 1; continue; }
        let Some(ani) = first_ani(f) else { no_ani += 1; continue };
        let Ok(raw_ani) = std::fs::read(&ani) else { no_ani += 1; continue };
        let Some(a) = parse_ani(&raw_ani) else { no_ani += 1; continue };

        let g = &layout.geometry;
        let frames: Vec<usize> = (0..a.frames).step_by(1.max(a.frames / 8)).collect();
        acc_none_bone += h.bones.iter().filter(|b| b.bind.is_none()).count();
        acc_none_track += h
            .bones
            .iter()
            .filter(|b| b.bind.is_none() && a.tracks.iter().any(|t| t.bone == b.name))
            .count();
        let anchor = pose::pose_frame(&h, &a, 0);
        let bindw = pose::bind_worlds(&h);
        let name = f.file_stem().unwrap().to_string_lossy().to_string();
        let base = Row {
            name,
            verts: g.positions.len(),
            skinned_bones: with_skin,
            bones: h.bones.len(),
            over2: 0,
            edges: 0,
            worst: 0.0,
        };

        if let Some((o2, ed, mx)) = measure(
            &h,
            &nodes,
            &g.positions,
            &g.indices,
            &anchor,
            &|fr| pose::pose_frame(&h, &a, fr),
            &frames,
        ) {
            let mut r = base.clone();
            r.over2 = o2;
            r.edges = ed;
            r.worst = mx;
            cur.push(r);
        }

        let anchor_w = world_direct(&h, &a, &bindw, 0);
        if let Some((o2, ed, mx)) = measure(
            &h,
            &nodes,
            &g.positions,
            &g.indices,
            &anchor_w,
            &|fr| world_direct(&h, &a, &bindw, fr),
            &frames,
        ) {
            let mut r = base.clone();
            r.over2 = o2;
            r.edges = ed;
            r.worst = mx;
            wor.push(r);
        }

        // 第三条臂（混口径）：只有**自己带 96B 绑定记录**的骨把轨道值当世界用，
        // 其余的骨仍沿父链复合——看两条口径各管哪一半。
        let mixed = |fr: usize| -> Vec<[f32; 16]> {
            let hw = pose::pose_frame(&h, &a, fr);
            let ww = world_direct(&h, &a, &bindw, fr);
            hw.into_iter()
                .enumerate()
                .map(|(i, m)| if h.bones[i].bind.is_some() { ww[i] } else { m })
                .collect()
        };
        let anchor_m = mixed(0);
        if let Some((o2, ed, mx)) = measure(
            &h,
            &nodes,
            &g.positions,
            &g.indices,
            &anchor_m,
            &mixed,
            &frames,
        ) {
            let mut r = base.clone();
            r.over2 = o2;
            r.edges = ed;
            r.worst = mx;
            mix.push(r);
        }
    }

    let paired = cur.iter().filter(|r| wor.iter().any(|w| w.name == r.name)).count();
    println!(
        "\n两种口径都量到的份数：{paired} · 只量到现口径 {} · 跳过（无骨架 {} / 无节点 {} / 无表 {} / 无动作 {}）",
        cur.len() - paired, no_hier, no_nodes, no_skin, no_ani
    );
    if cur.is_empty() {
        return;
    }

    let delta = |r: &Row| -> Option<f64> {
        wor.iter().find(|w| w.name == r.name).map(|w| w.worst - r.worst)
    };
    let better = cur.iter().filter(|r| delta(r).map_or(false, |d| d < -0.25 * r.worst)).count();
    let worse = cur.iter().filter(|r| delta(r).map_or(false, |d| d > 0.25 * r.worst)).count();
    println!(
        "世界口径把峰值压掉 ≥25% 的：{better} 份 · 反而涨 ≥25% 的：{worse} 份 · 其余：{} 份",
        paired - better - worse
    );

    println!(
        "混口径与世界口径的差别只在「没 bind 记录却有轨道」的骨上：这些份里无 bind 骨累计 {acc_none_bone} 根，其中带轨道的 {acc_none_track} 根"
    );
    let arm = |v: &Vec<Row>, name: &str| {
        let got: Vec<(&Row, f64)> = cur
            .iter()
            .filter_map(|r| v.iter().find(|x| x.name == r.name).map(|x| (r, x.worst)))
            .collect();
        if got.is_empty() {
            println!("  {name}：没量到");
            return;
        }
        let mean = got.iter().map(|(_, w)| *w).sum::<f64>() / got.len() as f64;
        let win = got.iter().filter(|(r, w)| *w < r.worst * 0.75).count();
        let bad = got.iter().filter(|(r, w)| *w > r.worst * 1.25).count();
        println!(
            "  {name}：配对 {} 份 · 峰值均值 {mean:.1}× · 比现口径压掉 ≥25% 的 {win} 份 · 涨 ≥25% 的 {bad} 份",
            got.len()
        );
    };
    arm(&wor, "世界口径（轨道全当世界）");
    arm(&mix, "混口径（有记录的骨才当世界）");

    for (lo, hi) in [(0.0f64, 0.34), (0.34, 0.70), (0.70, 1.01)] {
        let grp: Vec<&Row> = cur
            .iter()
            .filter(|r| {
                let cv = r.skinned_bones as f64 / r.bones.max(1) as f64;
                cv >= lo && cv < hi
            })
            .collect();
        if grp.is_empty() {
            continue;
        }
        let x: f64 = grp.iter().map(|r| r.worst).sum::<f64>() / grp.len() as f64;
        let ws: Vec<f64> = grp.iter().filter_map(|r| wor.iter().find(|w| w.name == r.name).map(|w| w.worst)).collect();
        if ws.is_empty() {
            continue;
        }
        let y: f64 = ws.iter().sum::<f64>() / ws.len() as f64;
        println!(
            "  带表骨/骨架骨 落在 {:.0}%~{:.0}%：{} 份（配对 {} 份）· 现口径峰值均值 {:.1}× → 世界口径 {:.1}×（{}）",
            lo * 100.0,
            hi * 100.0,
            grp.len(),
            ws.len(),
            x,
            y,
            if y < x { "世界口径更好" } else { "不更好" }
        );
    }

    // 同族 `_b1…_b8` 与部件（yifu/shoutao/toufa…）共用一副骨架与一批动作，
    // 按文件算的份数会虚高——这里按「族」再数一遍。
    let fam = |n: &str| -> String {
        let mut base = n.to_string();
        if let Some(pos) = base.rfind("_b") {
            let tail = &base[pos + 2..];
            if tail.len() <= 3 && tail.chars().all(|c| c.is_ascii_digit()) {
                base = base[..pos].to_string();
            }
        }
        // 部件后缀也去掉：同一只怪的 yifu / shoutao / toufa 各算一份会重复计数
        for suf in ["_yifu_001", "_yifu_002", "_shoutao_001", "_toufa_001", "_lian_001"] {
            if let Some(stripped) = base.strip_suffix(suf) {
                base = stripped.to_string();
            }
        }
        base
    };
    let mut byfam: Vec<(String, f64, f64, usize)> = Vec::new();
    for r in &cur {
        let f = fam(&r.name);
        let w = wor.iter().find(|x| x.name == r.name).map(|x| x.worst).unwrap_or(r.worst);
        match byfam.iter_mut().find(|x| x.0 == f) {
            Some(e) => {
                if r.worst > e.1 {
                    e.1 = r.worst;
                }
                if w > e.2 {
                    e.2 = w;
                }
                e.3 += 1;
            }
            None => byfam.push((f, r.worst, w, 1)),
        }
    }
    byfam.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    println!("
按族去重：{} 个族（上面是 {} 份文件）", byfam.len(), cur.len());
    println!("族 · 份数 · 现口径峰值 · 世界口径峰值");
    for (f, c, w, n) in byfam.iter().take(16) {
        println!("  {:<44} {:>2} 份 · {:>6.1}× → {:>6.1}×", f, n, c, w);
    }

    let mut srt = cur.clone();
    srt.sort_by(|a, b| b.worst.partial_cmp(&a.worst).unwrap());
    println!("\n现口径撕得最狠的 12 份（现 → 世界 · 带表骨/骨架 · 顶点 · 撕边/总边）：");
    for r in srt.iter().take(12) {
        match wor.iter().find(|w| w.name == r.name) {
            Some(w) => println!(
                "  {:>7.1}→{:>7.1}x 骨 {:>3}/{:<3} 顶点 {:>6} 撕边 {:>6}/{:<6} {}",
                r.worst, w.worst, r.skinned_bones, r.bones, r.verts, r.over2, r.edges, r.name
            ),
            None => println!(
                "  {:>7.1}→(世界口径没量到) 骨 {:>3}/{:<3} 顶点 {:>6} {}",
                r.worst, r.skinned_bones, r.bones, r.verts, r.name
            ),
        }
    }
}
