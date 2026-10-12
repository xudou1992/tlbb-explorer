//! 对一个解包目录跑「能不能被解析器读懂」的体检（只读，不写任何东西）。
//!
//! 为什么需要：`extract_named` 按 cfg 身份把「包里有、清单没名字」的件解了出来，
//! 但**文件写出来不等于读得懂**。这里拿与导出同一条 `parse_mesh` 去吃这些文件，
//! 并且用**原有的解包树**当对照组：两边成功率相当，才说明新解出来的不是另一类东西。
//!
//! 用法：
//! ```text
//! tree_check --dir=D:\TLGL\.scratch\out\sidecar_tree --limit=200
//! tree_check --dir=D:\TLGL\.scratch\out\tree --limit=200   # 对照组
//! ```

use std::path::{Path, PathBuf};

use tlbb_core::preview::{parse_hierarchy, parse_mesh, parse_nodes};

fn main() {
    let mut dir = PathBuf::from("D:/TLGL/.scratch/out/sidecar_tree");
    let mut limit = 200usize;
    let mut ext = "mesh".to_string();
    for s in std::env::args().skip(1) {
        if let Some(v) = s.strip_prefix("--dir=") {
            dir = PathBuf::from(v);
        } else if let Some(v) = s.strip_prefix("--limit=") {
            limit = v.parse().unwrap_or(200);
        } else if let Some(v) = s.strip_prefix("--ext=") {
            ext = v.to_ascii_lowercase();
        } else {
            eprintln!("不认识的参数：{s}（可用 --dir= --limit= --ext=）");
            std::process::exit(2);
        }
    }

    let mut files: Vec<PathBuf> = Vec::new();
    collect(&dir, &ext, &mut files);
    files.sort();
    println!("== 解包目录体检：{}", dir.display());
    println!("  找到 .{ext} 文件 {n} 份，本轮只看前 {limit} 份", n = files.len());
    if files.is_empty() {
        println!("  × 目录里没有可比的文件（先跑 extract_named？）");
        return;
    }

    let mut ok = 0usize;
    let mut with_nodes = 0usize;
    let mut with_chain = 0usize;
    let mut verts = 0usize;
    let mut fails: Vec<(String, String)> = Vec::new();
    let heads: std::collections::BTreeMap<String, usize> = std::collections::BTreeMap::new();
    let mut head = std::collections::BTreeMap::new();

    for f in files.iter().take(limit) {
        let raw = match std::fs::read(f) {
            Ok(b) => b,
            Err(e) => {
                fails.push((rel(f, &dir), format!("读文件失败：{e}")));
                continue;
            }
        };
        *head.entry(String::from_utf8_lossy(&raw[..raw.len().min(9)]).to_string())
            .or_insert(0usize) += 1;
        match parse_mesh(&raw) {
            Ok(m) => {
                ok += 1;
                verts += m.geometry.positions.len();
                let n = parse_nodes(&raw);
                if !n.is_empty() {
                    with_nodes += 1;
                }
                if parse_hierarchy(&raw).is_some() {
                    with_chain += 1;
                }
            }
            Err(e) => fails.push((rel(f, &dir), format!("解析器原话：{e}（{} 字节）", raw.len()))),
        }
    }
    let _ = heads;

    let seen = ok + fails.len();
    println!("\n结果（{seen} 份）：");
    println!("  parse_mesh 认得：**{ok} / {seen}**（{r}%）",
        r = if seen > 0 { ok * 100 / seen } else { 0 });
    println!("  其中带骨架节点表的：{with_nodes} · 父骨链解得出的：{with_chain}");
    println!("  顶点合计：{verts}");
    println!("\n文件头前 9 字节的分布：");
    for (k, v) in &head {
        println!("  {v:>4} × {k:?}");
    }
    if !fails.is_empty() {
        println!("\n不认的（前 8，共 {} 条）：", fails.len());
        for (p, why) in fails.iter().take(8) {
            println!("  {p}\n      ← {why}");
        }
    }
}

fn collect(dir: &Path, ext: &str, out: &mut Vec<PathBuf>) {
    let Ok(rd) = std::fs::read_dir(dir) else { return };
    for e in rd.flatten() {
        let p = e.path();
        if p.is_dir() {
            collect(&p, ext, out);
        } else if p.extension().and_then(|x| x.to_str()).map(|x| x.to_ascii_lowercase()) == Some(ext.to_string())
        {
            out.push(p);
        }
    }
}

fn rel(p: &Path, base: &Path) -> String {
    p.strip_prefix(base).unwrap_or(p).display().to_string()
}
