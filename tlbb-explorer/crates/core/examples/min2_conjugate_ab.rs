//! MIN2「存储旋转是不是需要按绑定旋转共轭」的受控 A/B。
//!
//! 静态侧此前只试过「左乘/右乘绑定旋转」，没试过共轭 `B·R·B⁻¹` / `B⁻¹·R·B`。
//! 三种口径同一把撕边尺（`pose::edge_stretch`），逐帧合计对比。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example min2_conjugate_ab -- "D:/TLGL/.scratch/dyn/probe_pairs.json"
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose, rest_poses, Anim};

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

fn main() {
    let pairs_file = std::env::args().nth(1).unwrap_or_default();
    let text = std::fs::read_to_string(&pairs_file).expect("配对文件读不到");
    let mut vals: Vec<String> = Vec::new();
    for line in text.lines() {
        let t = line.trim().trim_end_matches(',');
        if t.starts_with('"') {
            vals.push(t.trim_matches('"').to_string());
        }
    }
    println!("配对 {} 组（原始条目）", vals.len() / 3);
    let root = PathBuf::from("D:/TLGL");
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let (mut done, mut skipped) = (0usize, 0usize);
    let (mut sum_plain, mut sum_conj, mut sum_inv) = (0f64, 0f64, 0f64);
    let (mut win_conj, mut win_inv, mut win_plain) = (0usize, 0usize, 0usize);
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
        let (Ok(layout), Some(h), Some(a), Some(rests)) =
            (parse_mesh(&mraw), parse_hierarchy(&mraw), parse_ani(&araw), rest_poses(&araw))
        else {
            skipped += 1;
            continue;
        };
        let nodes = parse_nodes(&mraw);
        let g = &layout.geometry;
        if g.positions.is_empty() || g.indices.is_empty() {
            skipped += 1;
            continue;
        }
        let bind_q: HashMap<&str, [f32; 4]> =
            rests.iter().filter(|r| !r.bone.is_empty()).map(|r| (r.bone.as_str(), r.rotation)).collect();
        let mut conj = a.clone();
        let mut inv = a.clone();
        for t in conj.tracks.iter_mut() {
            if let Some(b) = bind_q.get(t.bone.as_str()) {
                for q in t.rotations.iter_mut() {
                    *q = qmul(&qmul(b, q), &qconj(b));
                }
            }
        }
        for t in inv.tracks.iter_mut() {
            if let Some(b) = bind_q.get(t.bone.as_str()) {
                let bc = qconj(b);
                for q in t.rotations.iter_mut() {
                    *q = qmul(&qmul(&bc, q), b);
                }
            }
        }
        let bind = pose::bind_worlds(&h);
        let total = |anim: &Anim| -> Option<usize> {
            let mut sum = 0usize;
            for f in 0..anim.frames {
                let world = pose::pose_frame(&h, anim, f);
                let pal = pose::skin_palette(&h, &bind, &world)?;
                let posed = pose::posed_vertices(&h, &pal, &nodes, &g.positions)?;
                sum += pose::edge_stretch(&g.positions, &posed, &g.indices).over15;
            }
            Some(sum)
        };
        let (Some(plain), Some(c), Some(i)) = (total(&a), total(&conj), total(&inv)) else {
            skipped += 1;
            continue;
        };
        done += 1;
        sum_plain += plain as f64;
        sum_conj += c as f64;
        sum_inv += i as f64;
        if c < plain && c <= i {
            win_conj += 1;
        } else if i < plain && i < c {
            win_inv += 1;
        } else {
            win_plain += 1;
        }
        println!(
            "  {mh:016x} 骨{} 帧{} 轨道{} · 现在 {plain:7} · B·R·B⁻¹ {c:7} · B⁻¹·R·B {i:7}",
            a.bones,
            a.frames,
            a.tracks.len()
        );
    }
    println!("MIN2 {done} 份（跳过 {skipped}）· 全帧撕边合计：现在 {sum_plain:.0} · 共轭 {sum_conj:.0} · 逆共轭 {sum_inv:.0}");
    println!("更好份数：共轭 {win_conj} · 逆共轭 {win_inv} · 现在 {win_plain}");
}
