//! MIN2 轨道区到底是「一根骨连排完所有帧」还是「一帧连排完所有骨」。
//!
//! 为什么值得单测：`bones × frames × 32` 这条**长度**闸门两种排法都过；
//! 每条 32B 记录自身仍是「四元数+位移+缩放」，所以四元数单位长、中位数≈绑定局部
//! 这些自检**两种排法都照样成立**——只有**帧与帧之间的连续性**能分辨。
//! 排错时间序的后果正是「每根骨各自摆在自己那一帧」＝皮撕开，而单帧数据看着全对。
//!
//! 判据：同一根骨相邻两帧的四元数夹角。排对了应该小（动作是连续的），排错了接近随机。
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example min2_order_probe -- "D:/TLGL/.scratch/dyn/probe_pairs.json"
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::parse_ani_header;

fn ang(q0: [f32; 4], q1: [f32; 4]) -> f32 {
    let d = (q0[0] * q1[0] + q0[1] * q1[1] + q0[2] * q1[2] + q0[3] * q1[3]).abs().clamp(-1.0, 1.0);
    2.0 * d.acos()
}

fn quat_at(raw: &[u8], o: usize) -> Option<[f32; 4]> {
    let s = raw.get(o..o + 16)?;
    let q = [
        f32::from_le_bytes([s[0], s[1], s[2], s[3]]),
        f32::from_le_bytes([s[4], s[5], s[6], s[7]]),
        f32::from_le_bytes([s[8], s[9], s[10], s[11]]),
        f32::from_le_bytes([s[12], s[13], s[14], s[15]]),
    ];
    let n = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt();
    // 只认单位长的四元数，否则这一格不算数据（两种排法都要过这条，保证公平）
    if (n - 1.0).abs() > 0.02 {
        return None;
    }
    Some(q)
}

/// 按给定排法量「同一根骨相邻帧」的平均夹角；返回 (平均, 参与对数)
fn walk(raw: &[u8], base: usize, bones: usize, frames: usize, frame_major: bool) -> (f64, usize) {
    let (mut sum, mut n) = (0f64, 0usize);
    for b in 0..bones {
        let mut prev: Option<[f32; 4]> = None;
        for f in 0..frames {
            let rec = if frame_major {
                (f * bones + b) * 32
            } else {
                b * frames * 32 + f * 32
            };
            match quat_at(raw, base + rec) {
                Some(q) => {
                    if let Some(p) = prev {
                        sum += ang(p, q) as f64;
                        n += 1;
                    }
                    prev = Some(q);
                }
                None => prev = None,
            }
        }
    }
    (if n > 0 { sum / n as f64 } else { 0.0 }, n)
}

fn main() {
    let pairs_file = match std::env::args().nth(1) {
        Some(p) => p,
        None => {
            println!("要给配对文件");
            return;
        }
    };
    let json = std::fs::read_to_string(&pairs_file).expect("配对文件读不到");
    let mut anis: Vec<(u64, String)> = Vec::new();
    for row in json.trim().trim_start_matches('[').trim_end_matches(']').split("],") {
        let parts: Vec<&str> = row
            .trim()
            .trim_start_matches('[')
            .trim_end_matches(']')
            .split(',')
            .map(|s| s.trim().trim_matches('"'))
            .collect();
        // 兼容两种格式：[mesh,pak,ani,pak] 与 [mesh,ani,pak]
        let (h, pak) = if parts.len() >= 4 {
            (parts[2], parts[3])
        } else if parts.len() == 3 {
            (parts[1], parts[2])
        } else {
            continue;
        };
        if let Ok(v) = u64::from_str_radix(h, 16) {
            anis.push((v, pak.to_string()));
        }
    }
    let root = PathBuf::from("D:/TLGL");
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let (mut bone_better, mut frame_better, mut both_zero) = (0usize, 0usize, 0usize);
    let mut ratios: Vec<f64> = Vec::new();
    let mut scanned = 0usize;
    for (h, pak_name) in &anis {
        if !paks.contains_key(pak_name) {
            if let Ok(p) = Pak::open(root.join(format!("{pak_name}.pak"))) {
                paks.insert(pak_name.clone(), p);
            }
        }
        let Some(p) = paks.get(pak_name) else { continue };
        let Some(rec) = p.records().find(|r| r.hash == *h && r.stored > 0) else {
            continue;
        };
        let Ok(raw) = payload::decode(p, &rec) else { continue };
        let raw = raw.bytes;
        if raw.get(0x8c..0x90) != Some(&b"MIN2"[..]) {
            continue;
        }
        let Some(hdr) = parse_ani_header(&raw) else { continue };
        let need = hdr.bones * hdr.frames * 32;
        if need > raw.len() || hdr.frames < 3 {
            continue;
        }
        let base = raw.len() - need;
        let (bm, n1) = walk(&raw, base, hdr.bones, hdr.frames, false);
        let (fm, n2) = walk(&raw, base, hdr.bones, hdr.frames, true);
        if n1 == 0 || n2 == 0 {
            both_zero += 1;
            continue;
        }
        scanned += 1;
        let r = bm / fm;
        if r.is_finite() {
            ratios.push(r);
        }
        if bm < fm {
            bone_better += 1;
        } else {
            frame_better += 1;
        }
        if scanned <= 8 {
            println!(
                "  {h:016x} {}骨×{}帧：骨主序 平均相邻角 {:.4} rad · 帧主序 {:.4} rad · 比值 {:.2}",
                hdr.bones, hdr.frames, bm, fm, bm / fm
            );
        }
    }
    ratios.sort_by(f64::total_cmp);
    let med = *ratios.get(ratios.len() / 2).unwrap_or(&0.0);
    println!(
        "MIN2 扫 {scanned} 份：骨主序更连续 {bone_better} 份 · 帧主序更连续 {frame_better} 份 · 中位比值(骨/帧) {med:.2}（<1 = 现在这套对）；两序都取不到样的 {both_zero} 份"
    );
}
