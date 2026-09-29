//! 贴图恢复系统 v1 · 步骤③⑤的数据层：候选榜单（uvfit 离线产出）+ 人工覆盖表。
//!
//! 纪律：原资源一个字节不动。覆盖表写在 `<root>/.scratch/model_texture_override.json`，
//! key 用 `cfg:<原始路径>`（90.8% 有）或 `bare:<裸名>`（其余），value 带确认的贴图 hash
//! 与时间——可撤销、可重评。候选全部是 🟡：uvfit 的分数是特征指标，不是归属结论；
//! 只有覆盖表里的才算 🟢。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use serde_json::json;
use tlbb_core::jpak::Pak;
use tlbb_core::preview::{png_bytes, scale_rgba};
use tlbb_core::{jmt1, payload};

/// 一个悬空贴图槽：原名、cfg 出处、人工确认状态。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct TexSlotInfo {
    pub name: String,
    pub cfg_path: Option<String>,
    /// 覆盖表里人工确认过的贴图 hash；没有就是 None（🟡 候选态）。
    pub override_hash: Option<String>,
}

/// 一只网格的候选榜单（uvfit --emit-cache 的产物；没有缓存就没有候选，不编造）。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct TexCandGroup {
    /// 候选按这只网格的 UV 排（同网格多槽共用一份榜单）。
    pub mesh: String,
    pub pool: usize,
    pub state: String,
    /// 榜单来源：None = 旧离线缓存（隐含 offline，候选内嵌 PNG）；
    /// Some("batch") = 全库批量缓存（无 PNG，缩略图由 candidate_png 按需现解）。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source: Option<String>,
    /// 这张榜是否按 v2 综合分（adjustedScore）重排过。前端据此说明排序依据——
    /// 由后端出这一句，免得排序规则改了而说明还写着「按 UV 排」。
    pub ranked: bool,
    pub candidates: Vec<TexCand>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct TexCand {
    pub hash: String,
    pub w: u16,
    pub h: u16,
    pub codec: String,
    pub mips: u32,
    /// uvfit 岛内外方差比。特征指标，不是归属概率——前端必须写明「未确认」。
    pub score: f64,
    /// v2 排序分（评分 × 尺寸/alpha 因子）。批量缓存没写这个字段就是 None——
    /// 「没读到」和「0 分」是两件事，前端据此决定摆不摆证据行。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub adjusted_score: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub factors: Option<TexFactors>,
    /// 256² PNG data URL，给「套上看看」直接包到模型上。
    pub png: String,
}

/// uvfit v2 的特征因子（v0.4.2）：UV 贴合、alpha 边界、尺寸先验、黑白偏置、平均色。
/// 这些是「为什么这张排在前面」的可查看证据，不是归属结论。
/// `colorSemantics` / `formatFit` 在核心里还是 None（未实现），这里就不给字段——
/// 前端拿不到就不摆，不给「0」这种看着像结论的假值。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct TexFactors {
    pub uv_fit: f64,
    pub alpha_fit: f64,
    pub size_fit: f64,
    pub black_bias: bool,
    pub white_bias: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mean_color: Option<[u8; 3]>,
}

fn f_of(v: &serde_json::Value, k: &str) -> Option<f64> {
    v.get(k).and_then(|x| x.as_f64())
}

fn factors_of(c: &serde_json::Value) -> Option<TexFactors> {
    let f = c.get("factors")?;
    Some(TexFactors {
        uv_fit: f_of(f, "uvFit")?,
        alpha_fit: f_of(f, "alphaFit")?,
        size_fit: f_of(f, "sizeFit")?,
        black_bias: f.get("blackBias").and_then(|x| x.as_bool()).unwrap_or(false),
        white_bias: f.get("whiteBias").and_then(|x| x.as_bool()).unwrap_or(false),
        mean_color: f.get("meanColor").and_then(|x| x.as_array()).and_then(|a| {
            if a.len() == 3 {
                Some([a[0].as_u64()? as u8, a[1].as_u64()? as u8, a[2].as_u64()? as u8])
            } else {
                None
            }
        }),
    })
}

