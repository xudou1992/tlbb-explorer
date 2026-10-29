//! 贴图恢复系统 v1 · 步骤③⑤的数据层：候选榜单（uvfit 离线产出）+ 人工覆盖表。
//!
//! 纪律：原资源一个字节不动。覆盖表写在 `<root>/.scratch/model_texture_override.json`，
//! key 用 `cfg:<原始路径>`（90.8% 有）或 `bare:<裸名>`（其余），value 带确认的贴图 hash、
//! 时间，以及（2026-10-26 起）确认时画布上的 `mesh` 网格名——可撤销、可重评。
//! 候选全部是 🟡：uvfit 的分数是特征指标，不是归属结论；只有覆盖表里的才算 🟢。

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use serde_json::json;
use tauri::State;
use tlbb_core::jpak::crypto::path_hash;
use tlbb_core::jpak::Pak;
use tlbb_core::pathmap::PathMap;
use tlbb_core::preview::summary::{material_slots, mdl_summary, ViewBody};
use tlbb_core::preview::{png_bytes, scale_rgba};
use tlbb_core::{jmt1, payload};

use crate::data::AppData;

/// 一个悬空贴图槽：原名、cfg 出处、人工确认状态。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct TexSlotInfo {
    pub name: String,
    pub cfg_path: Option<String>,
    /// 覆盖表里人工确认过的贴图 hash；没有就是 None（🟡 候选态）。
    pub override_hash: Option<String>,
    /// 这个名字在资源库里是否已对上实体。对上了也可能是 UI 小图标（玩家衣服基础色
    /// 实测如此），不代表它是模型大图 ⇒ 仍然列出来给人改标；界面要写「可能是图标」。
    pub resolved: bool,
    /// 客户端转换目录自动对上的匿名贴图（`convert/dxt/ + 逻辑路径`，2026-10-26）。
    /// 这不是候选榜的猜测，是引擎自己的转换路径；有它时界面要摆成「自动对上」。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_hash: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_width: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_height: Option<u16>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_codec: Option<String>,
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
    /// 岛外像素的颜色方差（评分的分母原料：`score = insideVar / (outsideVar + 4)`）。
    /// **0 意味着 UV 岛外没有可比像素**——这时 score 退化成「这张图自己有多忙」，
    /// 排出来的先后说明不了归属。批量缓存必带；旧离线缓存没这个字段就是 None，
    /// 前端对 None 只字不提（「没量过」不是「有对比」）。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub outside_var: Option<f64>,
    /// v2 排序分（评分 × 尺寸/alpha 因子）。批量缓存没写这个字段就是 None——
    /// 「没读到」和「0 分」是两件事，前端据此决定摆不摆证据行。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub adjusted_score: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub factors: Option<TexFactors>,
    /// 这张贴图在**多少只模型**的榜上排过第一（区分度）。全库实测：2,368 只模型的榜首
    /// 只来自 147 张贴图，其中一张当了 260 只的第一名——这种「通吃型冠军」对眼前这只
    /// 模型几乎不提供信息，但卡面看不出来。数一次缓存目录就有，不需要任何人工标注。
    /// 旧离线缓存不在批量结果目录里，取不到就是 None（前端对 None 只字不提）。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub also_first_for: Option<usize>,
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

/// 覆盖表的一条。`mesh` 是确认时画布上那只网格（2026-10-26 起写入）——
/// 槽名和网格名不同名时（头发/衣服槽），只靠「网格同名槽」找不到它；
/// 有了这个字段，`mesh_override_png` 才能把确认结果「加载即贴」回模型。
#[derive(Clone, Debug)]
struct OverrideEntry {
    hash: String,
    mesh: Option<String>,
}

fn load_overrides(root: &Path) -> HashMap<String, OverrideEntry> {
    let mut out = HashMap::new();
    if let Ok(raw) = std::fs::read(override_file(root)) {
        if let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) {
            if let Some(map) = v.get("overrides").and_then(|x| x.as_object()) {
                for (k, e) in map {
                    if let Some(h) = e.get("hash").and_then(|x| x.as_str()) {
                        out.insert(
                            k.clone(),
                            OverrideEntry {
                                hash: h.to_string(),
                                mesh: e.get("mesh").and_then(|x| x.as_str()).map(str::to_string),
                            },
                        );
                    }
                }
            }
        }
    }
    out
}

/// 覆盖表 key 里的槽位名：`cfg:<路径>` 取末段，`bare:<名>` 直接取。
fn slot_of_key(key: &str) -> &str {
    let raw = key
        .strip_prefix("cfg:")
        .or_else(|| key.strip_prefix("bare:"))
        .unwrap_or(key);
    raw.rsplit('/').next().unwrap_or(raw)
}

/// 这只网格在覆盖表里被**显式绑定**的条目。多个都绑定同一只网格时调用方
/// 必须当成歧义、不许随便挑一条——那会把 mask 的图套到基础色槽上。
fn bound_entries_for<'a>(
    ov: &'a HashMap<String, OverrideEntry>,
    mesh: &str,
) -> Vec<(&'a String, &'a OverrideEntry)> {
    let want = mesh.rsplit('/').next().unwrap_or(mesh).trim();
    ov.iter()
        .filter(|(_, e)| {
            e.mesh
                .as_deref()
                .map(|m| m.rsplit('/').next().unwrap_or(m).trim().eq_ignore_ascii_case(want))
                .unwrap_or(false)
        })
        .collect()
}

