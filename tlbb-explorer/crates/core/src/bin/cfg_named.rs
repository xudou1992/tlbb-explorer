//! cfg 路径 × 包内条目 的对账普查（只读，除非给 `--out` 写 sidecar）。
//!
//! 为什么要再量一次：`ResourcePath.cfg` 有 72,764 对「裸名→原始全路径」，而引擎的 pak 索引
//! 哈希就是 `path_hash(全路径)`（函数本身对库里有路径的行验准 4,000/4,000）。
//! 所以把每条 cfg 路径代进哈希，就能知道**哪些包内条目其实查得到路径**：
//!   · 命中的行 `path` 已有值 —— 库里已经叫对了名字；
//!   · 命中的行 `path is null` —— 条目在包里、路径也知道，但清单没记上（这批就是可以白捡身份的）；
//!   · 没命中 —— 源文件打包时被剥离，包里根本没有那件（不是解析漏）。
//! 2026-09-26 记的是「42,083 有名 + 4,780 匿名 + 25,901 缺」，这一枪把它按**类型**拆开重测，
//! 顺便看看匿名那批里有没有贴图（贴图归属是另一条已判死的路，别拿这个数当它的希望）。

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::crypto::path_hash;
use tlbb_core::pathmap::PathMap;

struct Args {
    root: PathBuf,
    db: PathBuf,
    out: Option<PathBuf>,
}

fn parse_args() -> Args {
    let mut root = PathBuf::from("D:/TLGL");
    let mut db = root.join(".scratch/resources.db");
    let mut out = None;
    for a in std::env::args().skip(1) {
        if let Some(v) = a.strip_prefix("--root=") {
            root = PathBuf::from(v);
        } else if let Some(v) = a.strip_prefix("--db=") {
            db = PathBuf::from(v);
        } else if let Some(v) = a.strip_prefix("--out=") {
            out = Some(PathBuf::from(v));
        } else {
            eprintln!("不认识的参数：{a}（可用：--root= --db= --out=）");
            std::process::exit(2);
        }
    }
    Args { root, db, out }
}

fn main() {
    let Args { root, db, out } = parse_args();
    println!("== cfg 路径 × 包内条目 对账（只读）");
    println!("  root = {root:?}\n  db   = {db:?}");

    let pm = match PathMap::load(&root) {
        Some(p) => p,
        None => {
            println!("× ResourcePath.cfg 读不出来（客户端不在或格式变了），不猜，直接退出");
            std::process::exit(1);
        }
    };
    println!("  cfg 映射对：{}", pm.pair_count());

    let con = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("只读打开资源清单失败");
    // hash(u64) -> (type, 有没有路径)
    let mut rows: HashMap<u64, (String, bool)> = HashMap::new();
    {
        let mut st = con
            .prepare("select hash, type, path from resources")
            .expect("查询准备失败");
        let it = st
            .query_map([], |r| {
                let h: String = r.get(0)?;
                let t: Option<String> = r.get(1)?;
                let p: Option<String> = r.get(2)?;
                Ok((h, t.unwrap_or_else(|| "（没类型）".into()), p.is_some()))
            })
            .expect("查询失败");
        for row in it.flatten() {
            if let Ok(num) = u64::from_str_radix(row.0.trim().trim_start_matches("0x"), 16) {
                rows.insert(num, (row.1, row.2));
            }
        }
    }
    println!("  清单条目：{}", rows.len());

    let mut named = 0usize; // 命中且库里本来就有路径
    let mut missing = 0usize; // 包里没这件
    let mut anon: BTreeMap<String, usize> = BTreeMap::new(); // 命中但 path 为空，按类型
    let mut anon_rows: HashMap<String, String> = HashMap::new();
    let mut disagree = 0usize; // 命中的行有路径，但与 cfg 给的不是同一条（大小写以外不同）
    let mut by_hash_seen: HashMap<u64, String> = HashMap::new();

    for (_bare, path) in pm.iter() {
        let h = path_hash(path);
        match rows.get(&h) {
            None => missing += 1,
            Some((_t, true)) => {
                named += 1;
                if let Some(prev) = by_hash_seen.insert(h, path.clone()) {
                    if !prev.eq_ignore_ascii_case(path) {
                        disagree += 1;
                    }
                }
            }
            Some((t, false)) => {
                *anon.entry(t.clone()).or_default() += 1;
                anon_rows.insert(format!("{h:016x}"), path.clone());
            }
        }
    }

    let anon_total: usize = anon.values().sum();
    println!("\n对账结果（cfg 映射逐条代 path_hash）");
    println!("  库里已有路径的行命中：{named}");
    println!("  包里没这件（源被剥离）：{missing}");
    println!("  命中但清单没记路径（白捡身份）：**{anon_total}**");
    println!("  同一哈希被两条不同 cfg 路径命中：{disagree}（该是 0，不是 0 就说明哈希不够唯一）");
    println!("\n白捡那 {anon_total} 条按类型：");
    let mut sorted: Vec<_> = anon.iter().collect();
    sorted.sort_by_key(|(_k, v)| std::cmp::Reverse(**v));
    for (t, v) in sorted.iter().take(14) {
        println!("  {t:<18} {v:>6}");
    }
    if sorted.len() > 14 {
        println!("  …另有 {} 类", sorted.len() - 14);
    }
    let tex = anon.get("texture").copied().unwrap_or(0);
    println!(
        "\n贴图那一格：{tex} 条。{} 别把它当成贴图归属有救了——匿名贴图池 24,261 条里 path 全空，\n  而贴图名的六条桥已证伪（见 .scratch/tex_归属证据缺失_20261010.md），这里能拿到的只是**少数几张确有路径登记的大图**。",
        if tex == 0 { "一条都没有。" } else { "" }
    );

    if let Some(o) = out {
        let mut lines = String::from("{\n");
        let mut keys: Vec<_> = anon_rows.keys().cloned().collect();
        keys.sort();
        for (i, k) in keys.iter().enumerate() {
            lines.push_str(&format!("  {:?}: {:?}", k, anon_rows[k]));
            lines.push_str(if i + 1 == keys.len() { "\n" } else { ",\n" });
        }
        lines.push_str("}\n");
        if let Some(dir) = o.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        std::fs::write(&o, lines).expect("写 sidecar 失败");
        println!("\nsidecar：{o:?}（{} 条 hash→cfg 路径）", anon_rows.len());
    } else {
        println!("\n没给 --out=，这次只在屏幕上数数，不落盘。");
    }
}
