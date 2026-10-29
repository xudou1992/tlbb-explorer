//! 只读 sidecar 身份表：`.scratch/cfg_named_sidecar.json`（4,780 条 hash→cfg 路径）。
//!
//! 这些条目在包里但没有写进 `resources.db` 的 `path` 列。按用户 2026-10-26 的选择，
//! 界面以**只读覆盖**的方式使用它们（不动 resources.db），并在模型上标明来源。
//! 变体组的网格（`_b2.mesh` 一类，共 468 个）靠这张表才能定位。

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Hit {
    pub hash: u64,
    pub path: String,
}

struct Index {
    by_name: HashMap<String, Hit>,
}

static INDEX: OnceLock<Option<Index>> = OnceLock::new();

pub fn path_of(root: &Path) -> PathBuf {
    std::env::var("TLBB_SIDECAR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/cfg_named_sidecar.json"))
}

/// 只认 `16 位十六进制 → 含 '/' 的路径`；坏行跳过，不猜。
pub fn parse(raw: &[u8]) -> Option<(HashMap<String, Hit>, usize)> {
    let map: HashMap<String, String> = serde_json::from_slice(raw).ok()?;
    let mut by_name = HashMap::with_capacity(map.len());
    let mut count = 0usize;
    for (h, p) in map {
        let h = h.trim();
        if h.len() != 16 || !h.chars().all(|c| c.is_ascii_hexdigit()) || !p.contains('/') {
            continue;
        }
        let Ok(hash) = u64::from_str_radix(h, 16) else {
            continue;
        };
        let name = p.rsplit('/').next().unwrap_or(&p).to_ascii_lowercase();
        if name.is_empty() {
            continue;
        }
        by_name.insert(name, Hit { hash, path: p });
        count += 1;
    }
    Some((by_name, count))
}

fn index(root: &Path) -> Option<&'static Index> {
    INDEX
        .get_or_init(|| {
            let raw = std::fs::read(path_of(root)).ok()?;
            let (by_name, _count) = parse(&raw)?;
            Some(Index { by_name })
        })
        .as_ref()
}

/// 按裸文件名（大小写不敏感）查 sidecar 身份。
pub fn lookup(root: &Path, name: &str) -> Option<Hit> {
    let key = name.rsplit('/').next().unwrap_or(name).to_ascii_lowercase();
    index(root)?.by_name.get(&key).cloned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_keeps_only_valid_hex_path_pairs() {
        let raw = br#"{
            "29bdb434e161b308": "data/source/npc/quest/w1351_pets_longgui_b0/w1351_pets_longgui_b2.mesh",
            "not-a-hash": "data/x.mesh",
            "1111111111111111": "no-slash.mesh",
            "2222222222222222": "data/y/w1351_pets_qiongqi_b2.mesh"
        }"#;
        let (map, n) = parse(raw).expect("合法 JSON");
        assert_eq!(n, 2);
        assert_eq!(
            map.get("w1351_pets_longgui_b2.mesh"),
            Some(&Hit {
                hash: 0x29bdb434e161b308,
                path: "data/source/npc/quest/w1351_pets_longgui_b0/w1351_pets_longgui_b2.mesh".into()
            })
        );
        assert_eq!(map.get("w1351_pets_qiongqi_b2.mesh").map(|h| h.hash), Some(0x2222222222222222));
        assert!(!map.contains_key("x.mesh"));
        assert!(!map.contains_key("no-slash.mesh"));
    }

    #[test]
    fn parse_rejects_non_object() {
        assert!(parse(b"[]").is_none());
        assert!(parse(b"not json").is_none());
    }
}
