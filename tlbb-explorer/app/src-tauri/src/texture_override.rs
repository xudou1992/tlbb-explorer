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
    /// 256² PNG data URL，给「套上看看」直接包到模型上。
    pub png: String,
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
                png: c.get("png").and_then(|x| x.as_str()).unwrap_or_default().into(),
            });
        }
    }
    candidates
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
        let candidates = parse_candidates(&v);
        if candidates.is_empty() {
            continue;
        }
        out.push(TexCandGroup {
            mesh: name.clone(),
            pool: v.get("pool").and_then(|x| x.as_u64()).unwrap_or(0) as usize,
            state: "candidates".into(),
            source,
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

/// 批量榜单第 idx 名的候选 hash。文件不存在、解析失败、越界、空号都如实回
/// None——没有这张缩略图是事实，不是错误，前端保持占位就好。
fn batch_candidate_hash(root: &Path, mesh: &str, idx: usize) -> Option<String> {
    let stem = mesh.strip_suffix(".mesh").unwrap_or(mesh);
    let file = root
        .join(".scratch/uvfit_batch/results")
        .join(format!("{stem}.json"));
    let raw = std::fs::read(&file).ok()?;
    let v = serde_json::from_slice::<serde_json::Value>(&raw).ok()?;
    let h = v.get("candidates")?.as_array()?.get(idx)?;
    let h = h.get("hash")?.as_str()?.trim();
    if h.is_empty() {
        None
    } else {
        Some(h.to_string())
    }
}

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
/// 再按 (网格, 名次) 来要这一张——现解、缩到长边 256、PNG base64 data URL 回去。
/// 榜单读不到 / 名次越界回 Ok(None)，解码失败回 Err：两种都让前端保持占位，
/// 没有图就是没有图，不编造。
#[tauri::command]
pub async fn candidate_png(mesh: String, idx: usize) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let (root, db) = crate::inspector::roots();
        let Some(hash_hex) = batch_candidate_hash(&root, &mesh, idx) else {
            return Ok(None);
        };
        let hash = u64::from_str_radix(&hash_hex, 16)
            .map_err(|e| format!("候选编号 {hash_hex} 不是合法的 16 位编号：{e}"))?;
        decode_candidate_png(&root, &db, hash)
            .map(|(mime, bytes)| Some(format!("data:{mime};base64,{}", crate::inspector::b64(&bytes))))
    })
    .await
    .map_err(|e| e.to_string())?
}
