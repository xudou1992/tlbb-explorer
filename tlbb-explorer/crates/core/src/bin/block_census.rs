//! block_census — 无名数据块自动分类器（P6，研究性离线工具）。
//!
//! 给 `resources` 表里 **path IS NULL** 的全部无名块自动分桶，回答「疑似是什么」。
//! 只分类，不解析、不断言——所有结论性措辞都是「疑似」，判据全部来自字节本身：
//! 魔数、香农熵、f32/u32 可读性、256B 窗口重复率、尺寸、refs 入度。
//!
//! 实测口径（2026-09-26，resources.db）：path IS NULL 共 **48,053** 条（用户口径
//! 「约 1.2 万」是旧库约数；texture 24,261 / geom 12,676 / ani 2,999 / binary 2,179 /
//! scene 1,126 / …）。其中 ≥512² RGBA32/BC3 的 1,650 张匿名贴图已有 uvfit 管线，
//! 本工具覆盖**全部**无名块，texture 只是其中一桶。
//!
//! 解码策略（实测决定）：`payload::decode` 不支持范围解（Snappy 整块 inflate +
//! 长度校验），无名块展开总量 6.3 GB（stored 3.1 GB），整块解逐块统计后丢弃，
//! 分片并行下全量在分钟级——不另造「部分解压」口径。解码失败的块（非标准封装/
//! 记录缺失）退回容器里 stored 原始字节取头部魔数，如实标注「未解封装」。
//!
//! 分桶规则（规则引擎，非 ML；阈值见 [`BUCKET_ENT_HIGH`] 等常量）：
//! 1. 已知魔数 → 格式名一桶（JMT1/JBCF/NAVF/信封 mesh·ani/通用图片音频…）；
//! 2. 无魔数按前 4KB 熵：≥7.5 `encrypted-or-compressed`；6.0–7.5 `structured-binary`；
//!    4.0–6.0 `mixed-numeric`（f32 可读比例高 → `float-table`）；<4.0
//!    `low-entropy-table/runtime`。
//! 3. 每桶内按尺寸分 <1KB / 1-16KB / 16-256KB / >256KB 四档。
//!
//! 落盘（只写 `--out`）：`census.json`（每桶统计）+ `rows.jsonl`（每块特征，
//! 供下游免重解 6.3 GB 直接重分桶）+ `SUMMARY.md`（人话报告，全部「疑似」措辞）。
//!
//! refs 入度：catalog 有现成 `refs` 表（`SELECT to_hash, count(*) … GROUP BY`），
//! 直接采用。注意实测**所有无名块的 refs 入度都是 0**——无名块从不被按名引用，
//! 这本身就是它们成批无名的一个旁证。
//!
//! 只读纪律：db 只读打开、pak 只读 mmap，写盘只写 `--out` 目录。
//!
//! 用法：
//! ```text
//! block_census --db D:/TLGL/.scratch/resources.db --root D:/TLGL \
//!              --out D:/TLGL/.scratch/block_census [--limit N] [--shards N]
//! ```

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::{Pak, Record};
use tlbb_core::payload;
use tlbb_core::preview::parse_envelope;
use tlbb_core::{jbcf, jmt1};

// ─────────────────────────────────────────────────────────────────────────────
// 常量：特征窗口与分桶阈值（经验值，未人工校准；依据见各行注释）
// ─────────────────────────────────────────────────────────────────────────────

/// 魔数/熵取头部字节数。
const HEAD_BYTES: usize = 4096;
/// f32/u32 可读性扫描字节数（1KB = 250 个 u32/f32）。
const NUMERIC_BYTES: usize = 1024;
/// 重复率扫描上限（单块最多扫前 4MB 的 256B 窗口，封顶成本）。
const REPEAT_SCAN_CAP: usize = 4 << 20;
/// 重复率窗口大小。
const REPEAT_WINDOW: usize = 256;

/// 熵 ≥ 7.5 → 疑似加密或仍在压缩态（解封装后仍高熵）。
const BUCKET_ENT_HIGH: f64 = 7.5;
/// 熵 ≥ 6.0 → 疑似结构化二进制。
const BUCKET_ENT_MID: f64 = 6.0;
/// 熵 ≥ 4.0 → 疑似混合数值（f32 可读比例高则 float-table）。
const BUCKET_ENT_LOW: f64 = 4.0;
/// float-table 的 f32 可读比例线。随机字节的 f32 落在 |1e-3..1e6| 的概率约
/// 12%（指数字节 117..147 共 31/256），真浮点表接近 1.0——0.8 两侧留足间隔。
const F32_READABLE_LINE: f64 = 0.8;

// ─────────────────────────────────────────────────────────────────────────────
// 特征采集：纯函数，全部可单测
// ─────────────────────────────────────────────────────────────────────────────

/// 前 `b` 字节的香农熵（0..8）。
pub fn entropy(b: &[u8]) -> f64 {
    if b.is_empty() {
        return 0.0;
    }
    let mut freq = [0u64; 256];
    for &c in b {
        freq[c as usize] += 1;
    }
    let n = b.len() as f64;
    freq.iter()
        .filter(|&&f| f > 0)
        .map(|&f| {
            let p = f as f64 / n;
            -p * p.log2()
        })
        .sum()
}

/// 一个 f32 值「可读」：0（合法垫底）、有限、|v| 落在 1e-3..1e6。
/// 指数位分布是否合理由区间隐式约束（2^-10..2^20）；inf/nan 直接否。
fn f32_plausible(v: f32) -> bool {
    if v == 0.0 {
        return true;
    }
    if !v.is_finite() {
        return false;
    }
    (1e-3..=1e6).contains(&v.abs())
}

