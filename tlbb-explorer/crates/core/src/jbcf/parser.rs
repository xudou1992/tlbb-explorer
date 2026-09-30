//! `JBCF` (`BinaryConfigFile`) — the container behind `.mtl` / `.mdl` / `.ske` / `.sfl`.
//!
//! Grammar recovered from the client (`sub_1409C6A10` validates the magic and reads the
//! string table; `sub_14060CB90` walks chunks):
//!
//! ```text
//! [0]  'JBCF'   [4] 0   [8] 8   [12] bodyLen (= file size - 16)
//! [16] root chunk: u32 id == 86, u32 size at +4
//! string table at round8(root.size) + 24:
//!   [u32 id == 85][u32 size][u32 flag][u32 count][count * (u32 len, u32 hash)][chars]
//! ```
//!
//! The string table is the payload that matters: material bodies list their parent
//! material, their shader class and their texture names in the clear, so this is where
//! the dependency graph comes from — not from filename guessing.

use std::fmt;

pub const MAGIC: [u8; 4] = *b"JBCF";
pub const ROOT_ID: u32 = 86;
pub const STRTABLE_ID: u32 = 85;
const HDR: usize = 16;
const MAX_COUNT: u32 = 8192;

#[derive(Debug, PartialEq, Eq)]
pub enum Error {
    NotJbcf,
    BodyLen { declared: u32, len: usize },
    RootId(u32),
    NoStrtab,
    StrtabId(u32),
    StrtabCount(u32),
    StrtabSize { size: u32, area: i64, total: usize },
    StrtabTail,
    StrtabChars,
    Truncated,
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::NotJbcf => write!(f, "not a JBCF payload"),
            Error::BodyLen { declared, len } => {
                write!(f, "bodyLen {declared} != {len} - {HDR}")
            }
            Error::RootId(id) => write!(f, "root chunk id {id}, expected {ROOT_ID}"),
            Error::NoStrtab => write!(f, "no string table"),
            Error::StrtabId(id) => write!(f, "string table id {id}"),
            Error::StrtabCount(c) => write!(f, "string table count {c}"),
            Error::StrtabSize { size, area, total } => {
                write!(f, "string table size {size} area {area} total {total}")
            }
            Error::StrtabTail => write!(f, "string table tail"),
            Error::StrtabChars => write!(f, "string table contains control characters"),
            Error::Truncated => write!(f, "truncated"),
        }
    }
}

impl std::error::Error for Error {}

#[derive(Debug, Clone)]
pub struct Str {
    pub text: String,
    /// Per-string 32-bit id. Stable across files and builds (0 collisions in 11,993
    /// samples) but its function is unidentified; treat it as an opaque key.
    pub hash: u32,
}

#[derive(Debug, Clone)]
pub struct Jbcf {
    pub body_len: u32,
    pub root_size: u32,
    pub strtab_at: usize,
    pub flag: u32,
    pub strings: Vec<Str>,
}

/// Round up to the next multiple of 8; chunks in a JBCF are 8-aligned.
pub const fn round8(n: u32) -> u32 {
    if n & 7 == 0 {
        n
    } else {
        // 畸形头部里 n 可以大到 0xFFFFFFF8，`n + 8 - (n & 7)` 会溢出：
        // debug 直接 panic，release 静默回绕成一个错偏移。
        n.saturating_add(8 - (n & 7))
    }
}

/// Chunk offset formula: the string table directly follows the 8-aligned root chunk.
pub fn predicted_strtab(raw: &[u8]) -> Option<usize> {
    let root_size = u32::from_le_bytes(raw.get(20..24)?.try_into().ok()?);
    Some(round8(root_size).saturating_add(24) as usize)
}

pub fn parse(raw: &[u8]) -> Result<Jbcf, Error> {
    if raw.len() < 24 || raw[..4] != MAGIC {
        return Err(Error::NotJbcf);
    }
    let a: Vec<u32> = (0..6)
        .map(|i| u32::from_le_bytes(raw[4 * i..4 * i + 4].try_into().unwrap()))
        .collect();
    if a[3] as usize + HDR != raw.len() {
        return Err(Error::BodyLen {
            declared: a[3],
            len: raw.len(),
        });
    }
    if a[4] != ROOT_ID {
        return Err(Error::RootId(a[4]));
    }
    // Try the formula, then fall back to a bounded backward scan: the table is the last
    // chunk, so its header sits within the tail window.
    let mut tried = Vec::new();
    if let Some(p) = predicted_strtab(raw) {
        tried.push(p);
    }
    let lo = raw.len().saturating_sub(200_000).max(HDR + 16);
    tried.extend((lo..raw.len().saturating_sub(15)).rev().step_by(4));
    for off in tried {
        if let Ok((flag, strings)) = read_strtab(raw, off) {
            return Ok(Jbcf {
                body_len: a[3],
                root_size: a[5],
                strtab_at: off,
                flag,
                strings,
            });
        }
    }
    Err(Error::NoStrtab)
}

