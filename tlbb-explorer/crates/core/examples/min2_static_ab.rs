//! MIN2 静态区：基址偏移 × 四元数约定 × 骨配对 的全组合裁决。
//!
//! 裁判是「静态记录里的绑定旋转」对「`.mesh` 反推出的绑定局部旋转」的角度差
//! （和 `rest::align_probe` 同一口径，但这里把三个参数拆开，不再由 `named` 一个变量同时管）。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example min2_static_ab -- "D:/TLGL/.scratch/dyn/probe_pairs.json"
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, pose};

fn qmul(a: &[f32; 4], b: &[f32; 4]) -> [f32; 4] {
    let [ax, ay, az, aw] = *a;
    let [bx, by, bz, bw] = *b;
    [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]
}

fn qconj(q: &[f32; 4]) -> [f32; 4] {
    [-q[0], -q[1], -q[2], q[3]]
}

/// 两个旋转矩阵的夹角（度）：`acos((tr(A·Bᵀ) − 1)/2)`，行主序 3×3 取前 12 个里的 0,4,8,1,5,9,2,6,10。
fn angle_deg(a: &[f32; 16], b: &[f32; 16]) -> f32 {
    let mut tr = 0f32;
    for r in 0..3 {
        for k in 0..3 {
            tr += a[r * 4 + k] * b[r * 4 + k];
        }
    }
    ((tr - 1.0) / 2.0).clamp(-1.0, 1.0).acos().to_degrees()
}

fn main() {
    let pairs_file = std::env::args().nth(1).unwrap_or_default();
    let text = std::fs::read_to_string(&pairs_file).expect("配对文件读不到");
    let vals: Vec<String> = text
        .lines()
        .map(|l| l.trim().trim_end_matches(',').to_string())
        .filter(|l| l.starts_with('"'))
        .map(|l| l.trim_matches('"').to_string())
        .collect();
    let root = PathBuf::from("D:/TLGL");
    let mut paks: HashMap<String, Pak> = HashMap::new();
    // (基址偏移, 四元子偏移, 四元数约定, 骨配对) → (命中, 总数)
    let mut votes: HashMap<(u32, usize, &str, u32), (usize, usize)> = HashMap::new();
    let mut files = 0usize;
    for row in vals.chunks(3) {
        let (mh, ah, pk) = (&row[0], &row[1], &row[2]);
        let (Ok(mh), Ok(ah)) = (u64::from_str_radix(mh, 16), u64::from_str_radix(ah, 16)) else {
            continue;
        };
        if !paks.contains_key(pk) {
            if let Ok(p) = Pak::open(root.join(format!("{pk}.pak"))) {
                paks.insert(pk.clone(), p);
            }
        }
        let Some(pak) = paks.get(pk) else { continue };
        let Some(rm) = pak.records().find(|r| r.hash == mh && r.stored > 0) else { continue };
        let Some(ra) = pak.records().find(|r| r.hash == ah && r.stored > 0) else { continue };
        let (Ok(mraw), Ok(araw)) = (
            payload::decode(pak, &rm).map(|d| d.bytes),
            payload::decode(pak, &ra).map(|d| d.bytes),
        ) else {
            continue;
        };
        if araw.get(0x8c..0x90) != Some(&b"MIN2"[..]) {
            continue;
        }
        let (Ok(_), Some(h), Some(a)) = (parse_mesh(&mraw), parse_hierarchy(&mraw), parse_ani(&araw))
        else {
            continue;
        };
        let n = h.bones.len();
        if n != a.bones {
            continue;
        }
        let bw = pose::bind_worlds(&h);
        // 网格反推的绑定局部旋转矩阵
        let mut local: Vec<Option<[f32; 16]>> = vec![None; n];
        for j in 0..n {
            let Some(p) = h.bones[j].parent else {
                local[j] = Some(bw[j]);
                continue;
            };
            if let Some(inv) = pose::mat_inverse_affine(&bw[p]) {
                local[j] = Some(pose::mat_mul(&bw[j], &inv));
            }
        }
        let names_end = 0xd2 + n * 30;
        files += 1;
        for off in [0u32, 16u32, 46u32, 76u32] {
            for qa in [12usize, 28] {
            for conv in ["原样", "取逆"] {
                for pair in [0u32, 1] {
                    let mut hit = 0usize;
                    let mut tot = 0usize;
                    for j in 0..n {
                        let Some(l) = local[j] else { continue };
                        let Some(i) = j.checked_sub(pair as usize) else { continue };
                        if i >= n {
                            continue;
                        }
                        let o = names_end + off as usize + i * 60 + qa;
                        let Some(b) = araw.get(o..o + 16) else { continue };
                        let g = |k: usize| f32::from_le_bytes([b[4 * k], b[4 * k + 1], b[4 * k + 2], b[4 * k + 3]]);
                        let mut q = [g(0), g(1), g(2), g(3)];
                        let nn: f32 = q.iter().map(|v| v * v).sum::<f32>().sqrt();
                        if !(0.99..=1.01).contains(&nn) {
                            continue;
                        }
                        q = q.map(|v| v / nn);
                        if conv == "取逆" {
                            q = qconj(&q);
                        }
                        // 四元数 → 行主序旋转矩阵（与 pose::quat_to_mat 同式）
                        let [x, y, z, w] = q;
                        let m: [f32; 16] = [
                            1.0 - 2.0 * (y * y + z * z),
                            2.0 * (x * y + w * z),
                            2.0 * (x * z - w * y),
                            0.0,
                            2.0 * (x * y - w * z),
                            1.0 - 2.0 * (x * x + z * z),
                            2.0 * (y * z + w * x),
                            0.0,
                            2.0 * (x * z + w * y),
                            2.0 * (y * z - w * x),
                            1.0 - 2.0 * (x * x + y * y),
                            0.0,
                            0.0,
                            0.0,
                            0.0,
                            1.0,
                        ];
                        tot += 1;
                        if angle_deg(&m, &l) < 0.5 {
                            hit += 1;
                        }
                    }
                    let e = votes.entry((off, qa, conv, pair)).or_default();
                    e.0 += hit;
                    e.1 += tot;
                }
            }
            }
        }
    }
    println!("MIN2 参与裁决的份数：{files}");
    let mut rows: Vec<_> = votes.into_iter().collect();
    rows.sort_by(|a, b| {
        let ra = if a.1 .1 == 0 { 0.0 } else { a.1 .0 as f64 / a.1 .1 as f64 };
        let rb = if b.1 .1 == 0 { 0.0 } else { b.1 .0 as f64 / b.1 .1 as f64 };
        rb.total_cmp(&ra)
    });
    for ((off, qa, conv, pair), (hit, tot)) in rows {
        println!(
            "基址=名表末+{off:>3}  四元数@{qa:>2}  {conv}  记录 i ↔ 骨 i+{pair}：{hit:>6}/{tot:<6} = {:.1}%",
            if tot == 0 { 0.0 } else { hit as f64 * 100.0 / tot as f64 }
        );
    }
    let _ = qmul;
}
