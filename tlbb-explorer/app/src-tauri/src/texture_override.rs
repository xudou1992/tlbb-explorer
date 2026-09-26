//! 贴图恢复系统 v1 · 步骤③⑤的数据层：候选榜单（uvfit 离线产出）+ 人工覆盖表。
//!
//! 纪律：原资源一个字节不动。覆盖表写在 `<root>/.scratch/model_texture_override.json`，
//! key 用 `cfg:<原始路径>`（90.8% 有）或 `bare:<裸名>`（其余），value 带确认的贴图 hash
//! 与时间——可撤销、可重评。候选全部是 🟡：uvfit 的分数是特征指标，不是归属结论；
//! 只有覆盖表里的才算 🟢。

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::json;

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

/// 读 uvfit 候选缓存：每组网格一份，找不到就是没有（🔴，不编造）。
pub fn load_candidate_groups(root: &Path, members: &[(String, String, bool)]) -> Vec<TexCandGroup> {
    let mut out = Vec::new();
    for (role, name, resolved) in members {
        if role != "mesh" || !resolved {
            continue;
        }
        let Some(stem) = name.strip_suffix(".mesh") else {
            continue;
        };
        let file = root.join(".scratch/texture_candidates").join(format!("{stem}.json"));
        let Ok(raw) = std::fs::read(&file) else {
            continue;
        };
        let Ok(v) = serde_json::from_slice::<serde_json::Value>(&raw) else {
            continue;
        };
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
        if candidates.is_empty() {
            continue;
        }
        out.push(TexCandGroup {
            mesh: name.clone(),
            pool: v.get("pool").and_then(|x| x.as_u64()).unwrap_or(0) as usize,
            state: "candidates".into(),
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
