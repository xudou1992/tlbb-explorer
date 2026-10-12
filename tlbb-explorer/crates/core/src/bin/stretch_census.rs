//! 全库边长尺普查（探针，不改判据）：把「非锚帧按边长仍然撕」从 6 份样本推成一族的数。
//!
//! 与 `stretch_probe` 同一把尺（`pose::edge_stretch`）、同一个锚（frame0），
//! 只是去掉逐帧打印，改成按目录扫几百份网格各配一条动作，末尾给分布。
//!
//! 用法：
//! ```text
//! stretch_census --root=D:\TLGL\.scratch\out\sidecar_tree [--limit=120]
//! ```

use std::path::{Path, PathBuf};

use tlbb_core::preview::{bone_count, parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose};

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
    println!("== 边长尺普查：{}（取前 {} 份 .mesh）", root.display(), files.len());

    let mut rows: Vec<(String, usize, usize, f64, usize, usize)> = Vec::new();
    let (mut no_ani, mut no_hier, mut no_nodes, mut no_bone) = (0, 0, 0, 0);

    for f in &files {
        let Ok(raw) = std::fs::read(f) else { continue };
        let Some(layout) = parse_mesh(&raw).ok() else { continue };
        let Some(h) = parse_hierarchy(&raw) else { no_hier += 1; continue };
        let nodes = parse_nodes(&raw);
        if nodes.is_empty() { no_nodes += 1; continue; }
        let with_skin = nodes.iter().filter(|n| n.skin.is_some()).count();
        if with_skin == 0 { no_bone += 1; continue; }
        let Some(ani) = first_ani(f) else { no_ani += 1; continue };
        let Ok(raw_ani) = std::fs::read(&ani) else { no_ani += 1; continue };
        let Some(a) = parse_ani(&raw_ani) else { no_ani += 1; continue };

        let g = &layout.geometry;
        let anchor = pose::pose_frame(&h, &a, 0);
        let frames: Vec<usize> = (0..a.frames).step_by(1.max(a.frames / 8)).collect();
        let (mut sum20, mut edges, mut worst) = (0usize, 0usize, 0f64);
        for &fr in &frames {
            let world = pose::pose_frame(&h, &a, fr);
            let Some(d) = pose::skin_palette(&h, &anchor, &world) else { continue };
            let Some(posed) = pose::posed_vertices(&h, &d, &nodes, &g.positions) else { continue };
            let s = pose::edge_stretch(&g.positions, &posed, &g.indices);
            sum20 += s.over20;
            edges += s.edges;
            worst = worst.max(s.max_ratio);
        }
        if edges == 0 { continue; }
        rows.push((
            f.file_stem().unwrap().to_string_lossy().to_string(),
            g.positions.len(),
            with_skin,
            worst,
            sum20,
            edges,
        ));
    }

    println!(
        "\n量到的份数：{} · 跳过（无骨架 {} / 无节点 {} / 无表 {} / 无动作或动作读不出 {}）",
        rows.len(), no_hier, no_nodes, no_bone, no_ani
    );
    if rows.is_empty() { return; }
    let any_tear = rows.iter().filter(|r| r.5 / 8 > 0).count();
    let heavy = rows.iter().filter(|r| r.4 as f64 / r.5 as f64 > 0.05).count();
    let mut ms: Vec<f64> = rows.iter().map(|r| r.3).collect();
    ms.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let pct = |q: f64| ms[((ms.len() as f64 - 1.0) * q) as usize];
    println!("至少一条边被拉开过 2 倍的：{any_tear} 份");
    println!("撕边占比 >5% 的：{heavy} 份");
    println!("单份最大边长倍数：P50 = {:.1}× · P90 = {:.1}× · 最差 = {:.1}×", pct(0.5), pct(0.9), ms[ms.len() - 1]);
    let mut srt = rows.clone();
    srt.sort_by(|a, b| b.3.partial_cmp(&a.3).unwrap());
    println!("\n撕得最狠的 12 份（最大倍数 · 撕边合计/边合计 · 带表骨数 · 顶点）：");
    for r in srt.iter().take(12) {
        println!("  {:>7.1}×  {:>6}/{:<6} 骨 {:>3} 顶点 {:>6}  {}", r.3, r.4, r.5, r.2, r.1, r.0);
    }
    println!("\n撕得最轻的 8 份：");
    for r in srt.iter().rev().take(8) {
        println!("  {:>7.1}×  {:>6}/{:<6} 骨 {:>3} 顶点 {:>6}  {}", r.3, r.4, r.5, r.2, r.1, r.0);
    }
    let _ = bone_count;
}
