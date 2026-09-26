//! 追查「沿 stride 走不动」的**具体原因**：是判据 M 破、判据 N 破，还是纯越界？
//!
//! 对全库 `.scene` 跑一遍，按 (tag, 停止阶段) 计数，并打印若干实例的现场字节。
//!
//!   cargo run --bin scene_stop

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::catalog::Catalog;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

const BASE: usize = 12;
const MATRIX_BYTES: usize = 64;

fn u32_at(raw: &[u8], off: usize) -> Option<u32> {
    let b = raw.get(off..off.checked_add(4)?)?;
    Some(u32::from_le_bytes(b.try_into().ok()?))
}
fn f32_at(raw: &[u8], off: usize) -> Option<f32> {
    let b = raw.get(off..off.checked_add(4)?)?;
    Some(f32::from_le_bytes(b.try_into().ok()?))
}
fn satisfies_m(raw: &[u8], at: usize) -> bool {
    (f32_at(raw, at + 12) == Some(0.0))
        && (f32_at(raw, at + 28) == Some(0.0))
        && (f32_at(raw, at + 44) == Some(0.0))
        && (f32_at(raw, at + 60) == Some(1.0))
}
fn read_name_at(raw: &[u8], at: usize) -> Option<String> {
    let start = at.checked_add(MATRIX_BYTES)?;
    let mut end = start;
    loop {
        let &c = raw.get(end)?;
        if c == 0 {
            break;
        }
        if !(0x20..0x7f).contains(&c) || c == b' ' || c == b'\\' {
            return None;
        }
        end += 1;
        if end - start > 200 {
            return None;
        }
    }
    if end == start {
        return None;
    }
    String::from_utf8(raw.get(start..end)?.to_vec()).ok()
}

#[derive(Default)]
struct Stat {
    stop_oob: usize,
    stop_m: usize,
    stop_n: usize,
    ok: usize,
    /// 走不动之后剩下的字节数（全部）
    leftover_sum: usize,
    /// 在走不动的那格 +64 之后是否能看到一个 NUL 结尾的可打印名字
    leftover_has_name: usize,
    leftover_has_m: usize,
    leftover_nonzero: usize,
}

fn main() {
    let root = PathBuf::from("D:/TLGL");
    let db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let out = PathBuf::from("D:/TLGL/.scratch/scene_stop.txt");

    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut idx: HashMap<(String, u64), tlbb_core::Record> = HashMap::new();
    let mut files: Vec<_> = std::fs::read_dir(&root)
        .expect("read root")
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "pak").unwrap_or(false))
        .collect();
    files.sort();
    for path in &files {
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        let pak = Pak::open(path).expect("open pak");
        for rec in pak.records() {
            idx.insert((stem.clone(), rec.hash), rec);
        }
        paks.insert(stem, pak);
    }
    let cat = Catalog::open_ro(&db).expect("open catalog");
    let mut cands: Vec<tlbb_core::catalog::Asset> = Vec::new();
    cands.extend(cat.by_type("scene", usize::MAX).unwrap());
    cands.extend(cat.by_type("binary", usize::MAX).unwrap());

    let mut by_tag: HashMap<u32, Stat> = HashMap::new();
    let mut samples: Vec<String> = Vec::new();

    for asset in &cands {
        if !asset.ext.eq_ignore_ascii_case(".scene") {
            continue;
        }
        let Some(rec) = idx.get(&(asset.pak.clone(), asset.hash)) else { continue };
        if rec.offset as i64 != asset.offset {
            continue;
        }
        let Some(pak) = paks.get(&asset.pak) else { continue };
        let Ok(dec) = payload::decode(pak, rec) else { continue };
        let raw = dec.bytes;
        let Some(declared) = u32_at(&raw, 0) else { continue };
        let Some(tag) = u32_at(&raw, 4) else { continue };
        if !matches!(tag, 324 | 592 | 596 | 601 | 605 | 749 | 753) {
            continue;
        }
        let stride = tag as usize + 8;
        let len = raw.len();

        // 手动走一遍，记录停止原因
        let mut offset = BASE;
        let mut n = 0usize;
        let stop = loop {
            if len < offset.saturating_add(MATRIX_BYTES + 2) {
                break "oob";
            }
            if !satisfies_m(&raw, offset) {
                break "m";
            }
            if read_name_at(&raw, offset).is_none() {
                break "n";
            }
            n += 1;
            offset = offset.saturating_add(stride);
        };

        let consumed = BASE + stride * n;
        let leftover = len.saturating_sub(consumed);
        let s = by_tag.entry(tag).or_default();
        match stop {
            "oob" => s.stop_oob += 1,
            "m" => s.stop_m += 1,
            _ => s.stop_n += 1,
        }
        s.ok += 1;
        s.leftover_sum += leftover;
        if leftover > 0 {
            if satisfies_m(&raw, consumed) {
                s.leftover_has_m += 1;
            }
            if read_name_at(&raw, consumed).is_some() {
                s.leftover_has_name += 1;
            }
            if raw[consumed..].iter().any(|&b| b != 0) {
                s.leftover_nonzero += 1;
            }
        }
        if n < declared as usize && samples.len() < 6 && consumed < len {
            let hex: String = raw[consumed..(consumed + 32).min(len)]
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<Vec<_>>()
                .join(" ");
            samples.push(format!(
                "  753-ish tag={tag} n={n} declared={declared} len={len} consumed={consumed} left={leftover} stop={stop}\n    path={}\n    hex@stop = {hex}",
                asset.path.clone().unwrap_or_default()
            ));
        }
    }

    let mut lines = Vec::new();
    let mut keys: Vec<u32> = by_tag.keys().copied().collect();
    keys.sort();
    for k in keys {
        let s = &by_tag[&k];
        lines.push(format!(
            "tag {k}: files={} stop_oob={} stop_M={} stop_N={} | leftover>0: M_ok={} N_ok={} nonzero={} avg_left={}",
            s.ok, s.stop_oob, s.stop_m, s.stop_n,
            s.leftover_has_m, s.leftover_has_name, s.leftover_nonzero,
            if s.ok > 0 { s.leftover_sum / s.ok } else { 0 }
        ));
    }
    lines.push("\n=== 停止现场样本 (n < declared) ===".to_string());
    lines.extend(samples);

    let text = lines.join("\n");
    println!("{text}");
    std::fs::write(&out, &text).ok();
    eprintln!("wrote {}", out.display());
}