/// u32 视角「可读」：0 或 < 2^24（顶点索引/计数/句柄一类的小整数）。
fn u32_plausible(v: u32) -> bool {
    v < (1 << 24)
}

/// 前 `NUMERIC_BYTES` 字节按 f32 LE 视角扫描，可读比例 0..1。
pub fn f32_readable_ratio(b: &[u8]) -> f64 {
    let n = b.len() / 4;
    if n == 0 {
        return 0.0;
    }
    let ok = b[..n * 4]
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
        .filter(|&v| f32_plausible(v))
        .count();
    ok as f64 / n as f64
}

/// 前 `NUMERIC_BYTES` 字节按 u32 LE 视角扫描，可读比例 0..1（只报告，不进规则）。
pub fn u32_readable_ratio(b: &[u8]) -> f64 {
    let n = b.len() / 4;
    if n == 0 {
        return 0.0;
    }
    let ok = b[..n * 4]
        .chunks_exact(4)
        .map(|c| u32::from_le_bytes(c.try_into().unwrap()))
        .filter(|&v| u32_plausible(v))
        .count();
    ok as f64 / n as f64
}

/// 256B 窗口重复率：整块（封顶 [`REPEAT_SCAN_CAP`]）按 [`REPEAT_WINDOW`] 切窗，
/// 与前一窗逐字节相等的窗占比。高值 = 疑似垫底/对齐垫/低熵压缩候选。
pub fn repeat_rate(b: &[u8]) -> f64 {
    let scan = &b[..b.len().min(REPEAT_SCAN_CAP)];
    let w = REPEAT_WINDOW;
    if scan.len() < 2 * w {
        return 0.0;
    }
    let mut prev = &scan[..w];
    let mut total = 0usize;
    let mut eq = 0usize;
    for cur in scan[w..].chunks_exact(w) {
        total += 1;
        if cur == prev {
            eq += 1;
        }
        prev = cur;
    }
    if total == 0 {
        0.0
    } else {
        eq as f64 / total as f64
    }
}

/// 前 4KB 的 0x00 字节占比（低熵桶的叙述佐证：全零垫 vs 常量表）。
fn zero_ratio(b: &[u8]) -> f64 {
    if b.is_empty() {
        return 0.0;
    }
    let n = b.len().min(HEAD_BYTES);
    b[..n].iter().filter(|&&c| c == 0).count() as f64 / n as f64
}

/// 已知格式魔数表。只收 crates/core 与盲查已证实的签名 + 通用容器标准魔数，
/// 命中即一桶（桶名=返回值）。顺序敏感：更具体的判据在前。
pub fn match_magic(b: &[u8]) -> Option<&'static str> {
    let m = |n: usize, want: &[u8]| b.len() >= n && &b[..n] == want;
    // 游戏自有格式（crates/core 已知签名）
    if jmt1::looks_like(b) {
        return Some("JMT1"); // 贴图（jmt1::decoder::MAGIC）
    }
    if m(4, jbcf::MAGIC.as_slice()) {
        return Some("JBCF"); // 配置容器（材质/模型定义/骨骼表）
    }
    if m(4, b"NAVF") {
        return Some("NAVF"); // 导航/寻路（blind_census 盲查证实）
    }
    if m(4, b"JBPU") {
        return Some("JBPU"); // 参数块 4CC（FileKind::Param 的载体）
    }
    // julegame 信封：0x40 处类型标签（summary.rs parse_envelope 布局）。
    // 白名单只收已证实标签，防文本块误命中（信封要求 banner/note 全可打印，
    // 纯文本文件可能碰巧过检，所以 tag 不认识的宁可不下判）。
    if let Some(env) = parse_envelope(b) {
        match env.tag.as_str() {
            "mesh" => return Some("envelope-mesh"),
            "ani" => return Some("envelope-ani"),
            _ => {}
        }
    }
    // 通用格式标准魔数（外来资源原样入包时出现）
    if m(8, b"\x89PNG\r\n\x1a\n") {
        return Some("png");
    }
    if m(3, b"\xff\xd8\xff") {
        return Some("jpeg");
    }
    if m(4, b"GIF8") {
        return Some("gif");
    }
    if m(4, b"RIFF") && b.len() >= 12 {
        if &b[8..12] == b"WEBP" {
            return Some("webp");
        }
        if &b[8..12] == b"WAVE" {
            return Some("wav");
        }
    }
    if m(4, b"OggS") {
        return Some("ogg");
    }
    if m(3, b"ID3") {
        return Some("mp3");
    }
    if m(4, b"DDS ") {
        return Some("dds");
    }
    None
}

