//! uvfit_batch — 全库批量试贴评分器（贴图恢复系统 v0.4.0；v0.4.1 起落盘 v2）。
//!
//! 单 mesh 版 `uvfit` 的最大浪费：每跑一个 mesh 都重新从 pak 解码整池
//! 1,650 张贴图（实测 ~10s，大头在池解码）。批量版的核心思路就一句：
//! **池解码一次、进程内复用**——之后每个 mesh 只做 UV 栅格化 + 方差评分
//! （毫秒级），全库几分钟跑完。
//!
//! 流程：
//! 1. 从 catalog 的 `refs` 取全部 `.mdl` 成员 mesh（按文件名去重），
//!    mesh 名 → hash 用与单 mesh 版完全相同的查询口径。
//! 2. 池解码一次（RGBA32/BC3 先验池，256² 亮度驻留内存）。
//! 3. 分片并行：每个 mesh 读 pak 解几何 → UV 栅格化 → 对整池评分 → Top-N。
//! 4. 每 mesh 落盘 `results/<stem>.json`（元数据级，**不带 PNG**，~7KB/个）；
//!    已存在即跳过——中断后重跑自动续（幂等）。`--force` 忽略已有结果
//!    全量重算（改评分口径后刷新落盘用）。
//! 5. 收尾写 `manifest.json`：每 mesh 一行 + 尾部统计块。
//!
//! v0.4.1 落盘 v2（追加式，v1 字段全部保留，新旧分级可对比）：
//! - results/*.json 每候选尾部追加 `factors` + `adjustedScore`
//!   （`Cand::summary_v2`；旧字段逐位不动）；
//! - manifest 行追加 `topAdjusted`（top-N 内 adjustedScore 的最大值）与
//!   `gradedV2`（阈值沿用 v1 但按 adjustedScore 判）；
//! - 措辞原则：graded/gradedV2 都是「系统评分」档位，不是正确率——归属
//!   只有人工确认（🟢）才算数。
//!
//! 只读纪律：db 只读、pak 只读、只写 --out 目录。
//!
//! 用法：
//! ```text
//! uvfit_batch --root D:/TLGL --db D:/TLGL/.scratch/resources.db \
//!             --out D:/TLGL/.scratch/uvfit_batch [--limit N] [--shards N] [--top N]
//!             [--force]
//! ```

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use rusqlite::OpenFlags;
use tlbb_core::preview::uvfit::{
    build_mask, covered, decode_pool, mdl_mesh_names, mesh_hash, open_paks, query_pool, score_pool,
    PakSet, PoolTex, GRID,
};
use tlbb_core::preview::parse_geometry;

// ---- 分级阈值：初始阈值，未人工校准。 ----
// v0.4.1 起同一组阈值用于两个口径：v1 按 topScore（旧方差比），v2 按
// topAdjusted（托底修正后的聚合分）。v2 的分布整体左移（黑底爆炸值被
// 托回 0..30 区间），这组阈值**没有按 v2 重新校准**——先落数据再看要不要调。
// high 要同时过分数线和覆盖率线（覆盖率太低的「高分」多半是 UV 岛太小的假阳性）。
const HIGH_SCORE: f64 = 6.0;
const HIGH_COVER: f64 = 0.3;
const MID_SCORE: f64 = 3.0;
const LOW_SCORE: f64 = 1.2;

/// 一个待评 mesh。hash 解析不出（悬空引用）也入队，按 unknown 落盘，
/// 保证断点续跑对全清单幂等（重跑时不会因为查不到 hash 而反复重试）。
#[derive(Clone)]
struct MeshJob {
    name: String,
    hash: Option<u64>,
}

/// manifest 的一行。coverage/topScore 用 Option：几何都拿不到时是 null，
/// 与「有几何但没 UV（coverage=0）」区分开。v0.4.1 追加 topAdjusted/gradedV2
/// （v2 口径，落盘时排在 v1 字段之后，旧字段不动）。
#[derive(Clone)]
struct Row {
    mesh: String,
    has_uv: bool,
    coverage: Option<f64>,
    top_score: Option<f64>,
    graded: &'static str,
    /// v2 口径：top-N 内 adjustedScore 的最大值（与结果文件里的候选集合
    /// 同口径，断点续跑重扫文件时能重建出同一行）。
    top_adjusted: Option<f64>,
    graded_v2: &'static str,
    /// 落盘的候选行数（Top-N 截断后的）。统计块里的 candidates 求和用它，
    /// 这样中断续跑后重扫结果文件也能得到同一口径的统计。
    candidates: usize,
}

