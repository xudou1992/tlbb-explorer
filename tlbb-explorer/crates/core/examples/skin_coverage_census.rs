//! 全库权重覆盖普查：每份 `.mesh` 有多少顶点**没被任何影响表盖住**。
//!
//! 没盖住的顶点在播放/导出里落到「挂根骨/恒等」兜底 ⇒ 骨头一动它们不跟，画面就是散开的碎片。
//! 这条普查用来回答：第七十九轮并入变体表之后，这个缺口还剩多少、集中在哪一档。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example skin_coverage_census [份数上限=150]
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{attach_bone_skin, parse_hierarchy, parse_mesh, parse_nodes};

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
    let args: Vec<String> = std::env::args().skip(1).collect();
    let detail = args.iter().find_map(|a| a.strip_prefix("--detail=")).map(|s| s.to_string());
    let limit: usize = args
        .iter()
        .find_map(|a| a.trim_start_matches('-').parse::<usize>().ok())
        .unwrap_or(150);
    let mut st = con
        .prepare("SELECT hash, coalesce(name,''), coalesce(pak,''), coalesce(stored,0) FROM resources WHERE ext='.mesh' AND coalesce(pak,'') <> '' ORDER BY hash")
        .unwrap();
    let rows = st
        .query_map([], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, i64>(3)?,
            ))
        })
        .unwrap()
        .flatten()
        .collect::<Vec<_>>();

    let mut paks: HashMap<String, Pak> = HashMap::new();
    let (mut done, mut zero, mut some, mut noverts) = (0usize, 0usize, 0usize, 0usize);
    let mut buckets = [0usize; 5]; // 0% · ~1% · 1~5% · 5~20% · >20%
    let mut worst: Vec<(f64, String, usize, usize)> = Vec::new();
    let (mut rigid, mut rigid_miss, mut def, mut def_v, mut def_miss) = (0usize, 0usize, 0usize, 0usize, 0usize);
    let (mut def_zero, mut def_bad) = (0usize, 0usize);
    let mut dbuckets = [0usize; 5];
    let mut tot_v = 0usize;
    let mut tot_miss = 0usize;
    for (hash, name, pak, stored) in rows {
        if done >= limit {
            break;
        }
        if stored <= 0 {
            continue;
        }
        let h = match u64::from_str_radix(&hash, 16) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if !paks.contains_key(&pak) {
            match Pak::open(root.join(format!("{pak}.pak"))) {
                Ok(p) => {
                    paks.insert(pak.clone(), p);
                }
                Err(_) => continue,
            }
        }
        let Some(p) = paks.get(&pak) else { continue };
        let Some(rec) = p.records().find(|r| r.hash == h && r.stored > 0) else { continue };
        let Ok(raw) = payload::decode(p, &rec).map(|d| d.bytes) else { continue };
        let Ok(layout) = parse_mesh(&raw) else { continue };
        let vc = layout.geometry.positions.len();
        if vc == 0 {
            noverts += 1;
            continue;
        }
        // 刚性件（骨架 ≤1 根骨）本来就不变形，未覆盖不算缺陷 ⇒ 分开统计。
        let bones = parse_hierarchy(&raw).map(|h| h.bones.len()).unwrap_or(0);
        let nodes = match parse_hierarchy(&raw) {
            Some(h) => attach_bone_skin(&h, &parse_nodes(&raw), &raw),
            None => parse_nodes(&raw),
        };
        let mut covered = vec![false; vc];
        for nd in &nodes {
            if let Some(sk) = &nd.skin {
                for &v in &sk.vertices {
                    let vi = v as usize;
                    if vi < vc {
                        covered[vi] = true;
                    }
                }
            }
        }
        let miss = covered.iter().filter(|c| !**c).count();
        let pct = miss as f64 * 100.0 / vc as f64;
        done += 1;
        if bones <= 1 {
            rigid += 1;
            rigid_miss += miss;
            continue;
        }
        def += 1;
        def_v += vc;
        def_miss += miss;
        if miss == 0 {
            def_zero += 1;
        } else if pct > 5.0 {
            def_bad += 1;
        }
        dbuckets[if miss == 0 {
            0
        } else if pct <= 1.0 {
            1
        } else if pct <= 5.0 {
            2
        } else if pct <= 20.0 {
            3
        } else {
            4
        }] += 1;
        tot_v += vc;
        tot_miss += miss;
        if miss == 0 {
            zero += 1;
        } else {
            some += 1;
        }
        buckets[if miss == 0 {
            0
        } else if pct <= 1.0 {
            1
        } else if pct <= 5.0 {
            2
        } else if pct <= 20.0 {
            3
        } else {
            4
        }] += 1;
        if worst.len() < 200 {
            worst.push((pct, name.clone(), miss, vc));
        }
        if let Some(pat) = &detail {
            if name.contains(pat.as_str()) {
                let mut runs: Vec<(usize, usize)> = Vec::new();
                let mut i = 0usize;
                while i < vc {
                    if !covered[i] {
                        let st = i;
                        while i < vc && !covered[i] {
                            i += 1;
                        }
                        runs.push((st, i - st));
                    } else {
                        i += 1;
                    }
                }
                runs.sort_by(|a, b| b.1.cmp(&a.1));
                println!(
                    "明细 {name}（{pak} / {hash}）骨 {bones} · 节点记录 {} 条（带表 {} 条）· 顶点 {vc} · 未覆盖 {miss} = {pct:.1}% · 分 {} 段，最长：{:?}",
                    nodes.len(),
                    nodes.iter().filter(|nd| nd.skin.is_some()).count(),
                    runs.len(),
                    runs.iter().take(6).collect::<Vec<_>>()
                );
            }
        }
    }
    worst.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap());
    println!(
        "量到 {done} 份（无顶点 {noverts}）· 未覆盖为 0 的 {zero} 份 · 仍有缺口的 {some} 份"
    );
    println!(
        "分档：0% {} · ≤1% {} · 1~5% {} · 5~20% {} · >20% {}",
        buckets[0], buckets[1], buckets[2], buckets[3], buckets[4]
    );
    println!(
        "合计顶点 {tot_v} · 未覆盖 {tot_miss} = {:.2}%",
        tot_miss as f64 * 100.0 / tot_v as f64
    );
    println!(
        "刚性件（骨架 ≤1 根骨）{rigid} 份：未覆盖 {rigid_miss} 个顶点（这类不该变形，不算缺陷）"
    );
    println!(
        "可变形网格 {def} 份：未覆盖 {def_miss}/{def_v} = {:.2}% · 完全覆盖 {def_zero} 份 · 缺口 >5% 的 {def_bad} 份",
        def_miss as f64 * 100.0 / def_v.max(1) as f64
    );
    println!(
        "可变形分档：0% {} · ≤1% {} · 1~5% {} · 5~20% {} · >20% {}",
        dbuckets[0], dbuckets[1], dbuckets[2], dbuckets[3], dbuckets[4]
    );
    println!("缺口最重的 10 份（含刚性，仅示意）：");
    for (pct, name, miss, vc) in worst.iter().take(10) {
        println!("  {pct:5.1}%  {miss:>6}/{vc:<6}  {name}");
    }
}
