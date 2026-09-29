//! uvfit_batch — 全库批量试贴评分器的命令行入口。
//!
//! 引擎本体在 `preview::uvfit_batch`（工作台后台跑的也是同一份），这里只做三件事：
//! 收参数、把进度事件打到终端、把最后的账面数字说出来。
//!
//! 只读纪律：db 只读、pak 只读、只写 --out 目录。
//!
//! 用法：
//! ```text
//! uvfit_batch --root D:/TLGL --db D:/TLGL/.scratch/resources.db \
//!             --out D:/TLGL/.scratch/uvfit_batch [--limit N] [--shards N] [--top N]
//!             [--force]
//! ```

use std::path::PathBuf;
use tlbb_core::preview::uvfit_batch::{self, Config};

fn main() {
    let mut root = PathBuf::from("D:/TLGL");
    let mut db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let mut out = PathBuf::from("D:/TLGL/.scratch/uvfit_batch");
    let mut limit = 0usize; // 0 = 全库
    let mut shards = 0usize; // 0 = 自动
    let mut top = 10usize;
    let mut force = false;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--root" => root = PathBuf::from(args.next().unwrap_or_default()),
            "--db" => db = PathBuf::from(args.next().unwrap_or_default()),
            "--out" => out = PathBuf::from(args.next().unwrap_or_default()),
            "--limit" => limit = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            "--shards" => shards = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            "--top" => top = args.next().and_then(|v| v.parse().ok()).unwrap_or(10),
            // 忽略已有 results 全量重算——评分口径升级后刷新落盘用。
            "--force" => force = true,
            other => eprintln!("未知参数 {other}"),
        }
    }
    let cfg = Config { root, db, out, limit, shards, top, force };
    // 终端上的进度口径与迁移前一致：池解码每 100 张一行、评分每 50 只一行带 ETA。
    // 池解码一次要发 1,650 条事件，全打出来就是刷屏——抽稀只抽进度，不抽账面。
    let progress = |v: serde_json::Value| {
        let phase = v["phase"].as_str().unwrap_or("");
        let done = v["done"].as_u64().unwrap_or(0) as usize;
        let total = v["total"].as_u64().unwrap_or(0) as usize;
        if phase == "pool" && done % 100 == 0 {
            eprintln!("  已解码 {done} / {total}");
        }
        if phase == "scored" && done % 50 == 0 {
            let el = v["elapsedSec"].as_f64().unwrap_or(0.0);
            let eta = el / done as f64 * (total - done) as f64;
            println!("进度 {done} / {total} · 已用 {el:.1}s · 预计剩余 {eta:.0}s");
        }
    };
    let stats = match uvfit_batch::run(&cfg, &progress) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("批量试贴失败：{e}");
            std::process::exit(2);
        }
    };
    println!(
        "完成：total {} · 有UV {} · 新评 {} · 沿用 {} · 候选 {} 行 · 池 {} 张 · 总用时 {:.1}s",
        stats.total,
        stats.with_uv,
        stats.scored,
        stats.reused,
        stats.candidates,
        stats.pool,
        stats.elapsed_sec
    );
    println!("manifest → {}", cfg.out.join("manifest.json").display());
}