/// 分级。无 UV / 无候选 / 分数不达标 → unknown。
fn grade(top_score: Option<f64>, coverage: f64, _has_uv: bool) -> &'static str {
    let Some(s) = top_score else { return "unknown" };
    if s >= HIGH_SCORE && coverage >= HIGH_COVER {
        "high"
    } else if s >= MID_SCORE {
        "mid"
    } else if s >= LOW_SCORE {
        "low"
    } else {
        "unknown"
    }
}

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
    let shards = if shards > 0 {
        shards
    } else {
        // 默认并行度：留一点余量给系统，最多 16 路（再多内存带宽反而顶不住）。
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4)
            .clamp(4, 16)
    };

    let t0 = std::time::Instant::now();
    let con = rusqlite::Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("db 打不开");

    // ① 模型清单：.mdl 的成员 mesh，按文件名去重；mesh 名 → hash 沿用
    //    单 mesh 版的口径（path like '%/<name>' 取第一条）。
    let mut names = mdl_mesh_names(&con);
    if limit > 0 {
        names.truncate(limit);
    }
    let jobs: Vec<MeshJob> = names
        .into_iter()
        .map(|name| MeshJob {
            hash: mesh_hash(&con, &name),
            name,
        })
        .collect();
    let dangling = jobs.iter().filter(|j| j.hash.is_none()).count();
    println!(
        "模型清单 {} 个 mesh（.mdl 成员去重；{} 个解析不到 hash，按 unknown 处理）",
        jobs.len(),
        dangling
    );

    // ② pak 全集 + 池解码一次。池以 Arc 共享给所有分片：PoolTex 建好后
    //    就是纯只读的（Pak 本身是 mmap，payload::decode 是纯函数）。
    let set = Arc::new(open_paks(&root));
    println!("打开 {} 个 pak，索引 {} 条", set.paks.len(), set.by_hash.len());
    let pool_rows = query_pool(&con, usize::MAX);
    println!("候选池 {} 张（先验：≥512² RGBA32/BC3 mips≥4）", pool_rows.len());
    let t_pool = std::time::Instant::now();
    let pool = Arc::new(decode_pool(&pool_rows, &set.paks, &set.by_hash, &mut |done, total| {
        eprintln!("  已解码 {} / {}", done, total);
    }));
    println!(
        "池解码完成 {} 张（SQL 行 {}），用时 {:.1}s",
        pool.len(),
        pool_rows.len(),
        t_pool.elapsed().as_secs_f64()
    );
    let pool_len = pool_rows.len();

    // ③ 断点续跑分区：results/<stem>.json 已存在且能解析 → 跳过（--force
    //    时不跳，全量重算）。结果文件自带 hasUv 字段，重扫时不必重新解几何
    //    就能重建 manifest 行。
    let results_dir = out.join("results");
    std::fs::create_dir_all(&results_dir).ok();
    let mut todo: Vec<MeshJob> = Vec::new();
    let mut done_rows = std::collections::HashMap::new();
    for job in &jobs {
        let stem = Path::new(&job.name)
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned();
        if force {
            todo.push(job.clone());
            continue;
        }
        match std::fs::read_to_string(results_dir.join(format!("{stem}.json")))
            .ok()
            .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        {
            Some(v) => {
                done_rows.insert(job.name.clone(), row_from_cache(&v, &job.name));
            }
            None => todo.push(job.clone()),
        }
    }
    if force {
        println!("--force：忽略已有结果，全量重算 {} 个", todo.len());
    } else if !done_rows.is_empty() {
        println!(
            "断点续跑：{} 个已有结果跳过，{} 个待跑",
            done_rows.len(),
            todo.len()
        );
    }

    // ④ 分片并行。每个分片独立处理自己的 mesh（几何解析互不依赖），
    //    结果文件按 mesh 名命名，天然无写冲突。
    let todo_total = todo.len();
    let scored_count = Arc::new(AtomicUsize::new(0));
    let t_run = std::time::Instant::now();
    let mut fresh: Vec<Row> = Vec::new();
    if todo_total > 0 {
        let per = todo_total.div_ceil(shards).max(1);
        let rows: Vec<Vec<Row>> = std::thread::scope(|scope| {
            let handles: Vec<_> = todo
                .chunks(per)
                .map(|chunk| {
                    let set = Arc::clone(&set);
                    let pool = Arc::clone(&pool);
                    let counter = Arc::clone(&scored_count);
                    let results_dir = &results_dir;
                    scope.spawn(move || {
                        let mut rows = Vec::with_capacity(chunk.len());
                        for job in chunk {
                            rows.push(run_one(&set, &pool, job, pool_len, top, results_dir));
                            let done = counter.fetch_add(1, Ordering::Relaxed) + 1;
                            if done % 50 == 0 {
                                let el = t_run.elapsed().as_secs_f64();
                                let eta = el / done as f64 * (todo_total - done) as f64;
                                println!(
                                    "进度 {done} / {todo_total} · 已用 {el:.1}s · 预计剩余 {eta:.0}s"
                                );
                            }
                        }
                        rows
                    })
                })
                .collect();
            handles
                .into_iter()
                .map(|h| h.join().expect("评分分片崩溃"))
                .collect()
        });
        for mut r in rows {
            fresh.append(&mut r);
        }
    }
    for r in fresh {
        done_rows.insert(r.mesh.clone(), r);
    }

    // ⑤ manifest：按清单原序一行一个 mesh，尾部加统计块。
    //    v0.4.1 起同时统计两个口径：graded（v1，按 topScore）与 gradedV2
    //    （按 topAdjusted）——两者字段都保留，可对比掉档情况。
    let mut graded = [("high", 0usize), ("mid", 0), ("low", 0), ("unknown", 0)];
    let mut graded_v2 = [("high", 0usize), ("mid", 0), ("low", 0), ("unknown", 0)];
    let mut with_uv = 0usize;
    let mut cand_total = 0usize;
    let mut manifest = String::new();
    for job in &jobs {
        let Some(r) = done_rows.get(&job.name) else {
            eprintln!("警告：{} 没有结果行（不应发生）", job.name);
            continue;
        };
        if r.has_uv {
            with_uv += 1;
        }
        cand_total += r.candidates;
        graded
            .iter_mut()
            .find(|(g, _)| *g == r.graded)
            .expect("未知分级")
            .1 += 1;
        graded_v2
            .iter_mut()
            .find(|(g, _)| *g == r.graded_v2)
            .expect("未知分级")
            .1 += 1;
        let cov = match r.coverage {
            Some(c) => format!("{c:.4}"),
            None => "null".into(),
        };
        let ts = match r.top_score {
            Some(s) => format!("{s:.3}"),
            None => "null".into(),
        };
        let ta = match r.top_adjusted {
            Some(s) => format!("{s:.3}"),
            None => "null".into(),
        };
        manifest.push_str(&format!(
            "{{\"mesh\":\"{}\",\"hasUv\":{},\"coverage\":{cov},\"topScore\":{ts},\"graded\":\"{}\",\"topAdjusted\":{ta},\"gradedV2\":\"{}\"}}\n",
            r.mesh, r.has_uv, r.graded, r.graded_v2
        ));
    }
    let elapsed = t0.elapsed().as_secs_f64();
    manifest.push_str(&format!(
        "{{\"total\":{},\"withUv\":{},\"candidates\":{},\"graded\":{{\"high\":{},\"mid\":{},\"low\":{},\"unknown\":{}}},\"gradedV2\":{{\"high\":{},\"mid\":{},\"low\":{},\"unknown\":{}}},\"elapsedSec\":{elapsed:.1},\"thresholds\":{{\"highScore\":{HIGH_SCORE},\"highCoverage\":{HIGH_COVER},\"midScore\":{MID_SCORE},\"lowScore\":{LOW_SCORE}}}}}\n",
        jobs.len(),
        with_uv,
        cand_total,
        graded[0].1,
        graded[1].1,
        graded[2].1,
        graded[3].1,
        graded_v2[0].1,
        graded_v2[1].1,
        graded_v2[2].1,
        graded_v2[3].1,
    ));
    std::fs::create_dir_all(&out).ok();
    std::fs::write(out.join("manifest.json"), manifest).ok();
    println!(
        "完成：total {} · 有UV {} · 候选 {} 行 · v1分级 high/mid/low/unknown = {}/{}/{}/{} · v2分级 = {}/{}/{}/{} · 总用时 {:.1}s",
        jobs.len(),
        with_uv,
        cand_total,
        graded[0].1,
        graded[1].1,
        graded[2].1,
        graded[3].1,
        graded_v2[0].1,
        graded_v2[1].1,
        graded_v2[2].1,
        graded_v2[3].1,
        elapsed
    );
    println!("manifest → {}", out.join("manifest.json").display());
}

