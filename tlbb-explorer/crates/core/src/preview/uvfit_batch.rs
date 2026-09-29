//! 全库批量试贴评分引擎（v0.4.1）。
//!
//! 原来这是 `src/bin/uvfit_batch.rs` 一个命令行工具：能跑，但只有人在终端前才跑得。
//! 搬进库里是为了让工作台也能跑它——用户点开「贴图候选」时不该看到 🔴，
//! 也不该自己去敲命令。单 mesh 版 `uvfit` 的最大浪费是每跑一个 mesh 都重新解码
//! 整池 1,650 张贴图（实测 ~10s，大头在池解码），批量版的核心思路就一句：
//! **池解码一次、进程内复用**，之后每个 mesh 只做 UV 栅格化 + 方差评分（毫秒级）。
//!
//! 流程：
//! 1. 从 catalog 的 `refs` 取全部 `.mdl` 成员 mesh（按文件名去重），
//!    mesh 名 → hash 用与单 mesh 版完全相同的查询口径。
//! 2. 断点续跑分区：已有 `results/<stem>.json` 的跳过，剩下的才解码池。
//! 3. 池解码一次（RGBA32/BC3 先验池，256² 亮度驻留内存）+ pak 全集。
//! 4. 分片并行：每个 mesh 读 pak 解几何 → UV 栅格化 → 对整池评分 → Top-N。
//! 5. 每 mesh 落盘 `results/<stem>.json`（元数据级，**不带 PNG**，~7KB/个）；
//!    收尾写 `manifest.json`：每 mesh 一行 + 尾部统计块。
//!
//! 落盘 v2（追加式，v1 字段全部保留，新旧分级可对比）：
//! - results/*.json 每候选尾部追加 `factors` + `adjustedScore`
//!   （`Cand::summary_v2`；旧字段逐位不动）；
//! - manifest 行追加 `topAdjusted` 与 `gradedV2`（阈值沿用 v1 但按 adjustedScore 判）。
//! - 措辞原则：graded/gradedV2 都是「系统评分」档位，不是正确率——归属
//!   只有人工确认（🟢）才算数。
//!
//! 只读纪律：db 只读、pak 只读、只写 `out` 目录。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;

use crate::preview::uvfit::{
    build_mask, covered, decode_pool, mdl_mesh_names, mesh_hash, open_paks, query_pool, score_pool,
    PakSet, PoolTex, GRID,
};
use crate::preview::parse_geometry;

// ---- 分级阈值：初始阈值，未人工校准。 ----
// 同一组阈值用于两个口径：v1 按 topScore（旧方差比），v2 按 topAdjusted
// （托底修正后的聚合分）。v2 的分布整体左移（黑底爆炸值被托回 0..30 区间），
// 这组阈值**没有按 v2 重新校准**——先落数据再看要不要调。
// high 要同时过分数线和覆盖率线（覆盖率太低的「高分」多半是 UV 岛太小的假阳性）。
const HIGH_SCORE: f64 = 6.0;
const HIGH_COVER: f64 = 0.3;
const MID_SCORE: f64 = 3.0;
const LOW_SCORE: f64 = 1.2;

/// 一次批量评分的全部输入。`limit`/`shards` 为 0 时取默认（不限 / 自动并行度）。
#[derive(Clone, Debug)]
pub struct Config {
    pub root: PathBuf,
    pub db: PathBuf,
    pub out: PathBuf,
    pub limit: usize,
    pub shards: usize,
    pub top: usize,
    pub force: bool,
}

impl Config {
    /// 工作台用的默认值：客户端根 + 清单 + 根下 `.scratch/uvfit_batch`，
    /// 不限数量、自动并行、Top-10、增量续跑（已评过的不重算）。
    pub fn for_client(root: PathBuf, db: PathBuf) -> Self {
        let out = root.join(".scratch/uvfit_batch");
        Config { root, db, out, limit: 0, shards: 0, top: 10, force: false }
    }
}

/// 跑完之后的账面数字，给调用方出声用（前端要说「这次新评了 N 只」）。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Stats {
    pub total: usize,
    pub with_uv: usize,
    pub candidates: usize,
    /// 本次真正重算并落盘的 mesh 数（增量续跑到尾声时为 0）。
    pub scored: usize,
    /// 本次直接沿用已有结果文件的数量。
    pub reused: usize,
    pub pool: usize,
    pub elapsed_sec: f64,
}

/// 一个待评 mesh。hash 解析不出（悬空引用）也入队，按 unknown 落盘，
/// 保证断点续跑对全清单幂等（重跑时不会因为查不到 hash 而反复重试）。
#[derive(Clone)]
struct MeshJob {
    name: String,
    hash: Option<u64>,
}