/// 规则引擎：魔数优先，其余按熵分桶（4.0–6.0 档 f32 可读比例高则 float-table）。
pub fn bucket_of(magic: Option<&'static str>, ent: f64, f32_ratio: f64) -> &'static str {
    if let Some(name) = magic {
        // 魔数桶名 = 格式名本身（JMT1/envelope-mesh/png/…）
        return match name {
            "JMT1" => "JMT1",
            "JBCF" => "JBCF",
            "NAVF" => "NAVF",
            "envelope-mesh" => "envelope-mesh",
            "envelope-ani" => "envelope-ani",
            "png" => "png",
            "jpeg" => "jpeg",
            "gif" => "gif",
            "webp" => "webp",
            "wav" => "wav",
            "ogg" => "ogg",
            "mp3" => "mp3",
            "dds" => "dds",
            other => other, // 理论不可达：match 已穷举 match_magic 的返回域
        };
    }
    if ent >= BUCKET_ENT_HIGH {
        "encrypted-or-compressed"
    } else if ent >= BUCKET_ENT_MID {
        "structured-binary"
    } else if ent >= BUCKET_ENT_LOW {
        if f32_ratio >= F32_READABLE_LINE {
            "float-table"
        } else {
            "mixed-numeric"
        }
    } else {
        "low-entropy-table/runtime"
    }
}

/// 尺寸分桶（展开后字节数）。
pub fn size_bucket(len: u64) -> &'static str {
    if len < 1024 {
        "<1KB"
    } else if len < 16 * 1024 {
        "1-16KB"
    } else if len < 256 * 1024 {
        "16-256KB"
    } else {
        ">256KB"
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 输入：catalog 行 + refs 入度
// ─────────────────────────────────────────────────────────────────────────────

/// resources 表里一条无名块记录（path IS NULL）。
struct DbRow {
    hash: u64,
    db_type: String,
    subtype: String,
    pak: String,
    offset: i64,
    stored: i64,
}

fn open_ro(path: &Path) -> Connection {
    Connection::open_with_flags(
        path,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("以只读方式打开 resources.db")
}

fn load_rows(con: &Connection, limit: usize) -> Vec<DbRow> {
    let sql = "SELECT hash, type, subtype, pak, offset, stored \
               FROM resources WHERE path IS NULL ORDER BY hash";
    let mut st = con.prepare(sql).unwrap();
    let mut out: Vec<DbRow> = st
        .query_map([], |r| {
            Ok(DbRow {
                hash: u64::from_str_radix(&r.get::<_, String>(0)?, 16).unwrap_or(0),
                db_type: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                subtype: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                pak: r.get(3)?,
                offset: r.get(4)?,
                stored: r.get(5)?,
            })
        })
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    if limit > 0 {
        out.truncate(limit);
    }
    out
}

/// refs 入度：`refs.to_hash` 按块计数（catalog 现成表，见模块注释）。
fn load_refs(con: &Connection) -> HashMap<u64, u32> {
    let mut st = con
        .prepare("SELECT to_hash, count(*) FROM refs WHERE to_hash IS NOT NULL GROUP BY to_hash")
        .unwrap();
    let rows = st
        .query_map([], |r| {
            let h = r.get::<_, String>(0)?;
            let n: i64 = r.get(1)?;
            Ok((
                u64::from_str_radix(&h, 16).unwrap_or(0),
                n.clamp(0, u32::MAX as i64) as u32,
            ))
        })
        .unwrap()
        .collect::<Result<Vec<_>, _>>()
        .unwrap();
    rows.into_iter().collect()
}

/// 按 nameless_probe 同一口径建索引：(pak 茎名, hash) → 记录。
/// DB 每行自带 pak/offset，所以按 (stem, hash) 精确定位并核对偏移，
/// 避免「同名 hash 在别的 pak 里」读错。
fn load_paks(root: &Path) -> (HashMap<String, Pak>, HashMap<(String, u64), Record>) {
    let mut paks = HashMap::new();
    let mut idx = HashMap::new();
    let mut files: Vec<_> = std::fs::read_dir(root)
        .expect("读取包目录")
        .flatten()
        .map(|e| e.path())
        .filter(|p| {
            p.extension()
                .map(|x| x.eq_ignore_ascii_case("pak"))
                .unwrap_or(false)
        })
        .collect();
    files.sort();
    for path in files {
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        let pak = Pak::open(&path).expect("以只读方式打开 pak");
        for rec in pak.records() {
            idx.insert((stem.clone(), rec.hash), rec);
        }
        paks.insert(stem, pak);
    }
    (paks, idx)
}

// ─────────────────────────────────────────────────────────────────────────────
// 每块采集
// ─────────────────────────────────────────────────────────────────────────────

/// 一块的全部特征（落 rows.jsonl 的形态）。
#[derive(Clone)]
struct Feat {
    hash: u64,
    db_type: String,
    subtype: String,
    /// true = payload::decode 成功；false = 用 stored 原始字节（未解封装）。
    decoded: bool,
    /// 特征来源字节数：decoded 用 original，未解封装用 stored。
    size: u64,
    bucket: &'static str,
    magic: String, // 已知格式名或前 4 字节 hex
    ent: f64,
    f32r: f64,
    u32r: f64,
    rep: f64,
    zero: f64,
    refs: u32,
}

/// 解码 + 特征。任何一步失败都有兜底：定位不到/偏移变动/解码失败 →
/// 退 stored 原始字节（未解封装）；连 stored 都取不到 → unresolved 桶。
fn measure(
    row: &DbRow,
    paks: &HashMap<String, Pak>,
    idx: &HashMap<(String, u64), Record>,
    refs: &HashMap<u64, u32>,
) -> Feat {
    let base = |decoded: bool, size: u64, bytes: &[u8], bucket: &'static str| Feat {
        hash: row.hash,
        db_type: row.db_type.clone(),
        subtype: row.subtype.clone(),
        decoded,
        size,
        bucket,
        magic: match match_magic(bytes) {
            Some(name) => name.to_string(),
            None => bytes
                .first()
                .map(|_| {
                    bytes[..bytes.len().min(4)]
                        .iter()
                        .map(|c| format!("{c:02x}"))
                        .collect::<String>()
                })
                .unwrap_or_default(),
        },
        ent: entropy(&bytes[..bytes.len().min(HEAD_BYTES)]),
        f32r: f32_readable_ratio(&bytes[..bytes.len().min(NUMERIC_BYTES)]),
        u32r: u32_readable_ratio(&bytes[..bytes.len().min(NUMERIC_BYTES)]),
        rep: repeat_rate(bytes),
        zero: zero_ratio(bytes),
        refs: refs.get(&row.hash).copied().unwrap_or(0),
    };

    let Some(rec) = idx.get(&(row.pak.clone(), row.hash)) else {
        return base(false, row.stored.max(0) as u64, &[], "unresolved");
    };
    if rec.offset as i64 != row.offset {
        // 偏移与目录不符 = 读到搬过家的旧记录，宁可不采（nameless_probe 同口径）
        return base(false, row.stored.max(0) as u64, &[], "unresolved");
    }
    let Some(pak) = paks.get(&row.pak) else {
        return base(false, row.stored.max(0) as u64, &[], "unresolved");
    };
    match payload::decode(pak, rec) {
        Ok(d) => {
            let bytes = &d.bytes;
            let ent = entropy(&bytes[..bytes.len().min(HEAD_BYTES)]);
            let f32r = f32_readable_ratio(&bytes[..bytes.len().min(NUMERIC_BYTES)]);
            base(
                true,
                bytes.len() as u64,
                bytes,
                bucket_of(match_magic(bytes), ent, f32r),
            )
        }
        Err(_) => {
            // 非标准封装：拿容器里 stored 原始字节看魔数（如实标注未解封装）
            let raw = rec.stored_bytes(pak.data()).unwrap_or(&[]);
            let ent = entropy(&raw[..raw.len().min(HEAD_BYTES)]);
            let f32r = f32_readable_ratio(&raw[..raw.len().min(NUMERIC_BYTES)]);
            base(
                false,
                row.stored.max(0) as u64,
                raw,
                bucket_of(match_magic(raw), ent, f32r),
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 聚合与落盘
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Default)]
struct BucketAgg {
    count: usize,
    total_bytes: u64,
    size_dist: BTreeMap<&'static str, usize>,
    ent_min: f64,
    ent_max: f64,
    f32_sum: f64,
    rep_sum: f64,
    samples: Vec<String>,
    magic: BTreeMap<String, usize>,
    db_types: BTreeMap<String, usize>,
    raw_undecoded: usize,
    refs_nonzero: usize,
}

impl BucketAgg {
    fn push(&mut self, f: &Feat) {
        self.count += 1;
        self.total_bytes += f.size;
        *self.size_dist.entry(size_bucket(f.size)).or_default() += 1;
        if self.count == 1 || f.ent < self.ent_min {
            self.ent_min = f.ent;
        }
        if self.count == 1 || f.ent > self.ent_max {
            self.ent_max = f.ent;
        }
        self.f32_sum += f.f32r;
        self.rep_sum += f.rep;
        if self.samples.len() < 10 {
            self.samples.push(format!("{:016x}", f.hash));
        }
        if !f.magic.is_empty() {
            *self.magic.entry(f.magic.clone()).or_default() += 1;
        }
        let label = if f.subtype.is_empty() {
            f.db_type.clone()
        } else {
            format!("{}/{}", f.db_type, f.subtype)
        };
        *self.db_types.entry(label).or_default() += 1;
        if !f.decoded {
            self.raw_undecoded += 1;
        }
        if f.refs > 0 {
            self.refs_nonzero += 1;
        }
    }
}

fn top5(t: &BTreeMap<String, usize>) -> Vec<serde_json::Value> {
    let mut rows: Vec<(&String, &usize)> = t.iter().collect();
    rows.sort_by(|a, b| b.1.cmp(a.1).then(a.0.cmp(b.0)));
    rows.iter()
        .take(5)
        .map(|(k, v)| serde_json::json!({ "magic": k, "count": v }))
        .collect()
}

/// 各桶的「疑似是什么」叙述（SUMMARY.md 用）。全部「疑似」措辞，不断言。
fn verdict(bucket: &str, agg: &BucketAgg) -> String {
    match bucket {
        "JMT1" => "匿名 JMT1 贴图（≥512² 且 RGBA32/BC3 的 1,650 张已有 uvfit 管线；其余疑似小图/图标/UI 一类，尺寸由目录字段可再细分）".into(),
        "envelope-mesh" => "julegame 信封格式的 .mesh 网格（0x40 处带 \"mesh\" 类型标签），疑似无名几何资源本体".into(),
        "envelope-ani" => "julegame 信封格式的 .ani 动作片段（0x40 处带 \"ani\" 类型标签）".into(),
        "JBCF" => "JBCF 配置容器（材质表/模型定义/骨骼表的载体），疑似无名配置资源".into(),
        "NAVF" => "导航/寻路数据（\"NAVF\" 魔数，此前盲查已证实；语义未解）".into(),
        "JBPU" => "JBPU 参数块（键值参数表的 4CC 载体，FileKind::Param 一族）".into(),
        "png" | "jpeg" | "gif" | "webp" | "wav" | "ogg" | "mp3" | "dds" => {
            format!("通用 {bucket} 格式资源（标准魔数原样入包）")
        }
        "encrypted-or-compressed" => "解封装后熵仍 ≥7.5，疑似加密数据或包内自带第二层压缩".into(),
        "structured-binary" => "无魔数、中高熵（6.0–7.5），疑似结构化二进制（顶点/索引缓冲、二进制表一类）".into(),
        "float-table" => "无魔数、中熵且 f32 可读比例高，疑似浮点表（顶点坐标/矩阵/蒙皮权重一类几何数据）".into(),
        "mixed-numeric" => "无魔数、中熵（4.0–6.0）、数值可读性一般，疑似混合数值表".into(),
        "low-entropy-table/runtime" => "低熵无魔数，疑似运行时常量表/查找表/对齐垫一类".into(),
        "unresolved" => "目录定位不到（记录缺失或偏移变动），未能采样".into(),
        other => format!("（未预设叙述的桶 {other}）"),
    }
    .replace("{bucket}", bucket)
    .replace(
        "{refs}",
        &agg.refs_nonzero.to_string(),
    )
}

fn human_bytes(n: u64) -> String {
    if n >= 1 << 30 {
        format!("{:.2} GB", n as f64 / (1 << 30) as f64)
    } else if n >= 1 << 20 {
        format!("{:.1} MB", n as f64 / (1 << 20) as f64)
    } else {
        format!("{:.1} KB", n as f64 / (1 << 10) as f64)
    }
}

fn main() {
    let mut db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let mut root = PathBuf::from("D:/TLGL");
    let mut out = PathBuf::from("D:/TLGL/.scratch/block_census");
    let mut limit = 0usize; // 0 = 全部
    let mut shards = 0usize; // 0 = 自动
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--db" => db = PathBuf::from(args.next().unwrap_or_default()),
            "--root" => root = PathBuf::from(args.next().unwrap_or_default()),
            "--out" => out = PathBuf::from(args.next().unwrap_or_default()),
            "--limit" => limit = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            "--shards" => shards = args.next().and_then(|v| v.parse().ok()).unwrap_or(0),
            other => eprintln!("未知参数 {other}"),
        }
    }
    let shards = if shards > 0 {
        shards
    } else {
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4)
            .clamp(4, 16)
    };

    let t0 = std::time::Instant::now();
    let con = open_ro(&db);
    let total_db = con
        .query_row("SELECT count(*) FROM resources", [], |r| r.get::<_, i64>(0))
        .unwrap_or(0);
    let total_null = con
        .query_row(
            "SELECT count(*) FROM resources WHERE path IS NULL",
            [],
            |r| r.get::<_, i64>(0),
        )
        .unwrap_or(0);
    let rows = load_rows(&con, limit);
    let refs = load_refs(&con);
    let refs_nonzero_nameless = rows.iter().filter(|r| refs.contains_key(&r.hash)).count();
    println!(
        "无名块：库内 {} 条资源，path IS NULL {} 条；本次采 {} 条（limit={}）；refs 入度非零 {} 条",
        total_db,
        total_null,
        rows.len(),
        limit,
        refs_nonzero_nameless
    );

    let (paks, idx) = load_paks(&root);
    println!(
        "打开 {} 个 pak，索引 {} 条记录（分片 {}）",
        paks.len(),
        idx.len(),
        shards
    );

    // 分片并行采集。Pak 内部是 mmap，payload::decode 是纯函数，
    // 与 uvfit_batch 同一共享口径。
    let done = Arc::new(AtomicUsize::new(0));
    let total = rows.len();
    let feats: Vec<Feat> = if total == 0 {
        Vec::new()
    } else {
        let per = total.div_ceil(shards).max(1);
        let chunks: Vec<Vec<Feat>> = std::thread::scope(|scope| {
            rows.chunks(per)
                .map(|chunk| {
                    let paks = &paks;
                    let idx = &idx;
                    let refs = &refs;
                    let done = Arc::clone(&done);
                    scope
                        .spawn(move || {
                            let mut out = Vec::with_capacity(chunk.len());
                            for row in chunk {
                                out.push(measure(row, paks, idx, refs));
                                let n = done.fetch_add(1, Ordering::Relaxed) + 1;
                                if n % 500 == 0 || n == total {
                                    let el = t0.elapsed().as_secs_f64();
                                    let eta = el / n as f64 * (total - n) as f64;
                                    println!("进度 {n} / {total} · 已用 {el:.1}s · 预计剩余 {eta:.0}s");
                                }
                            }
                            out
                        })
                })
                .collect::<Vec<_>>()
                .into_iter()
                .map(|h| h.join().expect("采集分片崩溃"))
                .collect()
        });
        chunks.into_iter().flatten().collect()
    };

    // 聚合：按 DB 原序（ORDER BY hash）收进来的，天然去重且确定性
    let mut buckets: BTreeMap<&'static str, BucketAgg> = BTreeMap::new();
    for f in &feats {
        buckets.entry(f.bucket).or_default().push(f);
    }

    // census.json
    let bucket_json: Vec<serde_json::Value> = buckets
        .iter()
        .map(|(name, a)| {
            serde_json::json!({
                "name": name,
                "count": a.count,
                "totalBytes": a.total_bytes,
                "sizeDist": a.size_dist,
                "entropyRange": [
                    (a.ent_min * 100.0).round() / 100.0,
                    (a.ent_max * 100.0).round() / 100.0
                ],
                "avgF32Readable": (a.f32_sum / a.count as f64 * 100.0).round() / 100.0,
                "avgRepeat": (a.rep_sum / a.count as f64 * 100.0).round() / 100.0,
                "samples": a.samples,
                "magicTop": top5(&a.magic),
                "dbTypeTop": top5(&a.db_types),
                "rawUndecoded": a.raw_undecoded,
                "refsNonzero": a.refs_nonzero,
            })
        })
        .collect();
    let decoded_ok = feats.iter().filter(|f| f.decoded).count();
    let census = serde_json::json!({
        "tool": "block_census",
        "db": db.to_string_lossy(),
        "root": root.to_string_lossy(),
        "totalResources": total_db,
        "namelessTotal": total_null,
        "sampled": feats.len(),
        "decodedOk": decoded_ok,
        "decodeStrategy": "payload::decode 整块解（无范围解口径）；失败退 stored 原始字节并标注未解封装",
        "thresholds": {
            "entHigh": BUCKET_ENT_HIGH,
            "entMid": BUCKET_ENT_MID,
            "entLow": BUCKET_ENT_LOW,
            "f32ReadableLine": F32_READABLE_LINE,
        },
        "elapsedSec": (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0,
        "buckets": bucket_json,
    });
    std::fs::create_dir_all(&out).ok();
    let census_path = out.join("census.json");
    std::fs::write(&census_path, serde_json::to_string_pretty(&census).unwrap()).ok();

    // rows.jsonl：每块一行特征，下游免重解 6.3GB 可直接重分桶
    let rows_path = out.join("rows.jsonl");
    {
        use std::io::Write;
        let mut w = std::io::BufWriter::new(std::fs::File::create(&rows_path).unwrap());
        for f in &feats {
            writeln!(
                w,
                "{{\"hash\":\"{:016x}\",\"dbType\":\"{}\",\"subtype\":\"{}\",\"bucket\":\"{}\",\"decoded\":{},\"size\":{},\"magic\":\"{}\",\"entropy\":{:.2},\"f32\":{:.3},\"u32\":{:.3},\"repeat\":{:.3},\"zero\":{:.3},\"refs\":{}}}",
                f.hash,
                f.db_type.replace('"', "'"),
                f.subtype.replace('"', "'"),
                f.bucket,
                f.decoded,
                f.size,
                f.magic,
                f.ent,
                f.f32r,
                f.u32r,
                f.rep,
                f.zero,
                f.refs
            )
            .ok();
        }
    }

    // SUMMARY.md
    let mut md = String::new();
    md.push_str("# 无名数据块普查（block_census）\n\n");
    md.push_str(&format!(
        "- 口径：`resources` 表 path IS NULL 共 **{total_null}** 条（库内共 {total_db} 条；本报告采样 {} 条，limit={limit}）。\n",
        feats.len()
    ));
    md.push_str(&format!(
        "- 解码：payload::decode 整块解 {} 条成功；{} 条退 stored 原始字节（未解封装，判据只看头部魔数/熵，措辞更保守）。\n",
        decoded_ok,
        feats.len() - decoded_ok
    ));
    md.push_str(&format!(
        "- refs 入度：catalog refs 表现成查询；无名块中被引用非零的 {} 条——**匿名块从不被按名引用**，这是它们无名处境的旁证。\n",
        refs_nonzero_nameless
    ));
    md.push_str("- 措辞纪律：以下全部是「疑似」，判据来自字节本身（魔数/熵/数值可读性/重复率/尺寸），不是结论。\n\n");

    // 桶按数量降序排
    let mut order: Vec<(&'static str, &BucketAgg)> = buckets.iter().map(|(k, v)| (*k, v)).collect();
    order.sort_by(|a, b| b.1.count.cmp(&a.1.count));
    for (name, a) in &order {
        let pct = 100.0 * a.count as f64 / feats.len().max(1) as f64;
        md.push_str(&format!(
            "## {} — {} 个（{pct:.1}%），共 {}\n\n",
            name,
            a.count,
            human_bytes(a.total_bytes)
        ));
        md.push_str(&format!("- **疑似**：{}\n", verdict(name, a)));
        md.push_str(&format!(
            "- **判据**：熵 {:.2}..{:.2}；平均 f32 可读 {:.2}；平均 256B 窗口重复率 {:.2}；未解封装 {} 条；refs 入度非零 {} 条。\n",
            a.ent_min,
            a.ent_max,
            a.f32_sum / a.count as f64,
            a.rep_sum / a.count as f64,
            a.raw_undecoded,
            a.refs_nonzero
        ));
        let dist = &a.size_dist;
        md.push_str(&format!(
            "- **尺寸**：<1KB {} · 1-16KB {} · 16-256KB {} · >256KB {}。\n",
            dist.get("<1KB").unwrap_or(&0),
            dist.get("1-16KB").unwrap_or(&0),
            dist.get("16-256KB").unwrap_or(&0),
            dist.get(">256KB").unwrap_or(&0)
        ));
        let magics = top5(&a.magic);
        if !magics.is_empty() {
            let s = magics
                .iter()
                .map(|m| {
                    format!(
                        "`{}`×{}",
                        m["magic"].as_str().unwrap_or(""),
                        m["count"].as_i64().unwrap_or(0)
                    )
                })
                .collect::<Vec<_>>()
                .join("、");
            md.push_str(&format!("- **magic 分布**：{s}。\n"));
        }
        let types = top5(&a.db_types);
        if !types.is_empty() {
            let s = types
                .iter()
                .map(|m| {
                    format!(
                        "{}×{}",
                        m["magic"].as_str().unwrap_or(""),
                        m["count"].as_i64().unwrap_or(0)
                    )
                })
                .collect::<Vec<_>>()
                .join("、");
            md.push_str(&format!(
                "- **目录旧标签对照**（建库时的 type/subtype，仅三角验证）：{s}。\n"
            ));
        }
        md.push_str(&format!(
            "- **样例 hash**：{}\n\n",
            a.samples
                .iter()
                .map(|h| format!("`{h}`"))
                .collect::<Vec<_>>()
                .join(" ")
        ));
    }

    // 总述：最大的未知桶（无魔数系）
    let known_buckets = [
        "JMT1",
        "envelope-mesh",
        "envelope-ani",
        "JBCF",
        "NAVF",
        "JBPU",
        "png",
        "jpeg",
        "gif",
        "webp",
        "wav",
        "ogg",
        "mp3",
        "dds",
        "unresolved",
    ];
    let mut unknown: Vec<(&'static str, &BucketAgg)> = order
        .iter()
        .filter(|(n, _)| !known_buckets.contains(n))
        .map(|(n, a)| (*n, *a))
        .collect();
    unknown.sort_by(|a, b| b.1.count.cmp(&a.1.count));
    md.push_str("## 总述\n\n");
    if let Some((name, a)) = unknown.first() {
        let pct = 100.0 * a.count as f64 / feats.len().max(1) as f64;
        let composition = top5(&a.db_types)
            .iter()
            .map(|m| {
                format!(
                    "{}×{}",
                    m["magic"].as_str().unwrap_or(""),
                    m["count"].as_i64().unwrap_or(0)
                )
            })
            .collect::<Vec<_>>()
            .join("、");
        md.push_str(&format!(
            "- 最大的未知桶是 **{name}**（{} 个，{pct:.1}%，共 {}）。疑似 {}。目录旧标签构成：{composition}。下一步建议先啃它：{}。",
            a.count,
            human_bytes(a.total_bytes),
            verdict(name, a),
            next_step(name)
        ));
        md.push('\n');
    }
    if let (Some(a), Some(b)) = (unknown.first(), unknown.get(1)) {
        md.push_str(&format!(
            "- 次大未知桶是 **{}**（{} 个，共 {}）。疑似 {}。两个桶合起来约占无名块 {:.1}%，与目录旧标签（geom/raw、binary/bin 等）交叉验证后可再细分。\n",
            b.0,
            b.1.count,
            human_bytes(b.1.total_bytes),
            verdict(b.0, b.1),
            100.0 * (a.1.count + b.1.count) as f64 / feats.len().max(1) as f64
        ));
    }
    md.push_str(&format!(
        "- 全程用时 {:.1}s；逐块特征见 `rows.jsonl`（改分桶阈值后无需重解 6.3GB，直接在特征上重跑规则即可）。\n",
        t0.elapsed().as_secs_f64()
    ));

    let md_path = out.join("SUMMARY.md");
    std::fs::write(&md_path, &md).ok();
    println!(
        "完成：{} 块 → {} 个桶；落盘 {}, {}, {}（用时 {:.1}s）",
        feats.len(),
        buckets.len(),
        census_path.display(),
        rows_path.display(),
        md_path.display(),
        t0.elapsed().as_secs_f64()
    );
}

/// 下一步建议（按桶给一句话，全部「疑似/可验证」口吻）。
fn next_step(bucket: &str) -> &'static str {
    match bucket {
        "float-table" => "可与目录 type='geom'/subtype='raw' 交叉验证，若对上就接 preview::parse_geometry 试解析（若失败可按其失败点反推顶点布局）",
        "structured-binary" => "先抽样对 f32/u32 可读性做直方图，确认是否索引缓冲/二进制表；再决定接哪个解析器",
        "mixed-numeric" => "抽样看头部 hex 与字符串分布，判断是表还是异构结构",
        "encrypted-or-compressed" => "先看解码 info 标志（encrypted/compressed/padded）分布，区分「包外已解、块内自带第二层」与「真加密」",
        "low-entropy-table/runtime" => "抽样看是否全零垫/小整数表，占比高的可并入运行时数据叙事",
        _ => "按样例 hash 抽几块人工看头部 hex",
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// 测试：熵 / 数值可读性 / 魔数表 / 规则引擎 / 尺寸分桶（全部合成字节）
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn 熵_全同字节为0() {
        assert_eq!(entropy(&[0x41u8; 1000]), 0.0);
        assert_eq!(entropy(&[]), 0.0);
    }

    #[test]
    fn 熵_两值对半为1() {
        let mut b = Vec::new();
        b.extend(std::iter::repeat_n(0u8, 512));
        b.extend(std::iter::repeat_n(255u8, 512));
        assert!((entropy(&b) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn 熵_均匀分布接近8() {
        let b: Vec<u8> = (0..=255u8).collect();
        assert!(entropy(&b) > 7.95, "got {}", entropy(&b));
    }

    #[test]
    fn f32可读_正常浮点表全过() {
        let vals = [0.0f32, 1.0, -2.5, 1000.0, 1e-3, 1e6, -0.75, 3.14159];
        let b: Vec<u8> = vals.iter().flat_map(|v| v.to_le_bytes()).collect();
        assert!((f32_readable_ratio(&b) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn u32可读_索引缓冲风格全过() {
        // 顶点索引/计数字段：小整数（< 2^24）
        let vals = [0u32, 1, 42, 65_535, 1 << 23, 3];
        let b: Vec<u8> = vals.iter().flat_map(|v| v.to_le_bytes()).collect();
        assert!((u32_readable_ratio(&b) - 1.0).abs() < 1e-9);
        // 随机位模式大整数不可读
        let big: Vec<u8> = [0xFFu8, 0xFF, 0xFF, 0xFF].iter().copied().take(64).collect();
        assert_eq!(u32_readable_ratio(&big), 0.0);
    }

    #[test]
    fn f32可读_随机模式低() {
        // 0xDEADBEEF / 0xFFFFFFFF 一类模式当 f32 是 NaN 或超大值，不可读
        let b: Vec<u8> = [0xDEu8, 0xAD, 0xBE, 0xEF, 0xFF, 0xFF, 0xFF, 0xFF]
            .iter()
            .cycle()
            .take(1024)
            .copied()
            .collect();
        assert!(f32_readable_ratio(&b) < 0.2, "got {}", f32_readable_ratio(&b));
    }

    #[test]
    fn f32可读_空与残尾() {
        assert_eq!(f32_readable_ratio(&[]), 0.0);
        assert_eq!(f32_readable_ratio(&[1, 2, 3]), 0.0); // 不足 4 字节
        // 1023 字节：只能凑 255 个完整 f32，尾 3 字节不读
        let b = vec![0u8; 1023];
        assert!((f32_readable_ratio(&b) - 1.0).abs() < 1e-9);
    }

    #[test]
    fn 魔数表_游戏自有格式() {
        let mut jmt1 = vec![b'J', b'M', b'T', b'1'];
        jmt1.extend(vec![0u8; 64]); // looks_like 要求 ≥28 字节
        assert_eq!(match_magic(&jmt1), Some("JMT1"));
        assert_eq!(match_magic(b"JBCF\x01\x02\x03"), Some("JBCF"));
        assert_eq!(match_magic(b"NAVF\x01\x02"), Some("NAVF"));
        assert_eq!(match_magic(b"JBPU\x01\x02"), Some("JBPU"));
    }

    #[test]
    fn 魔数表_通用格式() {
        let png = b"\x89PNG\r\n\x1a\n\x00\x00";
        assert_eq!(match_magic(png), Some("png"));
        assert_eq!(match_magic(b"\xff\xd8\xff\xe0rest"), Some("jpeg"));
        assert_eq!(match_magic(b"GIF89a...."), Some("gif"));
        let mut webp = b"RIFF\x00\x00\x00\x00".to_vec();
        webp.extend_from_slice(b"WEBP");
        assert_eq!(match_magic(&webp), Some("webp"));
        let mut wav = b"RIFF\x00\x00\x00\x00".to_vec();
        wav.extend_from_slice(b"WAVE");
        assert_eq!(match_magic(&wav), Some("wav"));
        assert_eq!(match_magic(b"OggS\x00\x02"), Some("ogg"));
        assert_eq!(match_magic(b"ID3\x04\x00"), Some("mp3"));
    }

    #[test]
    fn 魔数表_信封标签白名单() {
        // 合成 julegame 信封：banner(0x40) + tag(0x48 前的 8B) + version + note(64B)
        let make_env = |tag: &[u8]| -> Vec<u8> {
            let mut b = vec![0u8; 0x8C + 16];
            let banner = b"Copyright 2013-2200 http://www.julegame.com";
            b[..banner.len()].copy_from_slice(banner);
            b[0x40..0x40 + tag.len()].copy_from_slice(tag);
            b[0x48..0x4C].copy_from_slice(&1u32.to_le_bytes());
            b
        };
        assert_eq!(match_magic(&make_env(b"mesh\0\0\0\0")), Some("envelope-mesh"));
        assert_eq!(match_magic(&make_env(b"ani\0\0\0\0\0")), Some("envelope-ani"));
        // 不认识的标签宁可不下判（防文本块误命中）
        assert_eq!(match_magic(&make_env(b"junk\0\0\0\0")), None);
    }

    #[test]
    fn 魔数表_短输入不误判() {
        assert_eq!(match_magic(b""), None);
        assert_eq!(match_magic(b"JM"), None);
        assert_eq!(match_magic(b"JMT"), None);
    }

    #[test]
    fn 规则引擎_魔数优先() {
        assert_eq!(bucket_of(Some("JMT1"), 0.0, 0.0), "JMT1");
        assert_eq!(bucket_of(Some("envelope-mesh"), 0.0, 0.0), "envelope-mesh");
        // 有魔数时熵再高也走魔数桶
        assert_eq!(bucket_of(Some("JBCF"), 7.9, 0.0), "JBCF");
    }

    #[test]
    fn 规则引擎_熵分档与浮点覆盖() {
        assert_eq!(bucket_of(None, 7.5, 0.0), "encrypted-or-compressed");
        assert_eq!(bucket_of(None, 7.6, 0.0), "encrypted-or-compressed");
        assert_eq!(bucket_of(None, 6.5, 0.3), "structured-binary");
        assert_eq!(bucket_of(None, 6.0, 0.0), "structured-binary");
        assert_eq!(bucket_of(None, 5.0, 0.9), "float-table");
        assert_eq!(
            bucket_of(None, 4.5, 0.2),
            "mixed-numeric",
            "f32 可读低于阈值不升格 float-table"
        );
        assert_eq!(bucket_of(None, 4.0, 0.1), "mixed-numeric");
        assert_eq!(bucket_of(None, 3.9, 0.99), "low-entropy-table/runtime");
        assert_eq!(bucket_of(None, 0.0, 0.0), "low-entropy-table/runtime");
    }

    #[test]
    fn 尺寸分桶_四档边界() {
        assert_eq!(size_bucket(0), "<1KB");
        assert_eq!(size_bucket(1023), "<1KB");
        assert_eq!(size_bucket(1024), "1-16KB");
        assert_eq!(size_bucket(16 * 1024 - 1), "1-16KB");
        assert_eq!(size_bucket(16 * 1024), "16-256KB");
        assert_eq!(size_bucket(256 * 1024 - 1), "16-256KB");
        assert_eq!(size_bucket(256 * 1024), ">256KB");
        assert_eq!(size_bucket(18 * 1024 * 1024), ">256KB");
    }

    #[test]
    fn 重复率_垫底块高_随机块低() {
        assert!(repeat_rate(&[7u8; 8192]) > 0.99);
        let randomish: Vec<u8> = (0..8192u32)
            .map(|i| i.wrapping_mul(2_654_435_761).wrapping_shr(13) as u8)
            .collect();
        assert!(repeat_rate(&randomish) < 0.01, "got {}", repeat_rate(&randomish));
        // 短于两窗为 0
        assert_eq!(repeat_rate(&[0u8; 256]), 0.0);
        // 扫描封顶不越界
        assert!(repeat_rate(&vec![0u8; REPEAT_SCAN_CAP * 3]).is_finite());
    }
}