/// 评一个 mesh 并落盘结果文件（错误也落盘，作为断点续跑的「已处理」标记）。
/// 返回 manifest 行。
fn run_one(
    set: &PakSet,
    pool: &[PoolTex],
    job: &MeshJob,
    pool_len: usize,
    top: usize,
    results_dir: &Path,
) -> Row {
    let (row, json) = evaluate(set, pool, job, pool_len, top);
    let stem = Path::new(&job.name)
        .file_stem()
        .unwrap_or_default()
        .to_string_lossy()
        .into_owned();
    std::fs::write(results_dir.join(format!("{stem}.json")), &json).ok();
    row
}

/// 单个 mesh 的完整评估：取字节 → 解几何 → 栅格化 → 对整池评分 → Top-N。
/// 任何一步失败都返回 hasUv=false 的行 + 带 error 字段的结果文件
/// （candidates/coverage 置空），不中断批量。
fn evaluate(set: &PakSet, pool: &[PoolTex], job: &MeshJob, pool_len: usize, top: usize) -> (Row, String) {
    let name = &job.name;
    let blank = |has_uv: bool, coverage: Option<f64>, error: &str| {
        let cov = match coverage {
            Some(c) => format!("{c:.4}"),
            None => "null".into(),
        };
        let row = Row {
            mesh: name.clone(),
            has_uv,
            coverage,
            top_score: None,
            graded: grade(None, coverage.unwrap_or(0.0), has_uv),
            top_adjusted: None,
            graded_v2: grade(None, coverage.unwrap_or(0.0), has_uv),
            candidates: 0,
        };
        let json = format!(
            "{{\"mesh\":\"{name}\",\"pool\":{pool_len},\"coverage\":{cov},\"hasUv\":{has_uv},\"candidates\":[],\"error\":\"{error}\"}}\n"
        );
        (row, json)
    };
    let Some(hash) = job.hash else {
        return blank(false, None, "清单里解析不到 hash");
    };
    let Some(bytes) = set.fetch(hash) else {
        return blank(false, None, "pak 里取不到字节");
    };
    let Ok(geo) = parse_geometry(&bytes) else {
        return blank(false, None, "几何解析失败");
    };
    if geo.uvs.is_empty() {
        // 有几何、无 UV：覆盖率如实报 0，不当作错误。
        return blank(false, Some(0.0), "无 UV");
    }
    let (mask, _) = build_mask(&geo.uvs, &geo.indices);
    let coverage = covered(&mask) as f64 / (GRID * GRID) as f64;
    let scored = score_pool(&mask, pool);
    let top_score = scored.first().map(|c| c.score);
    let shown = &scored[..scored.len().min(top)];
    // v2 口径的 top：top-N（与落盘候选同一集合）里 adjustedScore 的最大值。
    // 旧 score 的排序口径不动，adjusted 只作另一个观察视角。
    let top_adjusted = shown
        .iter()
        .map(|c| c.adjusted_score)
        .fold(None, |acc: Option<f64>, v| {
            Some(acc.map_or(v, |a| a.max(v)))
        });
    let cands = shown
        .iter()
        // v0.4.1：候选行升级为 summary_v2（旧字段逐位在前，尾部追加
        // factors/adjustedScore）。
        .map(|c| c.summary_v2())
        .collect::<Vec<_>>()
        .join(",");
    let json = format!(
        "{{\"mesh\":\"{name}\",\"pool\":{pool_len},\"coverage\":{coverage:.4},\"hasUv\":true,\"candidates\":[{cands}]}}\n"
    );
    let row = Row {
        mesh: name.clone(),
        has_uv: true,
        coverage: Some(coverage),
        top_score,
        graded: grade(top_score, coverage, true),
        top_adjusted,
        graded_v2: grade(top_adjusted, coverage, true),
        candidates: shown.len(),
    };
    (row, json)
}