/// 本组悬空贴图槽清单：cfg 出处 + 覆盖表确认状态。
pub fn build_tex_slots(
    refs: &[(String, String, bool)],
    pm: Option<&tlbb_core::pathmap::PathMap>,
    con: &Connection,
    root: &Path,
) -> Vec<TexSlotInfo> {
    let ov = load_overrides(root);
    // 同名只留一条：只要有一处引用对上了实体，就按「已对上」算（同一名字可能从
    // 多个 .mtl 被引用，悬空/已对上的说法不能同时摆给人）。
    let mut uniq: std::collections::BTreeMap<String, bool> = std::collections::BTreeMap::new();
    for (kind, name, resolved) in refs {
        if !is_texture_name(kind) && !is_texture_name(name) {
            continue;
        }
        let e = uniq.entry(name.clone()).or_insert(false);
        *e |= *resolved;
    }
    let mut out = Vec::new();
    for (name, resolved) in uniq {
        let cfg_path = pm.and_then(|p| p.lookup(&name)).map(String::from);
        let key = match &cfg_path {
            Some(p) => format!("cfg:{p}"),
            None => format!("bare:{name}"),
        };
        let auto = pm.and_then(|p| resolve_texture_auto(p, con, &name));
        let (auto_hash, auto_path, auto_width, auto_height, auto_codec) = match auto {
            Some(a) => (Some(a.hash), Some(a.path), Some(a.width), Some(a.height), Some(a.codec)),
            None => (None, None, None, None, None),
        };
        out.push(TexSlotInfo {
            override_hash: ov.get(&key).map(|e| e.hash.clone()),
            name,
            cfg_path,
            resolved,
            auto_hash,
            auto_path,
            auto_width,
            auto_height,
            auto_codec,
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
                outside_var: f_of(c, "outsideVar"),
                adjusted_score: f_of(c, "adjustedScore"),
                factors: factors_of(c),
                also_first_for: None,
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

/// 进程内缓存：`<root> → (每张贴图当过多少次榜首)`。
/// 扫一次 2,818 个结果文件，所以只算一次；root 变了要重算（测试与换库都会走到这条）。
static FIRST_PLACES: std::sync::Mutex<Option<(PathBuf, HashMap<String, usize>)>> =
    std::sync::Mutex::new(None);

fn first_place_counts(root: &Path) -> HashMap<String, usize> {
    let mut g = match FIRST_PLACES.lock() {
        Ok(g) => g,
        Err(p) => p.into_inner(),
    };
    if let Some((_, m)) = g.as_ref().filter(|(r, _)| r == root) {
        return m.clone();
    }
    let m = scan_first_places(root);
    *g = Some((root.to_path_buf(), m.clone()));
    m
}

/// 数榜首：口径与前端看到的**一致**——先 `parse_candidates` + `rank`（综合分降序），
/// 再取第一名。直接读缓存里的第一条是错的：那是方差比顺序，榜出栈前会重排。
fn scan_first_places(root: &Path) -> HashMap<String, usize> {
    let dir = root.join(".scratch/uvfit_batch/results");
    let Ok(rd) = std::fs::read_dir(&dir) else {
        return HashMap::new();
    };
    let mut out: HashMap<String, usize> = HashMap::new();
    for e in rd.flatten() {
        let p = e.path();
        if p.extension().and_then(|x| x.to_str()) != Some("json") {
            continue;
        }
        let Ok(raw) = std::fs::read(&p) else { continue };
        let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) else { continue };
        if let Some(c) = rank(parse_candidates(&v)).first() {
            *out.entry(c.hash.clone()).or_default() += 1;
        }
    }
    out
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
        let counts = first_place_counts(root);
        let candidates: Vec<TexCand> = rank(parse_candidates(&v))
            .into_iter()
            .map(|mut c| {
                c.also_first_for = counts.get(&c.hash).copied();
                c
            })
            .collect();
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
        // 一组常有多份网格（衣服/头发/鞋/手套/脸），每份的榜带各自的网格名。
        // 以前只回 2 份，选中第 3 份时前端拿不到它的榜，自动试贴退回「第一份」，
        // 把脸的贴图套到头发上（2026-10-25 真窗口撞到）。8 份覆盖角色组，且不再兜底。
        if out.len() >= 8 {
            break;
        }
    }
    out
}

/// 这一组里批量试贴明确判定「没有 UV」的网格。只看批量缓存：
/// `hasUv == false` 或 `error == "无 UV"`。没缓存（还没跑过）不算——
/// 那是「不知道」，不能写成「读不出」，交给前端的进度话术。
pub fn load_no_uv_meshes(root: &Path, members: &[(String, String, bool)]) -> Vec<String> {
    let mut out = Vec::new();
    for (role, name, resolved) in members {
        if role != "mesh" || !resolved {
            continue;
        }
        let Some(stem) = name.strip_suffix(".mesh") else {
            continue;
        };
        let batch = root
            .join(".scratch/uvfit_batch/results")
            .join(format!("{stem}.json"));
        let Ok(raw) = std::fs::read(&batch) else {
            continue;
        };
        let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) else {
            continue;
        };
        let err = v.get("error").and_then(|x| x.as_str()).unwrap_or("");
        // 只认批量引擎明确写出的「无 UV」。`清单里解析不到 hash` / 取不到字节 / 几何解析失败
        // 都是「这份网格没能解析」，不是「它没有 UV」——混进来会把缺文件说成缺 UV（2026-10-25）。
        if err == "无 UV" {
            out.push(name.clone());
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
/// 按 hash 取**原始字节**与该行的类型：清单定位 → 开那一个 pak → 找记录 → 解码容器。
/// `decode_candidate_png` 与 UV 岛分布图共用这一条，两边不可能出现「一个取得到一个取不到」。
fn fetch_raw(root: &Path, db: &Path, hash: u64) -> Result<(Vec<u8>, String), String> {
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
    Ok((dec.bytes, rtype))
}

/// 把一张贴图/图片资源解成缩略图（长边 256）或原样字节。
fn decode_candidate_png(root: &Path, db: &Path, hash: u64) -> Result<(&'static str, Vec<u8>), String> {
    decode_image(root, db, hash, 256)
}

fn decode_image(
    root: &Path,
    db: &Path,
    hash: u64,
    max_side: usize,
) -> Result<(&'static str, Vec<u8>), String> {
    let (bytes, rtype) = fetch_raw(root, db, hash)?;
    match rtype.as_str() {
        "texture" => {
            let t = jmt1::decode(&bytes).map_err(|e| format!("JMT1 解码失败：{e}"))?;
            if let Some(w) = &t.webp {
                return Ok(("image/webp", w.clone()));
            }
            if t.rgba.is_empty() {
                return Err(format!("编码 {} 无像素", t.codec.as_str()));
            }
            let (pixels, w, h) = if t.width as usize > max_side || t.height as usize > max_side {
                scale_rgba(&t.rgba, t.width as usize, t.height as usize, max_side)
            } else {
                (t.rgba.clone(), t.width as usize, t.height as usize)
            };
            let png =
                png_bytes(w as u16, h as u16, &pixels, true).map_err(|e| format!("编码 PNG 失败：{e}"))?;
            Ok(("image/png", png))
        }
        "webp" => Ok(("image/webp", bytes)),
        "jpeg" => Ok(("image/jpeg", bytes)),
        "png" => Ok(("image/png", bytes)),
        other => Err(format!(
            "这个文件不是图片（它属于 {other} 那类内部文件），所以出不了图"
        )),
    }
}

/// 人工确认：写覆盖表（只加表，不碰原资源）。
#[tauri::command]
/// 写一条人工确认。`mesh` 是确认时画布上那只网格（可空；新界面必传）——
/// 槽名和网格名不同名时，加载即贴只能靠这个绑定找回，不能靠同名猜。
pub fn texture_override_set(
    slot_name: String,
    cfg_path: Option<String>,
    hash: String,
    note: String,
    mesh: Option<String>,
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
    let mut entry = json!({"hash": hash, "note": note, "ts": now_ts()});
    if let Some(m) = mesh.as_deref() {
        let base = m.rsplit('/').next().unwrap_or(m).trim();
        if !base.is_empty() {
            entry["mesh"] = json!(base);
        }
    }
    v["overrides"][&key] = entry;
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

/// 「加载即贴」的回包：确认过的那张匿名贴图，解成 PNG data URL。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MeshOverridePng {
    pub png: String,
    pub hash: String,
    pub slot: String,
    /// `auto` = 客户端转换目录 `convert/dxt/ + 逻辑路径` 自动对上的真文件；
    /// `manual` = 覆盖表里的人工标注。自动能对上时优先用自动（不是猜，是客户端的路径）。
    pub source: String,
    /// auto 时带上客户端转换路径，给界面写清「凭什么说这张是真的」。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub auto_path: Option<String>,
}

/// 自动解析：贴图名 → `ResourcePath.cfg` 逻辑路径 → `convert/{dxt,astc,etc,pvr}/` 前缀
/// → `path_hash` → 资源库的匿名贴图行。2026-10-26 实测全库 9,491 条贴图命中。
/// 这是客户端自己的转换目录规则（`sub_1401074A0` 里的硬编码字符串），不是我们拼的猜测。
#[derive(Debug, Clone)]
pub(crate) struct AutoTexture {
    pub(crate) hash: String,
    pub(crate) path: String,
    pub(crate) width: u16,
    pub(crate) height: u16,
    pub(crate) codec: String,
}

/// 给别的模块用（预览图那栏）：名字 → 客户端转换路径对上的贴图 hash。
/// 走的是同一条 `convert/*` 规则，不另写一套。
pub(crate) fn auto_texture_hash(pm: &PathMap, con: &Connection, name: &str) -> Option<(String, String)> {
    resolve_texture_auto(pm, con, name).map(|a| (a.hash, a.path))
}

fn resolve_texture_auto(pm: &PathMap, con: &Connection, name: &str) -> Option<AutoTexture> {
    let path = pm.lookup(name)?;
    for prefix in ["convert/dxt/", "convert/astc/", "convert/etc/", "convert/pvr/"] {
        let converted = format!("{prefix}{path}");
        let h = format!("{:016x}", path_hash(&converted));
        if let Ok((w, hgt, codec)) = con.query_row(
            "select coalesce(width,0), coalesce(height,0), coalesce(codec,'') \
             from resources where hash=? and type='texture'",
            [&h],
            |r| {
                Ok((
                    r.get::<_, i64>(0)? as u16,
                    r.get::<_, i64>(1)? as u16,
                    r.get::<_, String>(2)?,
                ))
            },
        ) {
            return Some(AutoTexture {
                hash: h,
                path: converted,
                width: w,
                height: hgt,
                codec,
            });
        }
    }
    None
}

/// 解一条自动对上的贴图（客户端 convert/dxt 路径）。
fn decode_auto(root: &Path, db: &Path, a: &AutoTexture, slot: &str) -> Result<MeshOverridePng, String> {
    decode_auto_sized(root, db, a, slot, 256)
}

fn decode_auto_sized(
    root: &Path,
    db: &Path,
    a: &AutoTexture,
    slot: &str,
    max_side: usize,
) -> Result<MeshOverridePng, String> {
    let hash = u64::from_str_radix(a.hash.trim().trim_start_matches("0x"), 16)
        .map_err(|_| format!("自动解析出的编号 {} 不是合法的十六进制", a.hash))?;
    let (mime, bytes) = decode_image(root, db, hash, max_side)?;
    Ok(MeshOverridePng {
        png: format!("data:{mime};base64,{}", crate::inspector::b64(&bytes)),
        hash: a.hash.clone(),
        slot: slot.to_string(),
        source: "auto".into(),
        auto_path: Some(a.path.clone()),
    })
}

fn decode_manual(root: &Path, db: &Path, hash_text: &str, slot: &str) -> Result<MeshOverridePng, String> {
    decode_manual_sized(root, db, hash_text, slot, 256)
}

fn decode_manual_sized(
    root: &Path,
    db: &Path,
    hash_text: &str,
    slot: &str,
    max_side: usize,
) -> Result<MeshOverridePng, String> {
    let hex = hash_text.trim().trim_start_matches("0x");
    let hash = u64::from_str_radix(hex, 16)
        .map_err(|_| format!("覆盖表里的编号 {hex} 不是合法的 16 位十六进制"))?;
    let (mime, bytes) = decode_image(root, db, hash, max_side)?;
    Ok(MeshOverridePng {
        png: format!("data:{mime};base64,{}", crate::inspector::b64(&bytes)),
        hash: hash_text.to_string(),
        slot: slot.to_string(),
        source: "manual".into(),
        auto_path: None,
    })
}

/// 查询内核（同步版，测试与命令共用）：
/// ① 覆盖表里显式绑定到这只网格的槽（头发/衣服）：**先按客户端 convert/dxt 自动解析这条槽**，
///    解析不到才用人工 hash；
/// ② 没有绑定时，网格同名槽（stem + 贴图扩展名）：同样自动优先、人工兜底。
/// 自动解析是客户端自己的转换目录规则，不是候选榜的猜测；人工表只兜住解析不到的名字。
/// 多条绑定时拒绝猜（mask 与基础色各一条时套错比灰模更坏）。
fn mesh_override_png_sync(
    root: &Path,
    db: &Path,
    name: &str,
) -> Result<Option<MeshOverridePng>, String> {
    let tail = name.rsplit('/').next().unwrap_or(name).trim();
    let Some(stem) = tail.strip_suffix(".mesh") else {
        return Ok(None); // 不是网格文件名，没有「对应槽位」可言
    };
    let pm = PathMap::load(root);
    let ov = load_overrides(root);
    let con = Connection::open_with_flags(
        db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok();

    // ① 人工绑定到这只网格的槽：人工优先（人可能故意选别的），自动只兜底解析不到的名字。
    let bound = bound_entries_for(&ov, tail);
    match bound.as_slice() {
        [(key, e)] => {
            let slot = slot_of_key(key);
            return decode_manual(root, db, &e.hash, slot).map(Some);
        }
        [] => {}
        many => {
            let slots = many
                .iter()
                .map(|(k, _)| slot_of_key(k))
                .collect::<Vec<_>>()
                .join("、");
            return Err(format!(
                "这只网格有 {} 条人工确认（{slots}），不知道该套哪一条；先在槽位清单里撤销多余的那条",
                many.len()
            ));
        }
    }

    // ② 网格同名槽：人工优先，没有人工才用客户端 convert/dxt 自动对上。
    for ext in [".tga", ".dds", ".png", ".jpg", ".bmp", ".webp"] {
        let slot = format!("{stem}{ext}");
        let cfg_path = pm.as_ref().and_then(|p| p.lookup(&slot)).map(String::from);
        let key = match cfg_path.as_deref() {
            Some(p) if !p.is_empty() => format!("cfg:{p}"),
            _ => format!("bare:{slot}"),
        };
        if let Some(e) = ov.get(&key) {
            return decode_manual(root, db, &e.hash, &slot).map(Some);
        }
        if let (Some(pm), Some(con)) = (pm.as_ref(), con.as_ref()) {
            if let Some(a) = resolve_texture_auto(pm, con, &slot) {
                return decode_auto(root, db, &a, &slot).map(Some);
            }
        }
    }
    Ok(None)
}

/// 「加载即贴」：模型渲染前查一次覆盖表，人工确认过的贴图直接套上——
/// 确认层存在的意义就是让确认的成果持久，不该每次开模型都手动再套一遍。
/// 查不到（这格没确认过）回 None，前端灰模照旧；候选榜第一名**绝不**冒充
/// 确认结果——🟡 是 🟡，🟢 是 🟢，这条线不能糊。
#[tauri::command]
pub async fn mesh_override_png(name: String) -> Result<Option<MeshOverridePng>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let (root, db) = crate::inspector::roots();
        mesh_override_png_sync(&root, &db, &name)
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 分层贴图的一块。`blend=opaque` 是基础层，`add` 是特效层（叠加）。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct LayerTexture {
    pub hash: String,
    pub png: String,
    pub slot: String,
    /// `manual` = 覆盖表人工确认；`auto` = 客户端 convert/dxt 路径自动对上。
    pub source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub path: Option<String>,
}

/// 一个子网格的贴图。`faceStart/faceCount` 是**面**为单位，前端乘 3 变索引数。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct TextureLayer {
    pub face_start: usize,
    pub face_count: usize,
    pub blend: String,
    pub color: LayerTexture,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mask: Option<LayerTexture>,
    pub slot: String,
}

/// 分层对齐的可核证据（2026-10-26 普查 1,200 份「材质表 + 同名网格」后定的口径）：
/// **颜色贴图数（不含 `_pbr`、不含遮罩）== 子网格段数**在 1,069/1,200 份上成立，
/// 而「材质段数 == 子网格数」只有 259/1,200——所以段数对齐不能当判据，
/// 颜色层数对齐才是。界面要把这两个数摆出来，对了就说对了，没对就说没验证。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct LayerEvidence {
    /// 子网格段数。
    pub submeshes: usize,
    /// 材质表里的颜色贴图张数（不含 pbr/遮罩）。
    pub color_layers: usize,
    /// 两者是否相等——相等才敢说「一张颜色对一段」。
    pub aligned: bool,
    /// 遮罩没配上颜色层的张数（配不上的遮罩画不出层，界面要如实报）。
    pub unpaired_masks: usize,
}

/// 从最终的分层结果回推证据：颜色层数、遮罩配对情况，和段数比一比。
fn layer_evidence(counts: &[u32], refs: &[TexRef], extras: &[LayerSpec]) -> LayerEvidence {
    let is_mask = |s: &str| s.to_ascii_lowercase().contains("mask");
    let color_layers = refs.iter().filter(|r| !is_mask(&r.name)).count();
    let masks_total = refs.iter().filter(|r| is_mask(&r.name)).count();
    let paired = extras.iter().filter(|e| e.mask.is_some()).count();
    LayerEvidence {
        submeshes: counts.len(),
        color_layers,
        aligned: color_layers == counts.len(),
        unpaired_masks: masks_total.saturating_sub(paired),
    }
}

/// 没解出来的层要**点名**：只报数量的话，人只知道「少了一段」，不知道是哪张图、
/// 该去哪条槽位补候选。名字一律取材质表原文的尾段，不改写、不翻译。
fn skipped_note(names: &[String]) -> String {
    let show = names
        .iter()
        .take(3)
        .map(|n| tail_of(n).to_string())
        .collect::<Vec<_>>()
        .join("、");
    let more = if names.len() > 3 {
        format!(" 等 {} 张", names.len())
    } else {
        String::new()
    };
    format!("（{} 段贴图没解出来，未画：{show}{more}）", names.len())
}

/// 材质表里没有颜色图时给用户看的一句话（不是「解析失败」）。
/// 普查 1,200 份里 87 份是这形状，其中 **82 份一张贴图都没有**（`w1351_an_model_wave_h001`
/// 这种：材质只有 `template_default.mtl` + `DynModelShader`），5 份只有 pbr。
/// 这两类颜色都由客户端着色器算，预览器复现不了。
fn no_color_note(pbr: usize, masks: usize, tex_total: usize) -> String {
    if tex_total == 0 {
        return "材质表里没有任何贴图（只有材质模板 + 着色器），颜色由客户端着色器算，预览器复现不了 ⇒ 保持灰模"
            .to_string();
    }
    let extra = if masks > 0 {
        format!("、遮罩 {masks} 张")
    } else {
        String::new()
    };
    format!(
        "材质表里只有 pbr 贴图 {pbr} 张{extra}，没有颜色图——客户端用水波/特效着色器画，预览器复现不了 ⇒ 保持灰模"
    )
}

/// 把证据写成人话。三种形状各说各的，别用一句「对不上」糊过去：
/// * 相等：一张颜色对一段；
/// * 颜色**少于**段数：材质表就那么几张颜色（客户端也没别的可绑），其余段按基础层铺；
/// * 颜色**多于**段数：多出来的叠在基础段上。
fn evidence_line(ev: &LayerEvidence) -> String {
    if ev.aligned {
        format!(
            "颜色贴图 {} 张 = 子网格 {} 段（一张对一段）",
            ev.color_layers, ev.submeshes
        )
    } else if ev.color_layers < ev.submeshes {
        format!(
            "颜色贴图 {} 张 < 子网格 {} 段：材质表只给了 {} 张，其余 {} 段按基础层铺（顺序未验证）",
            ev.color_layers,
            ev.submeshes,
            ev.color_layers,
            ev.submeshes - ev.color_layers
        )
    } else {
        format!(
            "颜色贴图 {} 张 > 子网格 {} 段：多出的 {} 张叠在基础段上（顺序未验证）",
            ev.color_layers,
            ev.submeshes,
            ev.color_layers - ev.submeshes
        )
    }
}

/// 一只网格的分层贴图计划：基础层在前，特效层按 `.mtl` 顺序。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MeshTexturePlan {
    pub mesh: String,
    pub layers: Vec<TextureLayer>,
    /// 这只网格自己的 `.mtl` 里出现的全部贴图名（含 pbr/mask），按文件顺序。
    /// 界面据此把「整组的槽位」收窄到当前网格，避免拿别的模型的贴图来标。
    pub slot_names: Vec<String>,
    /// 叠加特效层数（`effect_add_trans`）与不透明材质层数，界面据此说人话。
    pub effect_layers: usize,
    pub opaque_layers: usize,
    /// 每段几何的面数，界面用它说「第 k/n 段」。
    pub face_counts: Vec<u32>,
    /// 分层是不是有数可对：颜色层数与子网格段数是否一致。
    pub evidence: LayerEvidence,
    pub note: String,
}

fn tail_of(p: &str) -> &str {
    p.rsplit('/').next().unwrap_or(p)
}

fn stem_of(p: &str) -> &str {
    let t = tail_of(p);
    t.rsplit_once('.').map(|(s, _)| s).unwrap_or(t)
}

fn plan_texture(
    root: &Path,
    db: &Path,
    pm: Option<&PathMap>,
    con: Option<&Connection>,
    ov: &HashMap<String, OverrideEntry>,
    slot: &str,
    max_side: usize,
) -> Option<LayerTexture> {
    let cfg_path = pm.and_then(|p| p.lookup(slot)).map(String::from);
    let key = match cfg_path.as_deref() {
        Some(p) if !p.is_empty() => format!("cfg:{p}"),
        _ => format!("bare:{slot}"),
    };
    if let Some(e) = ov.get(&key) {
        if let Ok(p) = decode_manual_sized(root, db, &e.hash, slot, max_side) {
            return Some(LayerTexture {
                hash: p.hash,
                png: p.png,
                slot: slot.to_string(),
                source: p.source,
                path: cfg_path,
            });
        }
    }
    if let (Some(pm), Some(con)) = (pm, con) {
        if let Some(a) = resolve_texture_auto(pm, con, slot) {
            if let Ok(p) = decode_auto_sized(root, db, &a, slot, max_side) {
                return Some(LayerTexture {
                    hash: p.hash,
                    png: p.png,
                    slot: slot.to_string(),
                    source: p.source,
                    path: Some(a.path),
                });
            }
        }
    }
    None
}

/// 材质表里的贴图名（保持文件顺序）→ 基础色 + 额外层。
/// 返回 `(add, mask, color)`：`add=true` 才是叠加特效；手套/鞋这类第二材质
/// 即使贴图名排在后面，也必须按不透明层画。
///
/// 判据只有两条，且都能被单元测试钉住：
/// * `_pbr` 永远是通道图，不是颜色层；
/// 材质表里的一条贴图引用：名字 + 它自己的材质是不是叠加。
#[derive(Debug, Clone, PartialEq)]
struct TexRef {
    name: String,
    /// 叠加（特效）。证据取**离这条贴图最近的那个材质名**里有没有 `add`
    /// （`template_default_effect_add_trans` 这种）。普查 1,200 份：着色器名
    /// 0 份带 add/trans，混合模式只写在材质名里，别处找不到。
    add: bool,
    /// 认领到的材质在字符串表里的下标（usize::MAX = 没有材质名）。同一条材质的
    /// 多张贴图靠它分组，才能判断「这一组里的第一张是不是模型自己的图」。
    mat: usize,
}

/// 一层的规格：颜色图、可选遮罩、是否叠加。
#[derive(Debug, Clone, PartialEq)]
struct LayerSpec {
    color: String,
    mask: Option<String>,
    add: bool,
    mat: usize,
}

/// 按位置给每条贴图认领材质名：谁离得近算谁的，一样近认领前面那个。
///
/// 为什么不按「材质名起段、段内贴图归它」：普查 1,200 份里 **907 份**的字符串顺序是
/// `贴图 材质 着色器`——贴图排在它自己的材质名**前面**；起段会把这张贴图配给上一条
/// 材质（多数情况下前面根本没有材质名）。剩下的 152 份才是 `材质 贴图 着色器`。
/// 最近认领对两种顺序都成立。`_pbr` 是通道图，根本不成层，这里直接不收。
fn texture_refs(items: &[(String, String)]) -> Vec<TexRef> {
    let low = |s: &str| s.to_ascii_lowercase();
    let mats: Vec<usize> = items
        .iter()
        .enumerate()
        .filter(|(_, (role, _))| role == "材质")
        .map(|(i, _)| i)
        .collect();
    // 第一遍：每条贴图（不含 `_pbr`）按位置认领离它最近的材质名，一样近取前面那个。
    let mut refs: Vec<TexRef> = Vec::new();
    for (i, (role, name)) in items.iter().enumerate() {
        if role != "贴图" || low(name).contains("_pbr") {
            continue;
        }
        let add = match mats
            .iter()
            .min_by_key(|&&m| ((m as isize - i as isize).abs(), if m < i { 0 } else { 1 }))
        {
            Some(&m) => low(&items[m].1).contains("add"),
            None => false,
        };
        let mat = mats
            .iter()
            .min_by_key(|&&m| ((m as isize - i as isize).abs(), if m < i { 0 } else { 1 }))
            .copied()
            .unwrap_or(usize::MAX);
        refs.push(TexRef {
            name: name.clone(),
            add,
            mat,
        });
    }
    // 第二遍：遮罩自己不铺颜色，它的混合模式应该跟它配的那张颜色图一致——
    // 按「后面第一张非遮罩贴图」取，后面没有就取前面最近的一张。
    let mask_add: Vec<Option<bool>> = (0..refs.len())
        .map(|k| {
            if !low(&refs[k].name).contains("mask") {
                return None;
            }
            (k + 1..refs.len())
                .find(|&j| !low(&refs[j].name).contains("mask"))
                .or_else(|| (0..k).rev().find(|&j| !low(&refs[j].name).contains("mask")))
                .map(|j| refs[j].add)
        })
        .collect();
    for (k, r) in refs.iter_mut().enumerate() {
        if let Some(add) = mask_add[k] {
            r.add = add;
        }
    }
    refs
}

/// 贴图引用 → 基础层 + 额外层。
///
/// 基础色先认与网格同名的那张（衣服/头发实测都是这形状），否则第一张非遮罩非粒子图；
/// 基础层永远不透明——它是唯一铺满几何的底色，按叠加画整只模型会变半透明。
/// 遮罩按「同一材质里紧跟其后的那张颜色图」配对，配不上就不配（证据里计数）。
fn layer_specs(refs: &[TexRef], stem: &str) -> Option<(LayerSpec, Vec<LayerSpec>)> {
    let low = |s: &str| s.to_ascii_lowercase();
    let exts = [".tga", ".dds", ".png", ".jpg", ".webp"];
    let is_mask = |s: &str| low(s).contains("mask");
    let base_at = refs
        .iter()
        .position(|r| exts.iter().any(|e| low(&r.name) == format!("{stem}{e}")))
        .or_else(|| {
            refs.iter()
                .position(|r| !is_mask(&r.name) && !low(&r.name).contains("point"))
        })?;
    let base = refs[base_at].clone();
    let mut extras: Vec<LayerSpec> = Vec::new();
    for (i, r) in refs.iter().enumerate() {
        if i == base_at || is_mask(&r.name) {
            continue;
        }
        // 紧挨在这张颜色图前面的遮罩归它。
        let mask = if i > 0 && is_mask(&refs[i - 1].name) {
            Some(refs[i - 1].name.clone())
        } else {
            None
        };
        extras.push(LayerSpec {
            color: r.name.clone(),
            mask,
            add: r.add,
            mat: r.mat,
        });
    }
    // 同一叠加材质里「多张颜色图、都没遮罩」时，第一张是模型自己的图，不是特效：
    // 普查这 12 例多颜色特效段，第一张 12/12 只在单个模型出现，后续 11/12 是跨模型
    // 共用图（`texture_lf012` 就出现在 10 个模型里）。照叠加画，旗子/卷轴会整片透明。
    // 同一材质里带遮罩的（先锋衣服 4 组 mask+颜色）不在此列：遮罩本身就是叠加证据。
    let mut i = 0;
    while i < extras.len() {
        let mat = extras[i].mat;
        let mut end = i + 1;
        while end < extras.len() && extras[end].mat == mat {
            end += 1;
        }
        let group = &mut extras[i..end];
        if group.len() >= 2 && group.iter().all(|e| e.mask.is_none() && e.add) {
            group[0].add = false;
        }
        i = end;
    }
    Some((
        LayerSpec {
            color: base.name,
            mask: None,
            add: false,
            mat: base.mat,
        },
        extras,
    ))
}

/// 把 N 条额外材质分到子网格上：每个子网格一条，多出来的叠在**基础子网格**（第 0 段）上。
/// 返回 `(face_start, face_count, 是否叠在已有几何上)`；叠上去的那几条渲染时必须用叠加，
/// 不透明的“第二层”只会把基础色整片盖掉。
fn plan_placements(counts: &[u32], overlay_count: usize) -> Vec<(usize, usize, bool)> {
    let nsub = counts.len();
    if nsub == 0 {
        return Vec::new();
    }
    let per_sub = overlay_count.min(nsub.saturating_sub(1));
    let extra = overlay_count - per_sub;
    let base_count = nsub - per_sub;
    let mut start: usize = counts[..base_count].iter().map(|&x| x as usize).sum();
    let mut out = Vec::with_capacity(overlay_count);
    for j in 0..per_sub {
        let c = counts[base_count + j] as usize;
        out.push((start, c, false));
        start += c;
    }
    let sub0 = counts.first().copied().unwrap_or(0) as usize;
    for _ in 0..extra {
        out.push((0, sub0, true));
    }
    out
}

fn mesh_texture_plan_sync(
    app: &AppData,
    gid: i64,
    name: &str,
    hash: Option<&str>,
) -> Result<MeshTexturePlan, String> {
    // 尾部名会重名（`_b2.mesh` 一族），有 hash 就按 hash 精确定位这张网格。
    let (mesh_path, layout) = app.mesh_layout(name, hash)?;
    let counts = layout.face_counts.clone();
    if counts.is_empty() {
        return Err("这只网格没有子网格切分，无法分层".to_string());
    }
    let stem = stem_of(&mesh_path).to_ascii_lowercase();
    let mesh_tail = tail_of(&mesh_path).to_ascii_lowercase();
    let lite = app
        .lite_of(gid)
        .ok_or_else(|| format!("资产组 {gid} 还没读完"))?;
    let (root, db) = crate::inspector::roots();
    // 优先跟随 `.mdl` 的 body→material：大组里网格尾部名会重名（`_b2.mesh` 有一族），
    // 光按名字/茎取材质会把别的模型的材质表拿来，里面自然没有这张网格的贴图。
    let want_mdl = lite.group.stem.to_ascii_lowercase();
    let mdl_idx = lite
        .members
        .iter()
        .enumerate()
        .filter(|(_, m)| {
            m.path
                .as_deref()
                .map(|p| p.to_ascii_lowercase().ends_with(".mdl"))
                .unwrap_or(false)
        })
        .min_by_key(|(_, m)| {
            if stem_of(m.path.as_deref().unwrap_or("")).eq_ignore_ascii_case(&want_mdl) {
                0
            } else {
                1
            }
        })
        .map(|(i, _)| i);
    let from_mdl = mdl_idx.and_then(|i| {
        let raw = app.read(lite.members[i].hash)?;
        let ViewBody::Model(mdl) = mdl_summary(&raw, |_| None) else {
            return None;
        };
        let body = mdl
            .bodies
            .iter()
            .find(|b| tail_of(&b.mesh.name).eq_ignore_ascii_case(&mesh_tail))?;
        if let Some(h) = body.material.resolved {
            return app.read(h); // 材质可能是共享模板，不在本组成员里
        }
        if let Some(hit) = crate::sidecar::lookup(&root, &body.material.name) {
            if let Some(raw) = app.read(hit.hash) {
                return Some(raw); // 变体材质只在 sidecar 里有身份
            }
        }
        let mat_tail = tail_of(&body.material.name);
        lite.members
            .iter()
            .find(|x| {
                x.path
                    .as_deref()
                    .map(|p| tail_of(p).eq_ignore_ascii_case(mat_tail))
                    .unwrap_or(false)
            })
            .and_then(|x| app.read(x.hash))
    });
    let raw = match from_mdl {
        Some(r) => r,
        None => {
            let mtl = lite
                .members
                .iter()
                .filter(|m| {
                    m.path
                        .as_deref()
                        .map(|p| p.to_ascii_lowercase().ends_with(".mtl"))
                        .unwrap_or(false)
                })
                .min_by_key(|m| {
                    let p = m.path.as_deref().unwrap_or("");
                    if stem_of(p).eq_ignore_ascii_case(&stem) {
                        0
                    } else {
                        1
                    }
                })
                .ok_or_else(|| "这一组没有材质文件，无法按层取贴图".to_string())?;
            app.read(mtl.hash)
                .ok_or_else(|| "材质文件读不出来".to_string())?
        }
    };
    let slots = match material_slots(&raw, |_| None) {
        ViewBody::Material(s) => s,
        other => return Err(format!("材质表解析不出槽位：{other:?}")),
    };
    // 按文件顺序留 (角色, 名字)：材质名的**位置**就是判据（贴图认领离它最近的那条材质）。
    let items: Vec<(String, String)> = slots
        .iter()
        .map(|s| (s.role.clone(), s.name.clone()))
        .collect();
    let mut names = Vec::new();
    let mut seen = HashSet::new();
    for s in slots {
        if s.role == "贴图" && seen.insert(s.name.clone()) {
            names.push(s.name);
        }
    }
    if names.is_empty() {
        // 一张贴图都没有：水波这类纯着色器件（普查 1,200 份里 82 份）。不是解析失败。
        return Ok(MeshTexturePlan {
            mesh: mesh_path,
            layers: Vec::new(),
            slot_names: Vec::new(),
            effect_layers: 0,
            opaque_layers: 0,
            face_counts: counts.clone(),
            evidence: layer_evidence(&counts, &[], &[]),
            note: no_color_note(0, 0, 0),
        });
    }
    let slot_names = names.clone();
    let refs = texture_refs(&items);
    let Some((base_spec, overlays)) = layer_specs(&refs, &stem) else {
        // 材质表里一张颜色图都没有（普查 1,200 份里 87 份，全是 `template_pbr_water` 一类）。
        // 这不是解析失败，是这类特效件本来只给 pbr/遮罩、颜色由客户端着色器算 ⇒ 老实说清。
        let pbr = items
            .iter()
            .filter(|(r, n)| r == "贴图" && n.to_ascii_lowercase().contains("_pbr"))
            .count();
        let masks = refs
            .iter()
            .filter(|r| r.name.to_ascii_lowercase().contains("mask"))
            .count();
        return Ok(MeshTexturePlan {
            mesh: mesh_path,
            layers: Vec::new(),
            slot_names,
            effect_layers: 0,
            opaque_layers: 0,
            face_counts: counts.clone(),
            evidence: layer_evidence(&counts, &refs, &[]),
            note: no_color_note(pbr, masks, names.len()),
        });
    };
    let base_name = base_spec.color.clone();
    let evidence = layer_evidence(&counts, &refs, &overlays);
    let nsub = counts.len();
    // 每个子网格分一条；材质表里的额外层比子网格多时，多出来的叠在**基础子网格**上，
    // 不再直接丢掉——`w1351_monster_baiqizi` 这类 1 子网格 + 1 特效层就是这形状。
    let overlay_places = plan_placements(&counts, overlays.len());
    let base_count = nsub - overlays.len().min(nsub.saturating_sub(1));
    let base_faces: usize = counts[..base_count].iter().map(|&x| x as usize).sum();
    let extra = overlay_places.iter().filter(|(_, _, on_base)| *on_base).count();
    // 基础层与特效层都走客户端的 convert/dxt 自动路径；覆盖表里人工确认过的槽优先。
    let pm = PathMap::load(&root);
    let ov = load_overrides(&root);
    let con = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok();
    let base = plan_texture(&root, &db, pm.as_ref(), con.as_ref(), &ov, &base_name, 1024)
        .ok_or_else(|| format!("基础色 {base_name} 没解出来，先按单张图的老路显示"))?;
    let mut layers = vec![TextureLayer {
        face_start: 0,
        face_count: base_faces,
        blend: "opaque".into(),
        color: base,
        mask: None,
        slot: base_name,
    }];
    // 先排好「哪一段几何用哪一条材质」，再统一解码 PNG：位置与解码分开，读起来清楚。
    let mut placements: Vec<(usize, usize, LayerSpec)> = Vec::new();
    for (k, (fs, c, on_base)) in overlay_places.iter().enumerate() {
        let mut spec = overlays[k].clone();
        // 叠在同一段几何上的额外层只能当叠加：不透明的“第二层”会把基础色整片盖掉。
        if *on_base {
            spec.add = true;
        }
        placements.push((*fs, *c, spec));
    }
    let mut skipped_names: Vec<String> = Vec::new();
    let mut effect_layers = 0usize;
    let mut opaque_layers = 0usize;
    for (face_start, face_count, spec) in placements {
        let color_name = spec.color;
        let mask_name = spec.mask;
        let add = spec.add;
        let color = plan_texture(&root, &db, pm.as_ref(), con.as_ref(), &ov, &color_name, 512);
        let mask = mask_name
            .as_ref()
            .and_then(|m| plan_texture(&root, &db, pm.as_ref(), con.as_ref(), &ov, m, 512));
        if let Some(color) = color {
            if add {
                effect_layers += 1;
            } else {
                opaque_layers += 1;
            }
            layers.push(TextureLayer {
                face_start,
                face_count,
                blend: if add { "add".into() } else { "opaque".into() },
                color,
                mask,
                slot: color_name,
            });
        } else {
            // 点名：只报数量的话，人只知道「少了一段」，不知道是哪张图没解出来、
            // 该去哪一条槽位补候选（名字取自材质表原文，不改写）。
            skipped_names.push(color_name);
        }
    }
    let skipped = skipped_names.len();
    let mut note = format!("按材质表分层：基础层 {base_faces} 面");
    if effect_layers > 0 {
        note.push_str(&format!(" + 特效层 {effect_layers} 段"));
    }
    if opaque_layers > 0 {
        note.push_str(&format!(" + 不透明材质 {opaque_layers} 段"));
    }
    if extra > 0 {
        note.push_str(&format!("（其中 {extra} 段叠在基础子网格上）"));
    }
    if skipped > 0 {
        note.push_str(&skipped_note(&skipped_names));
    }
    // 把可核的那句话写进说明：对不对得上一眼能看出，不再笼统写「未单独人工确认」。
    note.push_str("；");
    note.push_str(&evidence_line(&evidence));
    if evidence.unpaired_masks > 0 {
        note.push_str(&format!("，{} 张遮罩没配上颜色层", evidence.unpaired_masks));
    }
    Ok(MeshTexturePlan {
        mesh: mesh_path,
        layers,
        slot_names,
        effect_layers,
        opaque_layers,
        face_counts: counts,
        evidence,
        note,
    })
}

/// 分层贴图：一只网格的多个子网格各用哪张贴图。失败时前端回退到单张「加载即贴」，
/// 绝不把一层的图盖到全部子网格上（2026-10-26 用户现场指出的错）。
#[tauri::command]
pub async fn mesh_texture_plan(
    app: State<'_, Arc<AppData>>,
    gid: i64,
    name: String,
    hash: Option<String>,
) -> Result<MeshTexturePlan, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || {
        mesh_texture_plan_sync(&app, gid, &name, hash.as_deref())
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 按网格路径取分层贴图计划：地图道具的网格不属于任何资产组（`amembers` 里只有同茎
/// `.mtl`），这里用同茎材质反查它所在的组，再走 `mesh_texture_plan` 同一条实现。
fn mesh_texture_plan_by_path_sync(app: &AppData, path: &str) -> Result<MeshTexturePlan, String> {
    let (_root, db) = crate::inspector::roots();
    let con = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| format!("资源清单打不开：{e}"))?;
    let stem = path
        .strip_suffix(".mesh")
        .or_else(|| path.strip_suffix(".MESH"))
        .unwrap_or(path);
    let mtl = format!("{stem}.mtl");
    let gid: i64 = con
        .query_row(
            "SELECT m.gid FROM amembers m JOIN resources r ON r.hash = m.hash \
             WHERE r.path = ?1 LIMIT 1",
            [&mtl],
            |r| r.get(0),
        )
        .map_err(|_| "这件网格旁边没有登记材质，取不到贴图".to_string())?;
    mesh_texture_plan_sync(app, gid, tail_of(path), None)
}

#[tauri::command]
pub async fn mesh_texture_plan_by_path(
    app: State<'_, Arc<AppData>>,
    path: String,
) -> Result<MeshTexturePlan, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || mesh_texture_plan_by_path_sync(&app, &path))
        .await
        .map_err(|e| e.to_string())?
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

    /// 只有批量引擎明确写 `error:"无 UV"` 的才算「无 UV」；缺 hash / 取不到字节 / 解析失败
    /// 都是清单或读取的问题，混进来会让界面把「缺文件」说成「缺 UV」。
    #[test]
    fn no_uv_only_counts_the_explicit_no_uv_error() {
        let root = std::env::temp_dir().join(format!("tlbb_nouv_{}", std::process::id()));
        let dir = root.join(".scratch/uvfit_batch/results");
        std::fs::create_dir_all(&dir).expect("建临时目录");
        std::fs::write(
            dir.join("a.json"),
            r#"{"mesh":"a.mesh","hasUv":false,"candidates":[],"error":"无 UV"}"#,
        )
        .expect("写 a");
        std::fs::write(
            dir.join("b.json"),
            r#"{"mesh":"b.mesh","hasUv":false,"candidates":[],"error":"清单里解析不到 hash"}"#,
        )
        .expect("写 b");
        std::fs::write(
            dir.join("c.json"),
            r#"{"mesh":"c.mesh","hasUv":true,"candidates":[]}"#,
        )
        .expect("写 c");
        let members = vec![
            ("mesh".to_string(), "a.mesh".to_string(), true),
            ("mesh".to_string(), "b.mesh".to_string(), true),
            ("mesh".to_string(), "c.mesh".to_string(), true),
        ];
        let got = load_no_uv_meshes(&root, &members);
        assert_eq!(got, vec!["a.mesh".to_string()], "缺 hash 不是无 UV");
        let _ = std::fs::remove_dir_all(&root);
    }

    /// `score = insideVar / (outsideVar + 4)`：岛外方差为 0 时这个比只剩「这张图自己有多忙」，
    /// 排不出归属。前端要靠这个数说话，所以「量出 0」和「旧缓存没量」必须是两个值。
    #[test]
    fn outside_var_distinguishes_zero_from_missing() {
        let v = value(
            r#"{"candidates":[
              {"hash":"cc00000000000001","w":512,"h":512,"codec":"BC3","mips":10,
               "insideVar":11529.8,"outsideVar":0.0,"score":2882.45},
              {"hash":"cc00000000000002","w":512,"h":512,"codec":"BC3","mips":10,
               "insideVar":900.0,"outsideVar":240.0,"score":3.2},
              {"hash":"cc00000000000003","w":512,"h":512,"codec":"BC3","mips":10,"score":90.0}
            ]}"#,
        );
        let got = parse_candidates(&v);
        assert_eq!(got[0].outside_var, Some(0.0), "岛外方差 0 要原样带出来");
        assert_eq!(got[1].outside_var, Some(240.0));
        assert_eq!(got[2].outside_var, None, "旧缓存没这个字段是「没量过」，不是 0");
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
    /// 「加载即贴」查询内核：真覆盖表、真 PathMap、真解码——设置后查得到、
    /// 撤销后查不到，键规则必须与 texture_override_set 一致（cfg 键优先）。
    /// 测试自清（set/clear 成对），覆盖表落盘保持零残留。
    #[test]
    fn mesh_override_png_follows_the_override_table() {
        let (root, db) = crate::inspector::roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端 pak 或资源清单");
            return;
        }
        // 拿批量缓存里第一个带候选的网格当真样本
        let dir = root.join(".scratch/uvfit_batch/results");
        let mut pick: Option<(String, String)> = None; // (stem, hash_hex)
        let Ok(rd) = std::fs::read_dir(&dir) else {
            eprintln!("跳过：没有 uvfit_batch/results 缓存");
            return;
        };
        for e in rd.flatten() {
            let p = e.path();
            if p.extension().and_then(|x| x.to_str()) != Some("json") {
                continue;
            }
            let Ok(raw) = std::fs::read(&p) else { continue };
            let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) else { continue };
            let Some(c0) = v.get("candidates").and_then(|x| x.as_array()).and_then(|a| a.first()) else { continue };
            let Some(h) = c0.get("hash").and_then(|x| x.as_str()) else { continue };
            let stem = p.file_stem().and_then(|x| x.to_str()).unwrap_or_default().to_string();
            pick = Some((stem, h.to_string()));
            break;
        }
        let Some((stem, hash_hex)) = pick else {
            eprintln!("跳过：批量缓存里没有带候选的网格");
            return;
        };
        let slot = format!("{stem}.tga");
        let cfg_path = tlbb_core::pathmap::PathMap::load(&root)
            .and_then(|pm| pm.lookup(&slot).map(String::from));

        // 没确认 → None
        let before = mesh_override_png_sync(&root, &db, &format!("{stem}.mesh")).expect("查询不该失败");
        assert!(before.is_none(), "{slot} 本来不该有覆盖，先清环境再跑这条测试");

        // 确认（走 texture_override_set 的真键规则）→ 查得到、hash 对得上
        texture_override_set(
            slot.clone(),
            cfg_path.clone(),
            hash_hex.clone(),
            "测试：加载即贴".into(),
            None,
        )
        .expect("写覆盖表不该失败");
        let hit = mesh_override_png_sync(&root, &db, &format!("{stem}.mesh")).expect("查询不该失败");
        let hit = match hit {
            Some(h) => h,
            None => {
                // 确认的贴图解不出图会 Err 而不是 None——落到这里说明键没对上，是 bug。
                texture_override_clear(slot.clone(), cfg_path.clone()).expect("清理");
                panic!("设置了覆盖却查不到：键规则不一致（slot={slot}，cfg={cfg_path:?}）");
            }
        };
        assert_eq!(hit.hash, hash_hex, "回包 hash 必须与覆盖表登记的一致");
        assert_eq!(hit.slot, slot);
        assert!(hit.png.starts_with("data:image/"), "回包该是 PNG data URL");

        // 撤销 → 落空（覆盖表零残留）
        texture_override_clear(slot.clone(), cfg_path.clone()).expect("撤销不该失败");
        let after = mesh_override_png_sync(&root, &db, &format!("{stem}.mesh")).expect("查询不该失败");
        assert!(after.is_none(), "撤销后还查得到，键没删干净");

        // 不是网格文件名 → 直接 None，不碰覆盖表
        assert!(mesh_override_png_sync(&root, &db, "随手一个字符串").expect("查询不该失败").is_none());

        // 槽名与网格名不同名：确认时写入 mesh 绑定，加载时按绑定找回（头发/衣服槽的修法）。
        // 用一只不存在的「测试网格」名，避免撞上真表里已有的绑定（如用户确认的头发）。
        let bound_slot = format!("{stem}_hair.tga");
        let bound_mesh = format!("{stem}_bind_test.mesh");
        let bound_cfg = tlbb_core::pathmap::PathMap::load(&root)
            .and_then(|pm| pm.lookup(&bound_slot).map(String::from));
        texture_override_set(
            bound_slot.clone(),
            bound_cfg.clone(),
            hash_hex.clone(),
            "测试：绑定网格".into(),
            Some(bound_mesh.clone()),
        )
        .expect("写绑定覆盖不该失败");
        let bound = mesh_override_png_sync(&root, &db, &bound_mesh)
            .expect("绑定后查询不该失败");
        assert!(bound.is_some(), "绑定到网格的非同名槽应能加载");
        assert_eq!(bound.unwrap().slot, bound_slot);
        texture_override_clear(bound_slot.clone(), bound_cfg.clone()).expect("清理绑定不该失败");
    }

    fn item(role: &str, name: &str) -> (String, String) {
        (role.to_string(), name.to_string())
    }

    /// 材质名在前或在后，贴图都要认领**离它最近**的那条材质：
    /// 普查 1,200 份里 907 份是「贴图 材质 着色器」，152 份是「材质 贴图 着色器」。
    #[test]
    fn texture_refs_claim_nearest_material_in_both_orders() {
        // 贴图在前（衣服实测顺序）
        let items = vec![
            item("贴图", "w1351_nan_s_yifu_xianfeng_001.tga"),
            item("材质", "data/sharematerial/material/skin/template_derfault_fashion.mtl"),
            item("着色器", "DynModelShader"),
            item("材质", "data/sharematerial/material/tran/template_default_effect_add_trans.mtl"),
            item("贴图", "w1351_mask_sz_nan_xf_c001.tga"),
            item("贴图", "w1351_texture_c013_01.tga"),
        ];
        let refs = texture_refs(&items);
        assert_eq!(refs.len(), 3, "pbr 不进来");
        assert!(!refs[0].add, "基础色认领 fashion 材质，不是叠加");
        assert!(refs[1].add, "遮罩认领最近的 effect_add_trans");
        assert!(refs[2].add, "颜色图认领最近的 effect_add_trans");

        // 材质名在前
        let items = vec![
            item("材质", "data/sharematerial/material/tran/template_default_effect_add_trans.mtl"),
            item("贴图", "w1351_texture_a.tga"),
        ];
        assert!(texture_refs(&items)[0].add, "材质名在前也认得到");
    }

    /// 衣服 `.mtl` 的贴图顺序：基础色、pbr、然后 4 组 mask+颜色。
    /// 分层计划必须把基础色单独拿出来、4 组按顺序留给 4 个特效子网格。
    #[test]
    fn layer_specs_pairs_mask_with_next_color() {
        let mut items = vec![
            item("贴图", "w1351_nan_s_yifu_xianfeng_001.tga"),
            item("贴图", "w1351_nan_s_yifu_xianfeng_001_pbr.tga"),
            item("材质", "data/sharematerial/material/skin/template_derfault_fashion.mtl"),
            item("材质", "data/sharematerial/material/tran/template_default_effect_add_trans.mtl"),
        ];
        for k in 1..=4 {
            items.push(item("贴图", &format!("w1351_mask_sz_nan_xf_c00{k}.tga")));
            items.push(item("贴图", &format!("w1351_texture_{k}.tga")));
        }
        let refs = texture_refs(&items);
        let (base, overlays) =
            layer_specs(&refs, "w1351_nan_s_yifu_xianfeng_001").expect("有基础色");
        assert_eq!(base.color, "w1351_nan_s_yifu_xianfeng_001.tga");
        assert!(!base.add, "基础层永远不透明");
        assert_eq!(overlays.len(), 4, "4 组 mask+颜色");
        for (k, o) in overlays.iter().enumerate() {
            let n = k + 1;
            assert_eq!(
                o.mask.as_deref(),
                Some(format!("w1351_mask_sz_nan_xf_c00{n}.tga").as_str())
            );
            assert_eq!(o.color, format!("w1351_texture_{n}.tga"));
            assert!(o.add, "effect_add_trans 下是叠加层");
        }
        assert!(
            !overlays.iter().any(|o| o.color.contains("_pbr")),
            "pbr 不是独立特效层"
        );
    }

    /// 头发槽名和网格名不同：没有同基础色，回退到第一张非 mask/pbr/point 的图。
    #[test]
    fn layer_specs_falls_back_when_stem_differs() {
        let refs = texture_refs(&[item("贴图", "w1351_nan_s_toufa_xianfeng_001.tga")]);
        let (base, overlays) =
            layer_specs(&refs, "w1351_model_xx_nan_jt_x02").expect("回退到第一张图");
        assert_eq!(base.color, "w1351_nan_s_toufa_xianfeng_001.tga");
        assert!(overlays.is_empty());
    }

    /// 第二材质（手套/鞋）没有 effect_add_trans：必须是不透明层，且它的 pbr 也不能
    /// 被当成颜色层。`w1351_cj_diao` 的实际顺序就是 yifu, yifu_pbr, 材质, 着色器,
    /// shoutao, shoutao_pbr。
    #[test]
    fn layer_specs_keeps_second_material_opaque() {
        let items = vec![
            item("贴图", "w1351_cj_diao_yifu.tga"),
            item("贴图", "w1351_cj_diao_yifu_pbr.tga"),
            item("材质", "data/sharematerial/material/skin/template_derfault_fashion.mtl"),
            item("着色器", "DynModelShader"),
            item("贴图", "w1351_cj_diao_shoutao.tga"),
            item("贴图", "w1351_cj_diao_shoutao_pbr.tga"),
        ];
        let refs = texture_refs(&items);
        let (base, overlays) = layer_specs(&refs, "w1351_cj_diao").expect("有基础色");
        assert_eq!(base.color, "w1351_cj_diao_yifu.tga");
        assert_eq!(overlays.len(), 1, "只留下手套颜色图");
        assert_eq!(overlays[0].color, "w1351_cj_diao_shoutao.tga");
        assert!(!overlays[0].add, "第二材质是不透明层");
        assert!(overlays[0].mask.is_none());
    }

    /// 衣服：5 段子网格、4 条特效 → 基础盖第 0 段，特效各占 1~4 段，不叠。
    #[test]
    fn plan_placements_one_per_submesh() {
        let counts = [4876u32, 989, 466, 2599, 1383];
        let p = plan_placements(&counts, 4);
        assert_eq!(p.len(), 4);
        assert_eq!(p[0], (4876, 989, false));
        assert_eq!(p[3], (4876 + 989 + 466 + 2599, 1383, false));
        assert!(!p.iter().any(|(_, _, on_base)| *on_base));
    }

    /// 单子网格 + 1 条额外层：叠在第 0 段上，且必须标成叠加（否则基础色被盖掉）。
    #[test]
    fn plan_placements_stacks_extra_on_base() {
        let p = plan_placements(&[476], 1);
        assert_eq!(p, vec![(0, 476, true)]);
    }

    /// 2 段子网格、2 条额外层：一条占第 1 段，多出来的一条叠在第 0 段。
    #[test]
    fn plan_placements_overflows_onto_base() {
        let p = plan_placements(&[100, 50], 2);
        assert_eq!(p, vec![(100, 50, false), (0, 100, true)]);
    }

    /// 叠加材质里多张颜色图、都没遮罩：第一张是模型自己的图，按不透明画。
    /// 证据：普查 12 例这种组合，第一张 12/12 只在单个模型出现，后续 11/12 是跨模型
    /// 共用图（`texture_lf012` 出现在 10 个模型）。照叠加画，旗子会整片透明。
    #[test]
    fn layer_specs_keeps_first_color_of_shared_effect_group_opaque() {
        let items = vec![
            item("贴图", "w1351_diancang_beimingshengong.tga"),
            item("材质", "data/sharematerial/material/skin/template_default_npc.mtl"),
            item("贴图", "w1351_model_bmsg_w001.tga"),
            item("贴图", "w1351_texture_lf012.tga"),
            item("材质", "data/sharematerial/material/tran/template_default_effect_add_trans.mtl"),
        ];
        let refs = texture_refs(&items);
        let (base, overlays) = layer_specs(&refs, "w1351_diancang_beimingshengong").expect("基础色");
        assert_eq!(base.color, "w1351_diancang_beimingshengong.tga");
        assert_eq!(overlays.len(), 2);
        assert_eq!(overlays[0].color, "w1351_model_bmsg_w001.tga");
        assert!(!overlays[0].add, "组里第一张是模型自己的图，不能当叠加");
        assert_eq!(overlays[1].color, "w1351_texture_lf012.tga");
        assert!(overlays[1].add, "共用光效图仍是叠加");

        // 带遮罩的（先锋衣服那种 mask+颜色 组合）不受影响：遮罩本身就是叠加证据。
        let items = vec![
            item("贴图", "w1351_nan_s_yifu_xianfeng_001.tga"),
            item("材质", "data/sharematerial/material/tran/template_default_effect_add_trans.mtl"),
            item("贴图", "w1351_mask_a.tga"),
            item("贴图", "w1351_tex_a.tga"),
            item("贴图", "w1351_mask_b.tga"),
            item("贴图", "w1351_tex_b.tga"),
        ];
        let refs = texture_refs(&items);
        let (_, overlays) = layer_specs(&refs, "w1351_nan_s_yifu_xianfeng_001").expect("基础色");
        assert!(overlays.iter().all(|o| o.add), "带遮罩的组合全是叠加层");
    }

    /// 落单 mask 没有颜色层就不画；落单的非 mask 图（如 point 光效）算无遮罩颜色层。
    #[test]
    fn layer_specs_drops_orphan_mask_but_keeps_standalone_color() {
        let items = vec![
            item("贴图", "s.tga"),
            item("材质", "x/template_default.mtl"),
            item("贴图", "w1351_point_z020.tga"),
            item("贴图", "w1351_mask_a.tga"),
            item("贴图", "w1351_texture_a.tga"),
            item("贴图", "w1351_mask_b.tga"),
        ];
        let refs = texture_refs(&items);
        let (base, overlays) = layer_specs(&refs, "s").expect("基础色");
        assert_eq!(base.color, "s.tga");
        assert_eq!(overlays.len(), 2, "point 图和 mask_a+texture_a 各一层");
        assert_eq!(overlays[0].color, "w1351_point_z020.tga");
        assert!(overlays[0].mask.is_none());
        assert_eq!(overlays[1].mask.as_deref(), Some("w1351_mask_a.tga"));
        assert_eq!(overlays[1].color, "w1351_texture_a.tga");
        assert!(
            !overlays.iter().any(|o| o.color == "w1351_mask_b.tga"),
            "落单遮罩不能当颜色"
        );
        let ev = layer_evidence(&[100, 50, 30], &refs, &overlays);
        assert_eq!(ev.color_layers, 3);
        assert_eq!(ev.submeshes, 3);
        assert!(ev.aligned, "三张颜色对三段");
        assert_eq!(ev.unpaired_masks, 1, "mask_b 落单要如实报");
    }

    /// 没解出来的层要点名（含超过 3 张时的收尾），名字取尾段不改写。
    #[test]
    fn skipped_note_names_the_missing_layers() {
        let n = skipped_note(&["data/source/x/w1351_zuoqi_wanli_a.tga".to_string()]);
        assert!(n.contains("1 段"), "{n}");
        assert!(n.contains("w1351_zuoqi_wanli_a.tga"), "要点名到文件名：{n}");
        assert!(!n.contains("data/source"), "只留尾段：{n}");
        let many: Vec<String> = (1..=5).map(|i| format!("texture_{i}.tga")).collect();
        let n = skipped_note(&many);
        assert!(n.contains("5 段"), "{n}");
        assert!(n.contains("等 5 张"), "超过 3 张要收尾：{n}");
        assert!(!n.contains("texture_4.tga"), "只列前 3 张：{n}");
    }

    /// 只有 pbr 的材质不是解析失败：那句话必须说清「着色器画、预览不了、保持灰模」，
    /// 不能写成「失败」让人以为程序坏了。
    #[test]
    fn no_color_note_explains_shader_only_materials() {
        let n = no_color_note(2, 1, 3);
        assert!(n.contains("pbr 贴图 2 张"), "要报张数：{n}");
        assert!(n.contains("遮罩 1 张"), "有遮罩也要报：{n}");
        assert!(n.contains("着色器"));
        assert!(n.contains("灰模"));
        assert!(!n.contains("失败"), "这不是失败：{n}");
        let n = no_color_note(1, 0, 1);
        assert!(!n.contains("遮罩"), "没有遮罩就别提：{n}");
        // 一张贴图都没有的（82/87 是这形状）：说「没有任何贴图」，不能提 pbr。
        let n = no_color_note(0, 0, 0);
        assert!(n.contains("没有任何贴图"), "{n}");
        assert!(!n.contains("pbr"), "没有 pbr 就别提 pbr：{n}");
        assert!(n.contains("灰模"));
    }

    /// 颜色层数和子网格数对不上时，证据必须说没验证——这是界面那句人话的来源。
    #[test]
    fn layer_evidence_flags_misalignment() {
        let refs = texture_refs(&[
            item("贴图", "a.tga"),
            item("贴图", "b.tga"),
            item("贴图", "c.tga"),
            item("贴图", "d.tga"),
        ]);
        let (_, overlays) = layer_specs(&refs, "a").expect("基础色");
        let ev = layer_evidence(&[10, 10, 10, 10, 10], &refs, &overlays);
        assert_eq!(ev.color_layers, 4);
        assert_eq!(ev.submeshes, 5);
        assert!(!ev.aligned);
        assert!(evidence_line(&ev).contains("未验证"), "人话里要写明没验证");
    }

    /// 榜首计数必须按**界面看到的顺序**（综合分降序）数，不是缓存里的方差比顺序。
    /// 数错口径 = 给错信息：方差比第一名往往正是那种「岛外无对比」的图。
    #[test]
    fn first_place_counts_follow_the_ui_ranking_not_cache_order() {
        let dir = std::env::temp_dir().join(format!("tlbb_first_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let res = dir.join(".scratch/uvfit_batch/results");
        std::fs::create_dir_all(&res).expect("建临时目录");
        let body = r#"{"mesh":"m.mesh","pool":10,"candidates":[
            {"hash":"aaaa000000000001","w":512,"h":512,"codec":"BC3","mips":10,"score":900.0,"adjustedScore":1.2,"outsideVar":0.0},
            {"hash":"aaaa000000000002","w":512,"h":512,"codec":"BC3","mips":10,"score":10.0,"adjustedScore":80.0,"outsideVar":3.0}]}"#;
        std::fs::write(res.join("m.json"), body).expect("写临时缓存");
        let m = scan_first_places(&dir);
        assert_eq!(m.get("aaaa000000000002"), Some(&1), "榜首要按综合分重排后的第一名数");
        assert_eq!(m.get("aaaa000000000001"), None, "方差比第一名不该被算成榜首");
        let _ = std::fs::remove_dir_all(&dir);
    }
}

