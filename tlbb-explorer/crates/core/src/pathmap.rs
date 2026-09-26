//! `ResourcePath.cfg` — 引擎自带的「裸文件名 → 全路径」翻译表。
//!
//! 它是标准 JBCF 容器，但字符串表有 145,528 条字符串（= 2 × 72,764 对映射），
//! 超出 [`crate::jbcf::parse`] 的 `MAX_COUNT`（8192，按 .mtl/.mdl 的正常规模定的
//! 保守上限）——对 cfg 这是合法数据不是畸形，所以本模块用同一套语法、不设上限。
//!
//! 语法（2026-09-26 对着 10,853,872 字节的实文件逐字节核过）：
//!
//! ```text
//! [0]  'JBCF'  [8] v8  [12] bodyLen = 文件长-16
//! [16] 根 chunk id=86，size=2,619,524
//! [round8(size)+24] 字符串表 id=85：[size][flag][count][count×(u32 len,u32 hash)][chars]
//!                   表尾正好顶到文件尾（slack ≤ 3 字节）
//! ```
//!
//! 每对映射 = 两条相邻字符串：(裸文件名, 全路径)，如
//! `1351_boss_hadaba_shoutao_001.tga → data/source/npc/quest/w1351_boss_hadaba/texture/…`。
//! 材质里悬空的贴图名有 90.8% 能在这里找到出处；注意 cfg 只给「名字→路径」，
//! 源 tga 文件本身在打包时被剥离，运行时贴图在 pak 里重新编址（见
//! resolver_last_mile_20260926.md），所以查到路径 ≠ 拿到字节。

use std::collections::HashMap;
use std::fmt;
use std::path::Path;

use crate::jbcf::{round8, MAGIC, ROOT_ID, STRTABLE_ID};

const HDR: usize = 16;
/// 合理上限：实文件 145,528 条；翻 16 倍的余量只为拦住乱数据，不是语义边界。
const MAX_COUNT: u32 = 1 << 21;

#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    NotCfg,
    RootId(u32),
    NoStrtab,
    StrtabCount(u32),
    StrtabOverrun { chars: usize, need: usize, len: usize },
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::NotCfg => write!(f, "不是 ResourcePath.cfg（JBCF v8）负载"),
            Error::RootId(id) => write!(f, "根 chunk id {id}，应为 {ROOT_ID}"),
            Error::NoStrtab => write!(f, "找不到字符串表"),
            Error::StrtabCount(c) => write!(f, "字符串表条数 {c} 超出合理范围"),
            Error::StrtabOverrun { chars, need, len } => {
                write!(f, "字符串区越界：@{chars} 需要 {need} 字节，文件只有 {len}")
            }
        }
    }
}

impl std::error::Error for Error {}

/// 翻译表：裸文件名（大小写不敏感）→ 客户端原始全路径（保留原文拼写）。
#[derive(Debug)]
pub struct PathMap {
    map: HashMap<String, String>,
    pairs: usize,
}

impl PathMap {
    pub fn parse(raw: &[u8]) -> Result<PathMap, Error> {
        if raw.len() < HDR + 16 || raw[..4] != MAGIC {
            return Err(Error::NotCfg);
        }
        let a: Vec<u32> = (0..6)
            .map(|i| u32::from_le_bytes(raw[4 * i..4 * i + 4].try_into().unwrap()))
            .collect();
        if a[3] as usize + HDR != raw.len() {
            return Err(Error::NotCfg);
        }
        if a[4] != ROOT_ID {
            return Err(Error::RootId(a[4]));
        }
        // 表偏移先按公式（与 jbcf::parse 同款），失败再从尾部往回扫。
        let mut tried = vec![round8(a[5]).saturating_add(24) as usize];
        let lo = raw.len().saturating_sub(4_000_000).max(HDR + 16);
        tried.extend((lo..raw.len().saturating_sub(15)).rev().step_by(4));
        for off in tried {
            if let Some(pm) = try_strtab(raw, off) {
                return Ok(pm);
            }
        }
        Err(Error::NoStrtab)
    }

    /// 从客户端根目录定位并解析：根下的散装文件，或按引擎自己的 path_hash
    /// 从 pak 里提取（cfg 本体就是包内资源，hash = `path_hash("ResourcePath.cfg")`）。
    pub fn load(root: &Path) -> Option<PathMap> {
        if let Ok(raw) = std::fs::read(root.join("ResourcePath.cfg")) {
            return PathMap::parse(&raw).ok();
        }
        let want = crate::path_hash("ResourcePath.cfg");
        for name in pak_names(root) {
            let Ok(pak) = crate::jpak::Pak::open(&root.join(&name)) else {
                continue;
            };
            for rec in pak.records() {
                if rec.hash == want {
                    if let Ok(dec) = crate::payload::decode(&pak, &rec) {
                        if let Ok(pm) = PathMap::parse(&dec.bytes) {
                            return Some(pm);
                        }
                    }
                }
            }
        }
        None
    }

    /// 查裸文件名的原始出处。大小写不敏感（引擎的 path_hash 本身也对大小写不敏感）。
    pub fn lookup(&self, bare: &str) -> Option<&str> {
        self.map.get(&bare.to_ascii_lowercase()).map(|s| s.as_str())
    }

    /// 成功配对的映射条数。实文件为 72,764。
    pub fn pair_count(&self) -> usize {
        self.pairs
    }
}