fn is_texture_name(s: &str) -> bool {
    let low = s.to_ascii_lowercase();
    [".tga", ".dds", ".png", ".jpg", ".bmp", ".webp"]
        .iter()
        .any(|e| low.ends_with(e))
}

pub fn override_file(root: &Path) -> PathBuf {
    root.join(".scratch/model_texture_override.json")
}

fn load_overrides(root: &Path) -> HashMap<String, String> {
    let mut out = HashMap::new();
    if let Ok(raw) = std::fs::read(override_file(root)) {
        if let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) {
            if let Some(map) = v.get("overrides").and_then(|x| x.as_object()) {
                for (k, e) in map {
                    if let Some(h) = e.get("hash").and_then(|x| x.as_str()) {
                        out.insert(k.clone(), h.to_string());
                    }
                }
            }
        }
    }
    out
}

/// 本组悬空贴图槽清单：cfg 出处 + 覆盖表确认状态。
pub fn build_tex_slots(
    dangling: &[(String, String)],
    pm: Option<&tlbb_core::pathmap::PathMap>,
    root: &Path,
) -> Vec<TexSlotInfo> {
    let ov = load_overrides(root);
    let mut out = Vec::new();
    for (kind, name) in dangling {
        if !is_texture_name(kind) && !is_texture_name(name) {
            continue;
        }
        let cfg_path = pm.and_then(|p| p.lookup(name)).map(String::from);
        let key = match &cfg_path {
            Some(p) => format!("cfg:{p}"),
            None => format!("bare:{name}"),
        };
        out.push(TexSlotInfo {
            name: name.clone(),
            cfg_path,
            override_hash: ov.get(&key).cloned(),
        });
    }
    out
}

/// 候选条目在两种缓存里同构：旧缓存多一个内嵌 png，批量缓存没有（留空串）。
fn parse_candidates(v: &serde_json::Value) -> Vec<TexCand> {
    let mut candidates = Vec::new();
    if let Some(arr) = v.get("candidates").and_then(|x| x.as_array()) {
        for c in arr {
            candidates.push(TexCand {
                hash: c.get("hash").and_then(|x| x.as_str()).unwrap_or_default().into(),
                w: c.get("w").and_then(|x| x.as_u64()).unwrap_or(0) as u16,
                h: c.get("h").and_then(|x| x.as_u64()).unwrap_or(0) as u16,
                codec: c.get("codec").and_then(|x| x.as_str()).unwrap_or_default().into(),
                mips: c.get("mips").and_then(|x| x.as_u64()).unwrap_or(0) as u32,
                score: c.get("score").and_then(|x| x.as_f64()).unwrap_or(0.0),
                adjusted_score: f_of(c, "adjustedScore"),
                factors: factors_of(c),
                png: c.get("png").and_then(|x| x.as_str()).unwrap_or_default().into(),
            });
        }
    }
    candidates
}

