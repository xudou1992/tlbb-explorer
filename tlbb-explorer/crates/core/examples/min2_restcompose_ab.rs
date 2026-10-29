//! MIN2 合成口径重测（**页面同款锚**）：轨道旋转是「绝对局部」还是「相对绑定」。
//!
//! 档案第五十六轮否过 `rest∘frame` / `frame∘rest`，但那次用的是 `.mesh` 绑定当锚
//! （今天已证明该锚会给整份网格恒定假阳）。这里改成与动作页一致的「第 0 帧为锚」重判。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example min2_restcompose_ab -- data3 dcbab0b69fcc82a4 data3 1f183a78a99e0988
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose, rest_poses, SkeletonHierarchy};

/// 自己搭一遍「局部 → 世界」，因为要换的是**局部怎么来**。
fn worlds(h: &SkeletonHierarchy, local: &[[f32; 16]]) -> Vec<[f32; 16]> {
    let n = h.bones.len();
    let mut w = vec![pose::mat_identity(); n];
    let mut done = vec![false; n];
    for _ in 0..=n {
        let mut moved = false;
        for i in 0..n {
            if done[i] {
                continue;
            }
            match h.bones[i].parent {
                None => {
                    w[i] = local[i];
                    done[i] = true;
                    moved = true;
                }
                Some(p) if done[p] => {
                    w[i] = pose::mat_mul(&local[i], &w[p]);
                    done[i] = true;
                    moved = true;
                }
                Some(_) => {}
            }
        }
        if !moved {
            break;
        }
    }
    w
}

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 4 {
        eprintln!("需要 网格pak 网格哈希 动作pak 动作哈希");
        return;
    }
    let root = PathBuf::from("D:/TLGL");
    let mp = Pak::open(root.join(format!("{}.pak", a[0]))).expect("网格包打不开");
    let ap = Pak::open(root.join(format!("{}.pak", a[2]))).expect("动作包打不开");
    let mh = u64::from_str_radix(&a[1], 16).unwrap();
    let ah = u64::from_str_radix(&a[3], 16).unwrap();
    let rm = mp.records().find(|r| r.hash == mh && r.stored > 0).expect("网格不在包里");
    let ra = ap.records().find(|r| r.hash == ah && r.stored > 0).expect("动作不在包里");
    let mraw = payload::decode(&mp, &rm).expect("网格解压失败").bytes;
    let araw = payload::decode(&ap, &ra).expect("动作解压失败").bytes;
    println!("容器 {}", String::from_utf8_lossy(&araw[0x8c..0x90]));
    let layout = parse_mesh(&mraw).expect("网格解析失败");
    let h = parse_hierarchy(&mraw).expect("骨架解析失败");
    let anim = parse_ani(&araw).expect("动作解析失败");
    let nodes = parse_nodes(&mraw);
    let g = &layout.geometry;
    let n = h.bones.len();
    let bw = pose::bind_worlds(&h);
    // 绑定局部旋转（只取旋转部分，平移/缩放仍走轨道值）
    let mut rest_rot = vec![pose::mat_identity(); n];
    for j in 0..n {
        if let Some(p) = h.bones[j].parent {
            if let Some(inv) = pose::mat_inverse_affine(&bw[p]) {
                let l = pose::mat_mul(&bw[j], &inv);
                let mut r = l;
                for k in 12..15 {
                    r[k] = 0.0;
                }
                r[15] = 1.0;
                rest_rot[j] = r;
            }
        }
    }
    let mut idx: HashMap<&str, usize> = HashMap::new();
    for (i, b) in h.bones.iter().enumerate() {
        idx.insert(b.name.as_str(), i);
    }
    // 第三组参照：用 `.ani` 静态区的绑定旋转（按骨名映射）做复合，而不是网格绑定。
    let rests = rest_poses(&araw);
    let mut static_rot: std::collections::HashMap<&str, [f32; 4]> = Default::default();
    if let Some(rs) = &rests {
        for r in rs {
            if !r.bone.is_empty() {
                static_rot.insert(r.bone.as_str(), r.rotation);
            }
        }
    }
    let quat_mat = |q: &[f32; 4]| {
        let [x, y, z, w] = *q;
        let mut m = [0f32; 16];
        m[0] = 1.0 - 2.0 * (y * y + z * z);
        m[1] = 2.0 * (x * y + w * z);
        m[2] = 2.0 * (x * z - w * y);
        m[4] = 2.0 * (x * y - w * z);
        m[5] = 1.0 - 2.0 * (x * x + z * z);
        m[6] = 2.0 * (y * z + w * x);
        m[8] = 2.0 * (x * z + w * y);
        m[9] = 2.0 * (y * z - w * x);
        m[10] = 1.0 - 2.0 * (x * x + y * y);
        m[15] = 1.0;
        m
    };
    let modes = [
        "绝对局部（现口径）",
        "绑定∘轨道",
        "轨道∘绑定",
        "静态∘轨道",
        "轨道∘静态",
        "静态⁻¹∘轨道",
        "轨道∘静态⁻¹",
    ];
    let mut sums = [0u64; 7];
    for (m, name) in modes.iter().enumerate() {
        let mut total = 0u64;
        let mut anchor: Vec<[f32; 16]> = Vec::new();
        for f in 0..anim.frames {
            let mut local = vec![pose::mat_identity(); n];
            for t in &anim.tracks {
                if t.bone.is_empty() || t.rotations.is_empty() {
                    continue;
                }
                let Some(&j) = idx.get(t.bone.as_str()) else { continue };
                let k = f.min(t.rotations.len() - 1);
                let trs = pose::trs_matrix(&t.rotations[k], t.positions[k], t.scales[k]);
                local[j] = match m {
                    0 => trs,
                    1 => pose::mat_mul(&rest_rot[j], &trs),
                    2 => pose::mat_mul(&trs, &rest_rot[j]),
                    3 => match static_rot.get(t.bone.as_str()) {
                        Some(q) => pose::mat_mul(&quat_mat(q), &trs),
                        None => trs,
                    },
                    4 => match static_rot.get(t.bone.as_str()) {
                        Some(q) => pose::mat_mul(&trs, &quat_mat(q)),
                        None => trs,
                    },
                    5 => match static_rot.get(t.bone.as_str()) {
                        Some(q) => {
                            let inv = [-q[0], -q[1], -q[2], q[3]];
                            pose::mat_mul(&quat_mat(&inv), &trs)
                        }
                        None => trs,
                    },
                    _ => match static_rot.get(t.bone.as_str()) {
                        Some(q) => {
                            let inv = [-q[0], -q[1], -q[2], q[3]];
                            pose::mat_mul(&trs, &quat_mat(&inv))
                        }
                        None => trs,
                    },
                };
            }
            let w = worlds(&h, &local);
            if f == 0 {
                anchor = w.clone();
            }
            let Some(pal) = pose::skin_palette(&h, &anchor, &w) else { continue };
            let Some(posed) = pose::posed_vertices(&h, &pal, &nodes, &g.positions) else { continue };
            total += pose::edge_stretch(&g.positions, &posed, &g.indices).over15 as u64;
        }
        sums[m] = total;
        println!("{name:22} 全帧撕边合计 {total}");
    }
    let best = sums.iter().position(|s| *s == *sums.iter().min().unwrap()).unwrap();
    println!("最低的是第 {} 种：{}", best + 1, modes[best]);
}