/// manifest 的一行。coverage/topScore 用 Option：几何都拿不到时是 null，
/// 与「有几何但没 UV（coverage=0）」区分开。v2 字段排在 v1 字段之后落盘。
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
    /// 落盘的候选行数（Top-N 截断后的）。统计块的 candidates 求和用它，
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

fn results_dir(out: &Path) -> PathBuf {
    out.join("results")
}

fn stem_of(name: &str) -> String {
    Path::new(name).file_stem().unwrap_or_default().to_string_lossy().into_owned()
}

/// 一个数值的 manifest 写法：None → `null`，与「有值但是 0」分开。
fn num(v: Option<f64>, digits: usize) -> String {
    match v {
        Some(x) => format!("{x:.digits$}"),
        None => "null".into(),
    }
}

/// 还差多少只模型没评过：清单里的 mesh 减去 `out/results/<stem>.json` 已存在的。
///
/// 只做「文件名在不在」这一件事——不解池、不开 pak、不算分，所以每次打开详情
/// 都能问一遍。数不出清单（没有资源清单库）时回 None：那是「不知道」，不是
/// 「0 只」，前端不许据此说「都跑完了」。
pub fn pending(cfg: &Config) -> Option<usize> {
    let con = Connection::open_with_flags(
        &cfg.db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok()?;
    let dir = results_dir(&cfg.out);
    let mut n = 0usize;
    for name in mdl_mesh_names(&con) {
        if !dir.join(format!("{}.json", stem_of(&name))).is_file() {
            n += 1;
        }
    }
    Some(n)
}

/// 跑一批（或全库）批量试贴评分。
///
/// `progress` 收两类事件：池解码阶段 `{phase:"pool",done,total}`，评分阶段
/// `{phase:"scored",done,total,mesh}`，收尾 `{phase:"finished",total,scored,pool,elapsedSec}`。
/// 接到哪儿是调用者的事——命令行 println!，工作台 emit 事件，测试收进数组。
/// 闭包要 `+ Sync`：评分分片在别的线程上，进度从各分片汇报出来（同一把锁串行）。
pub fn run(cfg: &Config, progress: &(dyn Fn(serde_json::Value) + Sync)) -> Result<Stats, String> {
    let t0 = std::time::Instant::now();
    let con = Connection::open_with_flags(
        &cfg.db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| format!("资源清单打不开：{e}"))?;

    // ① 模型清单：.mdl 的成员 mesh，按文件名去重；mesh 名 → hash 沿用
    //    单 mesh 版的口径（path like '%/<name>' 取第一条）。
    let mut names = mdl_mesh_names(&con);
    if cfg.limit > 0 {
        names.truncate(cfg.limit);
    }
    let jobs: Vec<MeshJob> = names
        .into_iter()
        .map(|name| MeshJob { hash: mesh_hash(&con, &name), name })
        .collect();
    let shards = if cfg.shards > 0 {
        cfg.shards
    } else {
        // 默认并行度：留一点余量给系统，最多 16 路（再多内存带宽反而顶不住）。
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4)
            .clamp(4, 16)
    };

    // ② 断点续跑分区：结果文件已存在且能解析 → 跳过（force 时不跳，全量重算）。
    //    结果文件自带 hasUv 字段，重扫时不必重新解几何就能重建 manifest 行。
    let dir = results_dir(&cfg.out);
    std::fs::create_dir_all(&dir).map_err(|e| format!("建结果目录失败：{e}"))?;
    let mut todo: Vec<MeshJob> = Vec::new();
    let mut done_rows: HashMap<String, Row> = HashMap::new();
    for job in &jobs {
        if cfg.force {
            todo.push(job.clone());
            continue;
        }
        match std::fs::read_to_string(dir.join(format!("{}.json", stem_of(&job.name))))
            .ok()
            .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
        {
            Some(v) => {
                done_rows.insert(job.name.clone(), row_from_cache(&v, &job.name));
            }
            None => todo.push(job.clone()),
        }
    }
    let todo_total = todo.len();

    // ③④ 池解码 + 分片评分。只有真有待跑 mesh 时才开 pak、才解池——增量续跑到
    //    尾声（todo 为空）不该把 1,650 张贴图再解一遍。
    let mut pool_len = 0usize;
    if todo_total > 0 {
        let set = Arc::new(open_paks(&cfg.root));
        let rows = query_pool(&con, usize::MAX);
        pool_len = rows.len();
        let pool = Arc::new(decode_pool(&rows, &set.paks, &set.by_hash, &mut |done, total| {
            progress(serde_json::json!({ "phase": "pool", "done": done, "total": total }));
        }));
        let counter = Arc::new(AtomicUsize::new(0));
        let t_run = std::time::Instant::now();
        let per = todo_total.div_ceil(shards).max(1);
        let rows: Vec<Vec<Row>> = std::thread::scope(|scope| {
            let handles: Vec<_> = todo
                .chunks(per)
                .map(|chunk| {
                    let set = Arc::clone(&set);
                    let pool = Arc::clone(&pool);
                    let counter = Arc::clone(&counter);
                    let dir = &dir;
                    let progress = &progress;
                    scope.spawn(move || {
                        let mut rows = Vec::with_capacity(chunk.len());
                        for job in chunk {
                            rows.push(run_one(&set, &pool, job, pool_len, cfg.top, dir));
                            // done 用全局计数：并行度多少都不影响「已完成多少个」。
                            let done = counter.fetch_add(1, Ordering::Relaxed) + 1;
                            progress(serde_json::json!({
                                "phase": "scored",
                                "done": done,
                                "total": todo_total,
                                "mesh": job.name,
                                "elapsedSec": t_run.elapsed().as_secs_f64(),
                            }));
                        }
                        rows
                    })
                })
                .collect();
            handles.into_iter().map(|h| h.join().expect("评分分片崩溃")).collect()
        });
        for mut r in rows {
            done_rows.extend(r.drain(..).map(|row| (row.mesh.clone(), row)));
        }
    }
    // ⑤ manifest：按清单原序一行一个 mesh，尾部加统计块。
    let elapsed = t0.elapsed().as_secs_f64();
    write_manifest(&cfg.out, &jobs, &done_rows, elapsed)?;
    let scored = todo_total;
    progress(serde_json::json!({
        "phase": "finished",
        "total": jobs.len(),
        "scored": scored,
        "pool": pool_len,
        "elapsedSec": elapsed,
    }));

    Ok(Stats {
        total: jobs.len(),
        with_uv: done_rows.values().filter(|r| r.has_uv).count(),
        candidates: done_rows.values().map(|r| r.candidates).sum(),
        scored,
        reused: done_rows.len().saturating_sub(scored),
        pool: pool_len,
        elapsed_sec: elapsed,
    })
}