/// 排序口径（v0.4.2）：缓存里每条都带 adjustedScore 时按它降序——那已经是
/// 「UV 贴合 × 尺寸先验 × alpha 边界」的综合分，比只看方差比更接近人能接受的
/// 顺序。只要有一条缺分（旧离线缓存）就整榜保持缓存原序：一半有分一半没分
/// 时重排，等于把没有证据的那些塞到中间冒充有证据。
///
/// 排序发生在这里（数据出栈之前），不在前端——前端的「第几张」必须和后端
/// 榜单是同一个顺序。
fn rank(mut cands: Vec<TexCand>) -> Vec<TexCand> {
    if cands.is_empty() || !cands.iter().all(|c| c.adjusted_score.is_some()) {
        return cands;
    }
    cands.sort_by(|a, b| {
        b.adjusted_score
            .unwrap()
            .partial_cmp(&a.adjusted_score.unwrap())
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    cands
}

/// 这张榜是否按 v2 综合分重排过（前端据此说明排序依据，不含糊成「按 UV 排」）。
pub fn ranked_by_adjusted(cands: &[TexCand]) -> bool {
    cands.len() > 1 && cands.iter().all(|c| c.adjusted_score.is_some())
}

/// 读 uvfit 候选缓存：每组网格一份，找不到就是没有（🔴，不编造）。
/// 两级来源：`.scratch/texture_candidates/<stem>.json`（旧离线缓存，内嵌 PNG）优先；
/// 没有才回退 `.scratch/uvfit_batch/results/<stem>.json`（全库批量缓存，只有元数据
/// 没有图——2,818 份全内嵌是不现实的体积账，缩略图由前端按需调 candidate_png 现解）。
/// 读不到、解析失败、候选为空都照旧当作没有：宁可 🔴 也不拿编的东西凑数。
pub fn load_candidate_groups(root: &Path, members: &[(String, String, bool)]) -> Vec<TexCandGroup> {
    let mut out = Vec::new();
    for (role, name, resolved) in members {
        if role != "mesh" || !resolved {
            continue;
        }
        let Some(stem) = name.strip_suffix(".mesh") else {
            continue;
        };
        let legacy = root
            .join(".scratch/texture_candidates")
            .join(format!("{stem}.json"));
        let batch = root
            .join(".scratch/uvfit_batch/results")
            .join(format!("{stem}.json"));
        let (raw, source) = match std::fs::read(&legacy) {
            Ok(raw) => (raw, None), // 旧缓存：来源隐含 offline，不写字段
            Err(_) => match std::fs::read(&batch) {
                Ok(raw) => (raw, Some("batch".to_string())),
                Err(_) => continue,
            },
        };
        let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) else {
            continue;
        };
        let candidates = rank(parse_candidates(&v));
        let ranked = ranked_by_adjusted(&candidates);
        if candidates.is_empty() {
            continue;
        }
        out.push(TexCandGroup {
            mesh: name.clone(),
            pool: v.get("pool").and_then(|x| x.as_u64()).unwrap_or(0) as usize,
            state: "candidates".into(),
            source,
            ranked,
            candidates,
        });
        if out.len() >= 2 {
            break;
        }
    }
    out
}

fn now_ts() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

// ----------------------------------------------------------------------- 批量候选缩略图

/// 按 hash 现解一张 256px 缩略图，返回 (mime, 图像字节)。
///
/// 与 inspector::decode_thumb 走同一条链（清单定位 → 单 pak 取字节 → JMT1 解码 /
/// WebP 原样 / 容器直出），只是长边 256——候选卡要看得清纹样，160 太糊。不能直接
/// 复用是因为那边的帮手是私有的、本次只许改本文件；口径一字不差：解不出如实报错，
/// 绝不拿别的图顶。
fn decode_candidate_png(root: &Path, db: &Path, hash: u64) -> Result<(&'static str, Vec<u8>), String> {
    let con = Connection::open_with_flags(
        db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| format!("只读打开资源清单失败：{e}"))?;
    let (pak_name, offset, _stored, rtype): (String, i64, i64, String) = con
        .query_row(
            "SELECT coalesce(pak,''), coalesce(offset,0), coalesce(stored,0), coalesce(type,'') \
             FROM resources WHERE hash = ?1 LIMIT 1",
            [format!("{hash:016x}")],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )
        .map_err(|_| "不在资源清单里".to_string())?;
    let pak = Pak::open(&root.join(format!("{pak_name}.pak")))
        .map_err(|e| format!("打开 {pak_name}.pak 失败：{e}"))?;
    let recs: Vec<_> = pak.records().collect();
    let rec = recs
        .iter()
        .find(|r| r.hash == hash && r.offset as i64 == offset)
        .or_else(|| recs.iter().find(|r| r.hash == hash))
        .ok_or_else(|| "容器索引里没有这条记录".to_string())?;
    let dec = payload::decode(&pak, rec).map_err(|e| format!("取字节失败：{e}"))?;
    match rtype.as_str() {
        "texture" => {
            let t = jmt1::decode(&dec.bytes).map_err(|e| format!("JMT1 解码失败：{e}"))?;
            if let Some(w) = &t.webp {
                return Ok(("image/webp", w.clone()));
            }
            if t.rgba.is_empty() {
                return Err(format!("编码 {} 无像素", t.codec.as_str()));
            }
            let (scaled, w, h) = scale_rgba(&t.rgba, t.width as usize, t.height as usize, 256);
            let png =
                png_bytes(w as u16, h as u16, &scaled, true).map_err(|e| format!("编码 PNG 失败：{e}"))?;
            Ok(("image/png", png))
        }
        "webp" => Ok(("image/webp", dec.bytes)),
        "jpeg" => Ok(("image/jpeg", dec.bytes)),
        "png" => Ok(("image/png", dec.bytes)),
        other => Err(format!(
            "这个文件不是图片（它属于 {other} 那类内部文件），所以出不了图"
        )),
    }
}

/// 人工确认：写覆盖表（只加表，不碰原资源）。
#[tauri::command]
pub fn texture_override_set(
    slot_name: String,
    cfg_path: Option<String>,
    hash: String,
    note: String,
) -> Result<(), String> {
    let (root, _) = crate::inspector::roots();
    let file = override_file(&root);
    let mut v = std::fs::read(&file)
        .ok()
        .and_then(|b| serde_json::from_slice::<serde_json::Value>(&b).ok())
        .unwrap_or_else(|| json!({"overrides": {}}));
    let key = match cfg_path.as_deref() {
        Some(p) if !p.is_empty() => format!("cfg:{p}"),
        _ => format!("bare:{slot_name}"),
    };
    v["overrides"][&key] = json!({"hash": hash, "note": note, "ts": now_ts()});
    if let Some(dir) = file.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let body = serde_json::to_string_pretty(&v).map_err(|e| e.to_string())?;
    std::fs::write(&file, body).map_err(|e| e.to_string())
}

/// 撤销确认：从覆盖表删掉这一条。
#[tauri::command]
pub fn texture_override_clear(slot_name: String, cfg_path: Option<String>) -> Result<(), String> {
    let (root, _) = crate::inspector::roots();
    let file = override_file(&root);
    let Ok(raw) = std::fs::read(&file) else {
        return Ok(()); // 没有表就没什么可撤的
    };
    let mut v: serde_json::Value =
        serde_json::from_slice(&raw).map_err(|e| e.to_string())?;
    let key = match cfg_path.as_deref() {
        Some(p) if !p.is_empty() => format!("cfg:{p}"),
        _ => format!("bare:{slot_name}"),
    };
    if let Some(o) = v.get_mut("overrides").and_then(|x| x.as_object_mut()) {
        o.remove(&key);
    }
    let body = serde_json::to_string_pretty(&v).map_err(|e| e.to_string())?;
    std::fs::write(&file, body).map_err(|e| e.to_string())
}

/// 批量候选的按需缩略图：全库批量缓存只存元数据不存图，前端候选卡先摆占位框，
/// 再按候选自带的编号（hash）来要这一张——现解、缩到长边 256、PNG base64
/// data URL 回去。
///
/// 为什么按编号而不是按「第几名」：榜单出栈前会按 v2 综合分重排，名次从此
/// 不再等于缓存里的下标。按名次取图，迟早把 A 的纹样摆到 B 的卡上——那是
/// 编造证据，比没有图严重得多。编号解不开回 Err（前端保持占位并写明原因）。
#[tauri::command]
pub async fn candidate_png(hash: String) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let (root, db) = crate::inspector::roots();
        let hex = hash.trim().trim_start_matches("0x");
        let hash = u64::from_str_radix(hex, 16)
            .map_err(|_| format!("贴图编号 {hex} 不是合法的 16 位十六进制"))?;
        decode_candidate_png(&root, &db, hash)
            .map(|(mime, bytes)| Some(format!("data:{mime};base64,{}", crate::inspector::b64(&bytes))))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    fn value(json: &str) -> serde_json::Value {
        serde_json::from_str(json).expect("测试里的 JSON 应能解析")
    }

    /// v2 批量缓存：因子与综合分要一路带到前端——那是「凭什么排前面」的唯一凭据。
    #[test]
    fn parses_v2_factors_and_adjusted_score() {
        let v = value(
            r#"{"candidates":[
              {"hash":"aa00000000000001","w":512,"h":512,"codec":"BC3","mips":10,"score":70.0,
               "adjustedScore":1.09,
               "factors":{"uvFit":0.12,"alphaFit":1.0,"sizeFit":1.0,"blackBias":true,"whiteBias":false,"meanColor":[48,34,19]}},
              {"hash":"aa00000000000002","w":256,"h":256,"codec":"RGBA32","mips":8,"score":300.0,
               "adjustedScore":2.5,
               "factors":{"uvFit":0.3,"alphaFit":0.0,"sizeFit":0.8,"blackBias":false,"whiteBias":true,"meanColor":[200,200,200]}}
            ]}"#,
        );
        let got = rank(parse_candidates(&v));
        assert_eq!(got.len(), 2);
        // 综合分降序：分数高（2.5）的那张在前，哪怕它的方差比更低。
        assert_eq!(got[0].hash, "aa00000000000002", "应按综合分排序，不按方差比");
        assert!(ranked_by_adjusted(&got), "全榜都有综合分时应报告已重排");
        let f = got[0].factors.as_ref().expect("因子应带出来");
        assert_eq!((f.uv_fit, f.alpha_fit, f.size_fit), (0.3, 0.0, 0.8));
        assert_eq!(f.black_bias, false);
        assert_eq!(f.white_bias, true);
        assert_eq!(f.mean_color, Some([200, 200, 200]));
    }

    /// 旧离线缓存没有综合分：整榜保持缓存原序，也不谎报「已重排」。
    #[test]
    fn legacy_cache_without_scores_keeps_order_and_says_so() {
        let v = value(
            r#"{"candidates":[
              {"hash":"bb00000000000001","w":512,"h":512,"codec":"BC3","mips":10,"score":900.0,"png":"data:1"},
              {"hash":"bb00000000000002","w":512,"h":512,"codec":"BC3","mips":10,"score":100.0,"png":"data:2"}
            ]}"#,
        );
        let got = rank(parse_candidates(&v));
        assert_eq!(got[0].hash, "bb00000000000001", "没有综合分就保持原序");
        assert!(got.iter().all(|c| c.adjusted_score.is_none()), "缺分应是 None，不是 0");
        assert!(!ranked_by_adjusted(&got));
    }

    /// 一半有分一半没分：不重排。把没证据的那些插进有证据的榜中间，
    /// 等于替它们编了一份不存在的证据。
    #[test]
    fn mixed_cache_is_not_resorted() {
        let v = value(
            r#"{"candidates":[
              {"hash":"cc00000000000001","score":1.0,"adjustedScore":9.0},
              {"hash":"cc00000000000002","score":2.0}
            ]}"#,
        );
        let got = rank(parse_candidates(&v));
        assert_eq!(got[0].hash, "cc00000000000001", "有缺分时保持原序");
        assert!(!ranked_by_adjusted(&got), "半榜有分不能报已重排");
    }

    /// 因子残缺的分两种：三项主因子缺一个就整份作废（主因子是这份榜的排序
    /// 原料，残缺了就不该摆「证据」）；平均色坏掉只丢平均色——UV/透明/尺寸
    /// 那三个数仍然是量出来的事实，不该被一个坏色值连坐。
    #[test]
    fn partial_factors_are_dropped_not_zero_filled() {
        let v = value(
            r#"{"candidates":[
              {"hash":"dd00000000000001","score":1.0,"factors":{"alphaFit":1.0,"sizeFit":1.0}},
              {"hash":"dd00000000000002","score":1.0,"factors":{"uvFit":0.1,"alphaFit":1.0,"sizeFit":1.0,"meanColor":[1,2]}},
              {"hash":"dd00000000000003","score":1.0,"factors":{"uvFit":0.1,"alphaFit":1.0,"sizeFit":1.0,"meanColor":[1,2,3]}}
            ]}"#,
        );
        let got = parse_candidates(&v);
        assert!(got[0].factors.is_none(), "缺 uvFit 的因子应整份作废");
        let bad_color = got[1].factors.as_ref().expect("主因子齐全，平均色坏不该连坐");
        assert_eq!(bad_color.mean_color, None, "meanColor 不是三段时不猜一个颜色");
        assert_eq!(bad_color.uv_fit, 0.1, "其余因子照实带出来");
        let ok = got[2].factors.as_ref().expect("齐全的那份应保留");
        assert_eq!(ok.mean_color, Some([1, 2, 3]));
        assert_eq!(ok.black_bias, false, "黑白偏置缺省是「没有这个偏置」，不是「未知」");
    }

    /// 吃本机批量缓存（随仓库分发的派生元数据，不含像素）：真榜上有因子、
    /// 且出栈顺序确实按综合分。缓存不在这台机器上就自己跳过并说明——
    /// 项目纪律：夹具缺席降级跳过，不算失败。
    #[test]
    fn batch_cache_on_disk_carries_factors_and_ranks() {
        let (root, _db) = crate::inspector::roots();
        let file = std::fs::read_dir(root.join(".scratch/uvfit_batch/results"))
            .map(|it| {
                it.flatten()
                    .find_map(|e| {
                        let p = e.path();
                        p.is_file().then_some(p)
                    })
            })
            .unwrap_or(None);
        let Some(file) = file else {
            eprintln!("跳过：本机没有 .scratch/uvfit_batch/results 批量缓存（离线试贴还没跑）");
            return;
        };
        let stem = file
            .file_stem()
            .unwrap_or_default()
            .to_string_lossy()
            .to_string();
        let groups = load_candidate_groups(
            &root,
            &[("mesh".to_string(), format!("{stem}.mesh"), true)],
        );
        let Some(g) = groups.first() else {
            eprintln!("跳过：{stem} 这份缓存没有可用候选");
            return;
        };
        assert_eq!(g.source.as_deref(), Some("batch"), "批量缓存应标明来源");
        let first = &g.candidates[0];
        assert!(
            first.adjusted_score.is_some() && first.factors.is_some(),
            "v2 缓存的因子必须一路带到前端，实际：{first:?}",
        );
        if g.ranked {
            for w in g.candidates.windows(2) {
                assert!(
                    w[0].adjusted_score.unwrap() >= w[1].adjusted_score.unwrap(),
                    "报「已重排」时榜单应真的按综合分降序：{:?}",
                    g.candidates.iter().filter_map(|c| c.adjusted_score).collect::<Vec<_>>(),
                );
            }
        }
    }

    /// 前端按编号取图：编号进、图出，与名次无关。吃本机真 pak + 清单，
    /// 没有客户端的机器上跳过（和 browse 那几个用例同样的降级口径）。
    #[test]
    fn candidate_png_resolves_by_hash() {
        let (root, db) = crate::inspector::roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端 pak 或资源清单");
            return;
        }
        let (root2, _db2) = (root.clone(), db.clone());
        let first_hash = std::fs::read_dir(root2.join(".scratch/uvfit_batch/results"))
            .ok()
            .and_then(|it| {
                it.flatten().find_map(|e| {
                    let p = e.path();
                    if !p.is_file() {
                        return None;
                    }
                    let v: serde_json::Value = serde_json::from_slice(&std::fs::read(&p).ok()?).ok()?;
                    v.get("candidates")?
                        .as_array()?
                        .first()?
                        .get("hash")?
                        .as_str()
                        .map(|s| s.to_string())
                })
            });
        let Some(hex) = first_hash else {
            eprintln!("跳过：本机批量缓存里没有可用候选编号");
            return;
        };
        let hash = u64::from_str_radix(&hex, 16).expect("缓存里的编号应是 16 位十六进制");
        match decode_candidate_png(&root, &db, hash) {
            Ok((mime, bytes)) => {
                assert!(mime.starts_with("image/"), "mime 应是图片：{mime}");
                assert!(bytes.len() > 100, "{hex} 解出来的图小得不像话：{}", bytes.len());
            }
            // 解不出图是允许的事实（这一张可能就不是可解码贴图），但必须说得出原因。
            Err(e) => {
                assert!(!e.is_empty(), "{hex} 解图失败却给不出原因");
                eprintln!("{hex} 解图失败（如实记录，不算失败）：{e}");
            }
        }
    }
}