fn read_strtab(raw: &[u8], off: usize) -> Result<(u32, Vec<Str>), Error> {
    if off < HDR + 16 || off + 16 > raw.len() {
        return Err(Error::Truncated);
    }
    let hdr: Vec<u32> = (0..4)
        .map(|i| u32::from_le_bytes(raw[off + 4 * i..off + 4 * i + 4].try_into().unwrap()))
        .collect();
    let (id, size, flag, count) = (hdr[0], hdr[1], hdr[2], hdr[3]);
    if id != STRTABLE_ID {
        return Err(Error::StrtabId(id));
    }
    if count > MAX_COUNT || off + 16 + 8 * count as usize > raw.len() {
        return Err(Error::StrtabCount(count));
    }
    let mut lens = Vec::with_capacity(count as usize);
    for i in 0..count as usize {
        let at = off + 16 + 8 * i;
        lens.push((
            u32::from_le_bytes(raw[at..at + 4].try_into().unwrap()),
            u32::from_le_bytes(raw[at + 4..at + 8].try_into().unwrap()),
        ));
    }
    let total: usize = lens.iter().map(|(l, _)| *l as usize).sum();
    // `size` covers everything after the size field itself, and the character area is
    // allowed trailing alignment slack — requiring exactness here rejects valid files.
    let area = size as i64 - 8 - 8 * count as i64;
    if area < total as i64 || off + 8 + size as usize > raw.len() + 8 {
        return Err(Error::StrtabSize {
            size,
            area,
            total,
        });
    }
    let chars = off + 16 + 8 * count as usize;
    if raw.len().saturating_sub(chars + total) > 7 {
        return Err(Error::StrtabTail);
    }
    let mut out = Vec::with_capacity(count as usize);
    let mut p = chars;
    for (len, hash) in lens {
        let end = p + len as usize;
        if end > raw.len() {
            return Err(Error::Truncated);
        }
        let s = &raw[p..end];
        if s.iter().any(|c| *c < 9 || (14..32).contains(c)) {
            return Err(Error::StrtabChars);
        }
        out.push(Str {
            text: decode_str(s),
            hash,
        });
        p = end;
    }
    Ok((flag, out))
}

/// 字符串表是 **GBK**（客户端跑在中文 Windows 上）。按 UTF-8 硬解会把
/// 「龙头01.tga」损成两个替换符——材质页上就是一排 `◆◆`。先按 UTF-8 试
/// （纯 ASCII 名字两边都合法，走快路），试不通再按 GBK，两边都不通才留替换符。
fn decode_str(bytes: &[u8]) -> String {
    if let Ok(s) = std::str::from_utf8(bytes) {
        return s.to_string();
    }
    let (cow, _, bad) = encoding_rs::GBK.decode(bytes);
    if !bad {
        return cow.into_owned();
    }
    String::from_utf8_lossy(bytes).into_owned()
}

/// Extensions the material/model graph actually uses.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    Texture,
    Material,
    Model,
    Skeleton,
    Animation,
    Scene,
    Shader,
    Other,
}

pub fn role(name: &str) -> Role {
    let low = name.rsplit('.').next().unwrap_or("").to_ascii_lowercase();
    match low.as_str() {
        "tga" | "dds" | "png" | "jpg" | "bmp" => Role::Texture,
        "mtl" => Role::Material,
        "mdl" => Role::Model,
        "ske" => Role::Skeleton,
        "ani" => Role::Animation,
        "scene" | "map" => Role::Scene,
        _ if name.to_ascii_lowercase().contains("shader") => Role::Shader,
        _ => Role::Other,
    }
}

#[cfg(test)]
mod decode_tests {
    use super::decode_str;

    /// 字符串表是 GBK（客户端跑在中文 Windows 上）：`龙头01.tga` 的字节是
    /// `C1FA CDB7 30 31 2E 74 67 61`。按 UTF-8 硬解会掉两个替换符——
    /// 材质页上就是一排 `◆◆`，那是把客户端原文写坏了。
    #[test]
    fn gbk_bytes_decode_to_chinese() {
        let raw = b"\xC1\xFA\xCD\xB7\x30\x31\x2E\x74\x67\x61";
        let s = decode_str(raw);
        assert_eq!(s, "龙头01.tga", "GBK 名字解错了：{s}");
        assert!(!s.contains('\u{FFFD}'), "还留着替换符：{s}");
    }

    /// 纯 ASCII 走 UTF-8 快路，不许被 GBK 通道改动。
    #[test]
    fn ascii_names_are_untouched() {
        assert_eq!(decode_str(b"template_default.mtl"), "template_default.mtl");
    }

    /// 两边都不像的字节：留替换符但不 panic（这是「读不出来」的兜底，不是猜）。
    /// 顺带记一条实测：GBK 会把单字节 ASCII 当尾字节吃掉，所以这条不许断言
    /// 「尾巴还在」——只断言不炸、且真的吐出了东西。
    #[test]
    fn undecodable_bytes_do_not_panic() {
        let s = decode_str(b"\xFF\xFE\xFD tail");
        assert!(!s.is_empty(), "解不出来也要回一个串，不能让界面空白");
    }
}