/// 分片里评一只 mesh 并落盘（错误也落盘，作为断点续跑的「已处理」标记）。
fn run_one(
    set: &PakSet,
    pool: &[PoolTex],
    job: &MeshJob,
    pool_len: usize,
    top: usize,
    results_dir: &Path,
) -> Row {
    let (row, json) = evaluate(set, pool, job, pool_len, top);
    std::fs::write(results_dir.join(format!("{}.json", stem_of(&job.name))), &json).ok();
    row
}

/// 单只 mesh 的完整评估：取字节 → 解几何 → 栅格化 → 对整池评分 → Top-N。
/// 任何一步失败都返回 hasUv=false 的行 + 带 error 字段的结果文件
/// （candidates/coverage 置空），不中断批量。
fn evaluate(
    set: &PakSet,
    pool: &[PoolTex],
    job: &MeshJob,
    pool_len: usize,
    top: usize,
) -> (Row, String) {
    let name = &job.name;
    let blank = |has_uv: bool, coverage: Option<f64>, error: &str| {
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
            "{{\"mesh\":\"{name}\",\"pool\":{pool_len},\"coverage\":{},\"hasUv\":{has_uv},\"candidates\":[],\"error\":\"{error}\"}}\n",
            num(coverage, 4)
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
        .fold(None, |acc: Option<f64>, v| Some(acc.map_or(v, |a| a.max(v))));
    let cands = shown
        .iter()
        // 候选行升级为 summary_v2：旧字段逐位在前，尾部追加 factors/adjustedScore。
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

/// 从已存在的结果文件重建 manifest 行（断点续跑用）。graded 按当前阈值重算——
/// 阈值调整后重跑一次，manifest 分级即全量刷新。
/// v2 字段：候选行里读 adjustedScore 取最大（v1 旧结果文件没有 adjustedScore
/// → topAdjusted=null → gradedV2 只能 unknown，须 force 重算）。
fn row_from_cache(v: &serde_json::Value, name: &str) -> Row {
    let has_uv = v["hasUv"].as_bool().unwrap_or(false);
    let coverage = v["coverage"].as_f64();
    let cands = v["candidates"].as_array().cloned().unwrap_or_default();
    let top_score = cands.first().and_then(|c| c["score"].as_f64());
    let top_adjusted = cands
        .iter()
        .filter_map(|c| c["adjustedScore"].as_f64())
        .fold(None, |acc: Option<f64>, v| Some(acc.map_or(v, |a| a.max(v))));
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

/// manifest：一行一个 mesh（按清单原序）+ 尾部统计块。
/// 两个口径的分级都统计：graded（v1，按 topScore）与 gradedV2（按 topAdjusted），
/// 字段都保留，可对比掉档情况。
fn write_manifest(
    out: &Path,
    jobs: &[MeshJob],
    rows: &HashMap<String, Row>,
    elapsed: f64,
) -> Result<(), String> {
    let mut graded = [("high", 0usize), ("mid", 0), ("low", 0), ("unknown", 0)];
    let mut graded_v2 = [("high", 0usize), ("mid", 0), ("low", 0), ("unknown", 0)];
    let mut with_uv = 0usize;
    let mut cand_total = 0usize;
    let mut manifest = String::new();
    for job in jobs {
        let Some(r) = rows.get(&job.name) else {
            return Err(format!("{} 没有结果行（不应发生）", job.name));
        };
        if r.has_uv {
            with_uv += 1;
        }
        cand_total += r.candidates;
        graded.iter_mut().find(|(g, _)| *g == r.graded).ok_or("未知分级")?.1 += 1;
        graded_v2.iter_mut().find(|(g, _)| *g == r.graded_v2).ok_or("未知分级")?.1 += 1;
        manifest.push_str(&format!(
            "{{\"mesh\":\"{}\",\"hasUv\":{},\"coverage\":{},\"topScore\":{},\"graded\":\"{}\",\"topAdjusted\":{},\"gradedV2\":\"{}\"}}\n",
            r.mesh,
            r.has_uv,
            num(r.coverage, 4),
            num(r.top_score, 3),
            r.graded,
            num(r.top_adjusted, 3),
            r.graded_v2,
        ));
    }
    manifest.push_str(&format!(
        "{{\"total\":{},\"withUv\":{},\"candidates\":{},\"graded\":{{\"high\":{},\"mid\":{},\"low\":{},\"unknown\":{}}},\"gradedV2\":{{\"high\":{},\"mid\":{},\"low\":{},\"unknown\":{}}},\"elapsedSec\":{elapsed:.1},\"thresholds\":{{\"highScore\":{HIGH_SCORE},\"highCoverage\":{HIGH_COVER},\"midScore\":{MID_SCORE},\"lowScore\":{LOW_SCORE}}}}}\n",
        jobs.len(),
        with_uv,
        cand_total,
        graded[0].1, graded[1].1, graded[2].1, graded[3].1,
        graded_v2[0].1, graded_v2[1].1, graded_v2[2].1, graded_v2[3].1,
    ));
    std::fs::create_dir_all(out).map_err(|e| format!("建输出目录失败：{e}"))?;
    std::fs::write(out.join("manifest.json"), manifest).map_err(|e| format!("写 manifest 失败：{e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 本机没有客户端 / 没有清单时跳过（与 browse 那几个用例同一降级口径）：
    /// 这条吃的是真 pak 字节，仓库不带素材，缺席不算失败。
    fn client_cfg(out: PathBuf) -> Option<Config> {
        let (root, db) = {
            let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
            let db = std::env::var("TLBB_DB").map(PathBuf::from).unwrap_or_else(|_| root.join(".scratch/resources.db"));
            (root, db)
        };
        if !root.join("data.pak").is_file() || !db.is_file() {
            return None;
        }
        Some(Config { root, db, out, limit: 3, shards: 1, top: 5, force: false })
    }

    /// 增量闭环：真跑 3 只 → 落盘 → 再跑一遍沿用 → force 重算。
    ///
    /// 标 ignore 的理由与 `data::warm_cache_e2e` 同一口径：它要解一整池
    /// 1,650 张匿名贴图，debug  profile 下一轮就是几分钟，不该拖慢日常
    /// `cargo test`。验证时手动跑：
    ///   cargo test --lib uvfit_batch -- --ignored
    #[test]
    #[ignore = "要解码全池匿名贴图，一轮约 7 分钟，手动验证批量闭环时跑"]
    fn 增量跑完后再跑一遍不重算且manifest齐全() {
        let out = std::env::temp_dir().join(format!("tlbb_uvfit_batch_{}", std::process::id()));
        std::fs::remove_dir_all(&out).ok();
        let Some(cfg) = client_cfg(out) else {
            eprintln!("跳过：本机没有客户端 pak 或资源清单");
            return;
        };
        let before = pending(&cfg).expect("有清单就该数得出还差多少只");
        assert!(before > 0, "全库清单里应有没评过的模型（limit=3 也至少 3 只）");

        // 进度闭包要求 Fn + Sync（分片线程也在汇报），收集器就得是一把锁。
        let events: std::sync::Mutex<Vec<serde_json::Value>> = std::sync::Mutex::new(Vec::new());
        let stats = run(&cfg, &|v| events.lock().unwrap().push(v.clone())).expect("批量评分应跑通");
        assert_eq!(stats.total, 3, "limit=3 就评 3 只");
        assert_eq!(stats.scored, 3, "首次跑：三只都该是新评的");
        assert_eq!(stats.reused, 0);
        assert!(stats.pool > 0, "候选池不该是空的");
        // 进度事件：收尾必发一条 finished，done 恒等于 total——进度条靠这两条收。
        let events = events.lock().unwrap();
        let finished = events.iter().rev().find(|e| e["phase"] == "finished").expect("收尾应有 finished 事件");
        assert_eq!(finished["total"], 3);
        assert_eq!(finished["scored"], 3);
        assert!(events.iter().any(|e| e["phase"] == "scored"), "每评一只都要出声");
        drop(events);

        // 落盘：三只各有一份结果文件 + 一份 manifest。
        let dir = results_dir(&cfg.out);
        let files = std::fs::read_dir(&dir).expect("结果目录应存在").count();
        assert_eq!(files, 3, "每只 mesh 一份结果文件");
        let manifest = std::fs::read_to_string(cfg.out.join("manifest.json")).expect("manifest 应写出来");
        let last: serde_json::Value = serde_json::from_str(
            manifest.lines().last().expect("manifest 不该是空的"),
        )
        .expect("统计块应是合法 JSON");
        assert_eq!(last["total"], 3);

        // 再跑一遍：三只都沿用已有结果，不再解池（todo 为空时连 pak 都不开）。
        let stats2 = run(&cfg, &|_| {}).expect("第二次跑应成功");
        assert_eq!(stats2.scored, 0, "已有结果必须跳过，不重算");
        assert_eq!(stats2.reused, 3);
        assert_eq!(pending(&cfg).unwrap_or(before), before - 3, "pending 应恰好减掉这三只");

        // force：忽略已有结果全量重算。
        let forced = Config { force: true, ..cfg.clone() };
        let stats3 = run(&forced, &|_| {}).expect("force 重算应成功");
        assert_eq!(stats3.scored, 3, "force 时要重算全部");
        std::fs::remove_dir_all(&forced.out).ok();
    }

    #[test]
    fn 分级阈值按两个口径各算一次() {
        // high 要同时过分数线和覆盖率线：光有高分但 UV 岛太小不算 high。
        assert_eq!(grade(Some(7.0), 0.5, true), "high");
        assert_eq!(grade(Some(7.0), 0.1, true), "mid", "覆盖率不够不许给 high");
        assert_eq!(grade(Some(3.5), 0.0, true), "mid");
        assert_eq!(grade(Some(1.5), 0.0, true), "low");
        assert_eq!(grade(Some(0.2), 0.0, true), "unknown");
        assert_eq!(grade(None, 0.0, false), "unknown", "几何都拿不到也是 unknown");
    }

    /// 「没量过」和「量到 0」在 manifest 里必须是两样东西：null 与 0.0000。
    #[test]
    fn 缺值是_null_不是零() {
        assert_eq!(num(None, 4), "null");
        assert_eq!(num(Some(0.0), 4), "0.0000");
        assert_eq!(num(Some(1.23456), 3), "1.235");
    }

    /// 旧 v1 结果文件没有 adjustedScore：重扫出来 topAdjusted 是 null、
    /// gradedV2 只能 unknown——不许拿 v1 的方差分冒充综合分。
    #[test]
    fn 旧缓存重扫不谎报v2口径() {
        let v: serde_json::Value = serde_json::from_str(
            r#"{"mesh":"a.mesh","pool":1650,"coverage":0.4100,"hasUv":true,
               "candidates":[{"hash":"aa","score":8.5}]}"#,
        )
        .unwrap();
        let row = row_from_cache(&v, "a.mesh");
        assert_eq!(row.top_score, Some(8.5));
        assert_eq!(row.graded, "high", "v1 口径照旧");
        assert_eq!(row.top_adjusted, None, "没有 adjustedScore 就是没量过");
        assert_eq!(row.graded_v2, "unknown");
        assert_eq!(row.candidates, 1);
    }
}