/// 从已存在的结果文件重建 manifest 行（断点续跑用）。graded 按当前
/// 阈值重算——阈值调整后重跑一次，manifest 分级即全量刷新。
/// v2 字段：候选行里读 adjustedScore 取最大（v0.4.0 的旧结果文件没有
/// adjustedScore → topAdjusted=null → gradedV2 只能 unknown，须 --force 重算）。
fn row_from_cache(v: &serde_json::Value, name: &str) -> Row {
    let has_uv = v["hasUv"].as_bool().unwrap_or(false);
    let coverage = v["coverage"].as_f64();
    let cands = v["candidates"].as_array().cloned().unwrap_or_default();
    let top_score = cands.first().and_then(|c| c["score"].as_f64());
    let top_adjusted = cands
        .iter()
        .filter_map(|c| c["adjustedScore"].as_f64())
        .fold(None, |acc: Option<f64>, v| {
            Some(acc.map_or(v, |a| a.max(v)))
        });
    Row {
        mesh: name.to_string(),
        has_uv,
        coverage,
        top_score,
        graded: grade(top_score, coverage.unwrap_or(0.0), has_uv),
        top_adjusted,
        graded_v2: grade(top_adjusted, coverage.unwrap_or(0.0), has_uv),
        candidates: cands.len(),
    }
}
