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
    let mut tsv: Option<PathBuf> = None;
    let mut limit = 200usize;
    let mut ext = "mesh".to_string();
    for s in std::env::args().skip(1) {
        if let Some(v) = s.strip_prefix("--dir=") {
            dir = PathBuf::from(v);
        } else if let Some(v) = s.strip_prefix("--limit=") {
            limit = v.parse().unwrap_or(200);
        } else if let Some(v) = s.strip_prefix("--ext=") {
            ext = v.to_ascii_lowercase();
        } else if let Some(v) = s.strip_prefix("--tsv=") {
            tsv = Some(PathBuf::from(v.trim_matches('"')));
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
    // 权重表这一层单独数：GLB 那边看到「整张网格挂根骨、播放时一动不动」，
    // 到底是 .mesh 里就没有 96B 记录，还是记录有、后面跟的影响顶点表没认出来，
    // 只有回到源文件才分得开。
    let mut no_nodes: Vec<String> = Vec::new();
    let mut nodes_but_no_skin: Vec<(String, usize)> = Vec::new();
    let mut partial: Vec<(String, usize, usize)> = Vec::new();
    let mut full = 0usize;
    let mut tsv_rows: Vec<String> = Vec::new();
    // 硬权重（单骨 1.0）vs 混合权重（多骨或小数权重）的全库计数
    let mut g_cov = 0usize;
    let mut g_hard = 0usize;
    let mut g_multi = 0usize;
    let mut g_frac = 0usize;
    let mut g_files_mix = 0usize;
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
                let total = m.geometry.positions.len();
                let skinned = n.iter().filter(|x| x.skin.is_some()).count();
                // 「硬权重 vs 混合权重」这一层要数出来才知道：撕的直接原因是每顶点
                // 只挂一根骨、权重 1.0（接缝没有过渡带）。若全库绝大多数顶点都是这种，
                // 那「混合权重在引擎里另有一处」就是仍未排除的方向；若相当比例的顶点
                // 本来就有多根骨、小数权重，那这份部件全 1.0 就是源数据本身如此。
                let mut tally: std::collections::HashMap<u32, (usize, f32, bool)> =
                    std::collections::HashMap::new();
                for nd in &n {
                    let Some(sk) = &nd.skin else { continue };
                    for (&v, &w) in sk.vertices.iter().zip(sk.weights.iter()) {
                        if !w.is_finite() || w <= 0.0 {
                            continue; // 0 权重不占槽位，与 posed_vertices 同口径
                        }
                        let e = tally.entry(v).or_insert((0, 0.0, false));
                        e.0 += 1;
                        e.1 += w;
                        e.2 |= (w - 1.0).abs() > 1e-4; // 出现过非 1.0 的权重
                    }
                }
                let mut hard = 0usize;
                let mut multi = 0usize;
                let mut frac = 0usize;
                for (&v, (c, _, f)) in &tally {
                    if (v as usize) >= total {
                        continue;
                    }
                    if *c > 1 {
                        multi += 1;
                    } else if !f {
                        hard += 1;
                    }
                    if *f {
                        frac += 1;
                    }
                }
                g_hard += hard;
                g_multi += multi;
                g_frac += frac;
                g_cov += tally.values().filter(|e| e.0 > 0).count().min(total);
                if multi > 0 || frac > 0 {
                    g_files_mix += 1;
                }
                let covered = tally.keys().filter(|&&v| (v as usize) < total).count();
                tsv_rows.push(format!(
                    "{}|{}|{}|{}|{}|{}|{}|{}",
                    rel(f, &dir),
                    n.len(),
                    skinned,
                    covered,
                    total,
                    hard,
                    multi,
                    frac
                ));
                if n.is_empty() {
                    no_nodes.push(rel(f, &dir));
                } else if skinned == 0 {
                    nodes_but_no_skin.push((rel(f, &dir), n.len()));
                } else if total > 0 && covered == total {
                    full += 1;
                } else {
                    partial.push((rel(f, &dir), covered, total));
                }
            }
            Err(e) => fails.push((rel(f, &dir), format!("解析器原话：{e}（{} 字节）", raw.len()))),
        }
    }
    let _ = heads;

    if let Some(w) = tsv.as_ref() {
        use std::io::Write;
        match std::fs::File::create(w) {
            Ok(mut fh) => {
                let _ = writeln!(fh, "file|nodes|withSkin|covered|verts|hard|multi|frac");
                for r in &tsv_rows {
                    let _ = writeln!(fh, "{r}");
                }
                println!("每份明细写了 {}（{} 行）", w.display(), tsv_rows.len());
            }
            Err(e) => println!("明细写不出去：{e}"),
        }
    }
    let seen = ok + fails.len();
    println!("\n结果（{seen} 份）：");
    println!("  parse_mesh 认得：**{ok} / {seen}**（{r}%）",
        r = if seen > 0 { ok * 100 / seen } else { 0 });
    println!("  其中带骨架节点表的：{with_nodes} · 父骨链解得出的：{with_chain}");
    println!("  顶点合计：{verts}");
    println!(
        "  带表顶点 {g_cov} 个：单骨权重 1.0（硬）{g_hard} · 多骨 {g_multi} · 含小数权重 {g_frac}（{} 份文件里出现过混合）",
        g_files_mix
    );
    println!("\n权重表分档（决定导出后网格跟不跟骨架走）：");
    println!("  一份都没有 96B 节点记录：{} 份", no_nodes.len());
    println!("  有节点记录但后面没认出影响表：{} 份", nodes_but_no_skin.len());
    println!("  有影响表、覆盖全部顶点：{full} 份 · 只覆盖一部分：{} 份", partial.len());
    for p in no_nodes.iter().take(6) {
        println!("    无节点 {p}");
    }
    for (p, n) in nodes_but_no_skin.iter().take(6) {
        println!("    有 {n} 条节点却无影响表 {p}");
    }
    let mut ps = partial.clone();
    ps.sort_by_key(|(_, c, t)| (t - c) as i64);
    println!("  缺口最大的几份（覆盖/总数）：");
    for (p, c, t) in ps.iter().take(8) {
        println!("    {c:>6}/{t:<6} {p}");
    }
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
