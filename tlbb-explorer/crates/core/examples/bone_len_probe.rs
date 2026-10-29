//! 逐帧量「每根骨到父骨原点的距离」。刚体骨架在纯旋转动作里这个距离应当恒定；
//! 某根骨的距离大幅变化，说明它的局部平移通道在动（或是读错了通道），
//! 这正是「关节被拉开」那类观感的来源。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example bone_len_probe -- <网格包> <网格哈希> <动作包> <动作哈希>
//! ```

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, pose};

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 4 {
        eprintln!("需要：网格包 网格哈希 动作包 动作哈希");
        return;
    }
    let root = PathBuf::from("D:/TLGL");
    let mp = Pak::open(root.join(format!("{}.pak", a[0]))).expect("网格包打不开");
    let ap = Pak::open(root.join(format!("{}.pak", a[2]))).expect("动作包打不开");
    let mh = u64::from_str_radix(&a[1], 16).expect("网格哈希");
    let ah = u64::from_str_radix(&a[3], 16).expect("动作哈希");
    let rm = mp.records().find(|r| r.hash == mh && r.stored > 0).expect("网格不在包里");
    let ra = ap.records().find(|r| r.hash == ah && r.stored > 0).expect("动作不在包里");
    let mraw = payload::decode(&mp, &rm).expect("网格解压失败").bytes;
    let araw = payload::decode(&ap, &ra).expect("动作解压失败").bytes;
    let h = parse_hierarchy(&mraw).expect("骨架解析失败");
    let anim = parse_ani(&araw).expect("动作解析失败");
    let frames = anim.frames;
    // 每根骨：min/max 到父骨原点的距离
    let mut stat: Vec<Option<(f32, f32)>> = vec![None; h.bones.len()];
    let step = (frames / 12).max(1);
    let mut f = 0;
    while f < frames {
        let world = pose::pose_frame(&h, &anim, f);
        for (i, b) in h.bones.iter().enumerate() {
            let Some(p) = b.parent else { continue };
            let d = dist(&world[i], &world[p]);
            let e = stat[i].get_or_insert((d, d));
            e.0 = e.0.min(d);
            e.1 = e.1.max(d);
        }
        f += step;
    }
    let mut rows: Vec<(f32, &str, f32, f32)> = Vec::new();
    for (i, s) in stat.iter().enumerate() {
        let Some((mn, mx)) = *s else { continue };
        if mn <= 1e-6 {
            continue;
        }
        rows.push((mx / mn, &h.bones[i].name, mn, mx));
    }
    rows.sort_by(|a, b| b.0.total_cmp(&a.0));
    println!("骨 {} 帧 {} · 到父骨原点距离变化最大的前 12 根：", h.bones.len(), frames);
    for (r, n, mn, mx) in rows.iter().take(12) {
        println!("  {n:<28} x{r:.3}  [{mn:.4} .. {mx:.4}]");
    }
    let bad = rows.iter().filter(|(r, ..)| *r > 1.05).count();
    println!("变化 >5% 的骨：{bad}/{}", rows.len());
}

fn dist(m: &[f32; 16], p: &[f32; 16]) -> f32 {
    let dx = m[12] - p[12];
    let dy = m[13] - p[13];
    let dz = m[14] - p[14];
    (dx * dx + dy * dy + dz * dz).sqrt()
}