fn try_strtab(raw: &[u8], off: usize) -> Option<PathMap> {
    if off < HDR + 16 || off + 16 > raw.len() {
        return None;
    }
    let hdr: Vec<u32> = (0..4)
        .map(|i| u32::from_le_bytes(raw[off + 4 * i..off + 4 * i + 4].try_into().unwrap()))
        .collect();
    let (id, _size, _flag, count) = (hdr[0], hdr[1], hdr[2], hdr[3]);
    if id != STRTABLE_ID || count == 0 || count > MAX_COUNT {
        return None;
    }
    let desc = off + 16;
    let chars = desc + 8 * count as usize;
    // 描述符区是交错 (len, hash)，这里只需要 len：stride 8 取第一个 u32。
    let mut total = 0usize;
    let mut lens = Vec::with_capacity(count as usize);
    for i in 0..count as usize {
        let l = u32::from_le_bytes(raw[desc + 8 * i..desc + 8 * i + 4].try_into().ok()?) as usize;
        if l > 4096 {
            return None;
        }
        total += l;
        lens.push(l);
    }
    if chars + total > raw.len() + 7 {
        return None;
    }
    let mut strings: Vec<&str> = Vec::with_capacity(count as usize);
    let mut p = chars;
    for l in lens {
        let end = (p + l).min(raw.len());
        strings.push(std::str::from_utf8(&raw[p..end]).unwrap_or(""));
        p += l;
    }
    let mut map = HashMap::with_capacity(count as usize / 2 + 1);
    let mut pairs = 0usize;
    let mut i = 0;
    while i + 1 < strings.len() {
        let (a, b) = (strings[i], strings[i + 1]);
        i += 2;
        // 方向判定：全路径侧含 '/'。两个都含或都不含的配对不收，照实少记。
        let (name, path) = if !a.contains('/') && b.contains('/') {
            (a, b)
        } else if !b.contains('/') && a.contains('/') {
            (b, a)
        } else {
            continue;
        };
        if name.is_empty() || path.is_empty() {
            continue;
        }
        pairs += 1;
        // 同名不同目录时后写的覆盖前写的：查询语义取最后一条，计数照实全记。
        map.insert(name.to_ascii_lowercase(), path.to_string());
    }
    Some(PathMap { map, pairs })
}

fn pak_names(root: &Path) -> Vec<String> {
    let mut out = Vec::new();
    if let Ok(rd) = std::fs::read_dir(root) {
        for e in rd.flatten() {
            let p = e.path();
            let is_pak = p
                .extension()
                .map(|x| x.eq_ignore_ascii_case("pak"))
                .unwrap_or(false);
            if is_pak {
                if let Some(n) = p.file_name().and_then(|s| s.to_str()) {
                    out.push(n.to_string());
                }
            }
        }
    }
    out.sort();
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 手搓一个最小 cfg 形状的 JBCF：2 对映射 + 1 对方向颠倒的干扰项不收。
    fn synthetic() -> Vec<u8> {
        let mut v = Vec::new();
        let strs: [&[u8]; 4] = [b"a.tga", b"data/x/a.tga", b"b.wav", b"data/sound/b.wav"];
        let count = strs.len() as u32;
        let strtab_size =
            8 + 8 * count + strs.iter().map(|s| s.len() as u32).sum::<u32>();
        let body: Vec<u8> = {
            let mut b = Vec::new();
            b.extend_from_slice(&86u32.to_le_bytes());
            b.extend_from_slice(&8u32.to_le_bytes()); // root size，round8=8
            b.extend_from_slice(&[0u8; 8]); // root body 占位
            b.extend_from_slice(&85u32.to_le_bytes());
            b.extend_from_slice(&strtab_size.to_le_bytes());
            b.extend_from_slice(&0u32.to_le_bytes());
            b.extend_from_slice(&count.to_le_bytes());
            for s in &strs {
                b.extend_from_slice(&(s.len() as u32).to_le_bytes());
                b.extend_from_slice(&0x1234u32.to_le_bytes());
            }
            for s in &strs {
                b.extend_from_slice(s);
            }
            b
        };
        v.extend_from_slice(b"JBCF");
        v.extend_from_slice(&0u32.to_le_bytes());
        v.extend_from_slice(&8u32.to_le_bytes());
        v.extend_from_slice(&((body.len()) as u32).to_le_bytes());
        v.extend_from_slice(&body);
        v
    }

    #[test]
    fn parses_synthetic_and_looks_up_case_insensitively() {
        let pm = PathMap::parse(&synthetic()).expect("解析应成功");
        assert_eq!(pm.pair_count(), 2);
        assert_eq!(pm.lookup("a.tga"), Some("data/x/a.tga"));
        assert_eq!(pm.lookup("A.TGA"), Some("data/x/a.tga"));
        assert_eq!(pm.lookup("b.wav"), Some("data/sound/b.wav"));
        assert_eq!(pm.lookup("missing.dds"), None);
    }

    #[test]
    fn rejects_non_cfg() {
        assert!(matches!(
            PathMap::parse(b"not a cfg at all........"),
            Err(Error::NotCfg)
        ));
    }

    /// 真文件测试：有客户端（TLBB_ROOT 指向 D:\TLGL 这类根）才跑，否则跳过。
    #[test]
    fn real_cfg_matches_shipped_facts() {
        let Ok(root) = std::env::var("TLBB_ROOT") else {
            return;
        };
        let root = Path::new(&root);
        let raw = std::fs::read(root.join(".scratch/out/tree/ResourcePath.cfg"))
            .or_else(|_| std::fs::read(root.join("ResourcePath.cfg")));
        let Ok(raw) = raw else { return };
        let pm = PathMap::parse(&raw).expect("实文件应能解析");
        assert_eq!(pm.pair_count(), 72_764, "发货事实：72,764 对映射");
        let hit = pm
            .lookup("1351_boss_hadaba_shoutao_001.tga")
            .expect("样例应命中");
        assert!(
            hit.contains("w1351_boss_hadaba") && hit.ends_with("1351_boss_hadaba_shoutao_001.tga"),
            "样例路径应有语义目录：{hit}"
        );
    }
}