/// UV 岛分布图：把这只网格的 UV 铺在 [0,1]² 的哪些格子上画成一张 256×256 的图
/// （亮 = 岛内，暗 = 岛外）。
///
/// 为什么值得占一个命令位：评分是「岛内方差 / (岛外方差 + 4)」，而覆盖率≈1 的网格
/// **岛外一个像素都没有**——这种榜的分数没有任何对比含义，光看「覆盖率 1.000」
/// 人感觉不到（实测 `w1351_model_fasheqi_h001` 铺满整张，榜首是一张山峰特效图）。
/// 画出来就看得见了。它不新造任何判断：mask 就是评分时算过的同一份。
/// 没有 UV、或清单里查不到这份网格 → 回 `None`（前端整块不出现，不摆空图）。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UvMapPng {
    pub png: String,
    pub coverage: f64,
    pub faces: usize,
}

#[tauri::command]
pub async fn uv_map_png(name: String) -> Result<Option<UvMapPng>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let (root, db) = crate::inspector::roots();
        let con = Connection::open_with_flags(
            &db,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(|e| format!("只读打开资源清单失败：{e}"))?;
        let tail = name
            .rsplit(['/', std::path::MAIN_SEPARATOR])
            .next()
            .unwrap_or(&name)
            .trim()
            .to_string();
        let file = if tail.to_ascii_lowercase().ends_with(".mesh") {
            tail
        } else {
            format!("{tail}.mesh")
        };
        let Some(hash) = tlbb_core::preview::mesh_hash(&con, &file) else {
            return Ok(None);
        };
        let (bytes, rtype) = fetch_raw(&root, &db, hash)?;
        if rtype != "mesh" && rtype != "geom" {
            return Err(format!("这个文件不是网格（它属于 {rtype} 那类），画不出 UV 岛"));
        }
        let Ok(geo) = tlbb_core::preview::parse_geometry(&bytes) else {
            return Ok(None);
        };
        if geo.uvs.is_empty() {
            return Ok(None); // 无 UV：本来就没有岛分布可画
        }
        let (mask, faces) = tlbb_core::preview::build_mask(&geo.uvs, &geo.indices);
        let cov_px = tlbb_core::preview::covered(&mask);
        let coverage = cov_px as f64 / (tlbb_core::preview::GRID * tlbb_core::preview::GRID) as f64;
        let png = tlbb_core::preview::mask_png(&mask)?;
        Ok(Some(UvMapPng {
            png: format!("data:image/png;base64,{}", crate::inspector::b64(&png)),
            coverage,
            faces,
        }))
    })
    .await
    .map_err(|e| e.to_string())?
}
