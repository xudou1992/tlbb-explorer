//! `.ani` 容器版别普查：0x8C 的 MIN2/MIN3/… 各多少份，各自被 `parse_ani` 认下多少。
//!
//! 起因（2026-10-27）：动作页对变体宠物/部分 NPC 报「不按已知的 .ani 布局」。
//! 已发现 `0x8C` 是 **MIN2 与 MIN3** 两种容器（客户端装载器放行 MIN2/3/6/7、排除 MIN5），
//! 而我们的解析器只按 MIN2 的一套装法（骨架记录 60B / 32B 每帧）写。
//! 这份普查要回答的是：**分族有多少份**，别拿个别样本下全库结论。
//!
//! 只读：db、pak 全部只读打开，不落资源字节。
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --example ani_tag_census
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{ani_min3_summary, parse_ani, parse_ani_header};

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
    .expect("资源清单打不开");

    let mut rows: Vec<(u64, String)> = Vec::new();
    {
        let mut st = con
            .prepare("SELECT hash, coalesce(pak,'') FROM resources WHERE name LIKE '%.ani' AND coalesce(pak,'') <> ''")
            .unwrap();
        let it = st
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .unwrap();
        for row in it.flatten() {
            if let Ok(h) = u64::from_str_radix(&row.0, 16) {
                rows.push((h, row.1));
            }
        }
    }
    println!("清单里 .ani 条数：{}", rows.len());

    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut by_tag: HashMap<String, (usize, usize, usize)> = HashMap::new(); // tag -> (份数, parse_ani 认, header 认)
    let mut fails: Vec<String> = Vec::new();
    let mut min3_unequal = 0usize;
    // (骨数累计, 会动骨累计, 非单位累计, 份数, 最大帧间角累计)
    let mut min3_bad_struct = 0usize;
    let mut min3_bad_prefix = 0usize;
    let mut min3_bad_examples: Vec<String> = Vec::new();
    let mut min3_eq_metric = (0usize, 0usize, 0usize, 0usize, 0f32);
    let mut min3_ne_metric = (0usize, 0usize, 0usize, 0usize, 0f32);
    let mut min3_equal = 0usize;
    let mut bytes_fail = 0usize;

    for (hash, pak_name) in &rows {
        if !paks.contains_key(pak_name) {
            match Pak::open(root.join(format!("{pak_name}.pak"))) {
                Ok(p) => {
                    paks.insert(pak_name.clone(), p);
                }
                Err(_) => continue,
            }
        }
        let Some(p) = paks.get(pak_name) else { continue };
        let Some(rec) = p.records().find(|r| r.hash == *hash && r.stored > 0) else {
            continue;
        };
        let Ok(raw) = payload::decode(p, &rec) else {
            bytes_fail += 1;
            continue;
        };
        let bytes = raw.bytes;
        let tag = bytes
            .get(0x8c..0x90)
            .map(|s| String::from_utf8_lossy(s).into_owned())
            .unwrap_or_else(|| "<短>".to_string());
        let e = by_tag.entry(tag.clone()).or_insert((0, 0, 0));
        e.0 += 1;
        // MIN3 里两个计数不等的份有多少（骨↔标志的对应未证，现在只报结构）。
        if tag == "MIN3" {
            let u32_at = |o: usize| -> u32 {
                bytes.get(o..o + 4).map(|x| u32::from_le_bytes(x.try_into().unwrap())).unwrap_or(0)
            };
            let (c1, c2) = (u32_at(0xba), u32_at(0xbe));
            if c1 != c2 {
                min3_unequal += 1;
            } else {
                min3_equal += 1;
            }
        }
        // MIN3 解不出来的按原因分桶：结构不成立（扫不到唯一精确解）/ 结构成立但解析仍拒（计数前缀那条）。
        if tag == "MIN3" && parse_ani(&bytes).is_none() {
            if ani_min3_summary(&bytes).is_some() {
                min3_bad_prefix += 1;
            } else {
                min3_bad_struct += 1;
                if min3_bad_examples.len() < 5 {
                    let u32_at = |o: usize| -> u32 {
                        bytes.get(o..o + 4).map(|x| u32::from_le_bytes(x.try_into().unwrap())).unwrap_or(0)
                    };
                    min3_bad_examples.push(format!(
                        "{hash:016x} c1={} c2={} frames={} tag@0x8c={}",
                        u32_at(0xba),
                        u32_at(0xbe),
                        u32_at(0xc2),
                        String::from_utf8_lossy(&bytes[0x8c..0x90])
                    ));
                }
            }
        }
        if let Some(a) = parse_ani(&bytes) {
            e.1 += 1;
            if tag == "MIN3" {
                // 质量指标：会动骨比例、最大帧间角、非单位四元数——计数相等的族当基准。
                let mut moved = 0usize;
                let mut maxd = 0f32;
                let mut nonunit = 0usize;
                for tr in &a.tracks {
                    let mut mv = false;
                    let mut prev: Option<[f32; 4]> = None;
                    for q in &tr.rotations {
                        let n = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt();
                        if (n - 1.0).abs() > 1e-3 {
                            nonunit += 1;
                        }
                        if let Some(p) = prev {
                            let d = 2.0
                                * (q[0] * p[0] + q[1] * p[1] + q[2] * p[2] + q[3] * p[3])
                                    .abs()
                                    .clamp(-1.0, 1.0)
                                    .acos();
                            if d > 1e-3 {
                                mv = true;
                            }
                            maxd = maxd.max(d);
                        }
                        prev = Some(*q);
                    }
                    if mv {
                        moved += 1;
                    }
                }
                let u32_at = |o: usize| -> u32 {
                    bytes.get(o..o + 4).map(|x| u32::from_le_bytes(x.try_into().unwrap())).unwrap_or(0)
                };
                let (c1, c2) = (u32_at(0xba), u32_at(0xbe));
                let slot = if c1 == c2 { &mut min3_eq_metric } else { &mut min3_ne_metric };
                slot.0 += a.tracks.len();
                slot.1 += moved;
                slot.2 += nonunit;
                slot.3 += 1;
                slot.4 += maxd.min(3.0);
            }
        }
        if parse_ani_header(&bytes).is_some() {
            e.2 += 1;
        } else if fails.len() < 10 {
            fails.push(format!(
                "{hash:016x} tag={} len={}",
                bytes
                    .get(0x8c..0x90)
                    .map(|s| String::from_utf8_lossy(s).into_owned())
                    .unwrap_or_default(),
                bytes.len()
            ));
        }
    }

    println!("取字节失败：{bytes_fail}");
    println!("MIN3 里两个计数相等 {min3_equal} / 不等 {min3_unequal}");
    for e in &min3_bad_examples {
        println!("  例：{e}");
    }
    println!("MIN3 解不出 {} 份：结构不成立 {min3_bad_struct} · 结构成立但解析仍拒（计数前缀分支）{min3_bad_prefix}", min3_bad_struct + min3_bad_prefix);
    for (label, m) in [("计数相等", min3_eq_metric), ("计数不等", min3_ne_metric)] {
        if m.3 > 0 {
            println!(
                "  {label}：{} 份 · 骨 {}/{} 会动（{:.1}%）· 非单位四元数 {} · 平均最大帧间角 {:.3}",
                m.3,
                m.1,
                m.0,
                100.0 * m.1 as f32 / m.0.max(1) as f32,
                m.2,
                m.4 / m.3 as f32
            );
        }
    }
    println!("—— 按 0x8C 的容器标签分组（份数 / parse_ani 认下 / 头部认下）——");
    let mut tags: Vec<_> = by_tag.into_iter().collect();
    tags.sort_by_key(|(_, v)| std::cmp::Reverse(v.0));
    for (tag, (n, ok, hok)) in &tags {
        println!("  {tag}: {n} / {ok} / {hok}");
    }
    if !fails.is_empty() {
        println!("—— 头部都认不出的前 10 例 ——");
        for f in &fails {
            println!("  {f}");
        }
    }
}