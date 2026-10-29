//! `.ani` 骨名对齐普查：名字表基址到底该是 0xF0 还是 0xD2，用全库数字说话。
//!
//! 背景：`.mesh` 尾部骨架的根骨实测叫 `000`（`geometry.rs` 的 BoneNode 注释），
//! 而 0xD2 起的名表第一条正是 `000`、第二条才是 `bip01`——若名表基址取 0xF0，
//! 每条轨道拿到的名字就整体晚一根骨（第 0 条被贴上第 1 根骨的名，最后一条读到名表外的垃圾变空串）。
//! MIN3 一侧另有闭式证据：标志区 = 0xD2 + 78×骨数，2522/2522 份正好收在文件尾。
//!
//! 只读：db、pak 全部只读打开，不落资源字节。
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example ani_names_census
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, rest_poses};

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

    let mut paks: HashMap<String, Pak> = HashMap::new();
    // tag -> (份数, 解出, 轨道条数, 有名轨道, rest 解出, 首条名=000, 末条名空)
    let mut stat: HashMap<String, (usize, usize, usize, usize, usize, usize, usize)> = HashMap::new();
    let mut roots: HashMap<String, usize> = HashMap::new();

    for (hash, pak_name) in &rows {
        if !paks.contains_key(pak_name) {
            if let Ok(p) = Pak::open(root.join(format!("{pak_name}.pak"))) {
                paks.insert(pak_name.clone(), p);
            }
        }
        let Some(p) = paks.get(pak_name) else { continue };
        let Some(rec) = p.records().find(|r| r.hash == *hash && r.stored > 0) else {
            continue;
        };
        let Ok(raw) = payload::decode(p, &rec) else { continue };
        let bytes = raw.bytes;
        let tag = bytes
            .get(0x8c..0x90)
            .map(|s| String::from_utf8_lossy(s).into_owned())
            .unwrap_or_else(|| "<短>".to_string());
        let Some(a) = parse_ani(&bytes) else { continue };
        let e = stat.entry(tag).or_default();
        e.0 += 1;
        e.2 += a.tracks.len();
        e.3 += a.tracks.iter().filter(|t| !t.bone.is_empty()).count();
        if rest_poses(&bytes).is_some() {
            e.4 += 1;
        }
        if let Some(t) = a.tracks.first() {
            if t.bone == "000" {
                e.5 += 1;
            }
            *roots.entry(t.bone.clone()).or_default() += 1;
        }
        if a.tracks.last().map(|t| t.bone.is_empty()).unwrap_or(false) {
            e.6 += 1;
        }
    }

    println!("按容器分族（份数 / 轨道条数 / 有名轨道 / rest 解出 / 首条名==000 / 末条名空）：");
    let mut keys: Vec<_> = stat.keys().cloned().collect();
    keys.sort();
    for k in keys {
        let e = stat[&k];
        println!(
            "  {k:6} 份={:5}  轨道={:8} 有名={:8}（{:.1}%）  rest={:5}  首条=000 的份={:5}  末条空名={:5}",
            e.0,
            e.2,
            e.3,
            if e.2 > 0 { 100.0 * e.3 as f64 / e.2 as f64 } else { 0.0 },
            e.4,
            e.5,
            e.6
        );
    }
    let mut rs: Vec<(String, usize)> = roots.into_iter().collect();
    rs.sort_by(|a, b| b.1.cmp(&a.1));
    println!(
        "首条轨道的名字分布（前 10）：{}",
        rs.iter()
            .take(10)
            .map(|(n, c)| format!("{n}×{c}"))
            .collect::<Vec<_>>()
            .join("  ")
    );
}
