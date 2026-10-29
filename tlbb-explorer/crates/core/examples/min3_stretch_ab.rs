//! MIN3「缺位移块用绑定局部平移」这条修掉的到底是什么：同一份数据，两种填法各量一遍边长倍数。
//!
//! 填零 = 改前的行为（没位移块的骨被挪到父骨原点）；填绑定局部平移 = 现在的行为。
//! 尺子与闸门同一份（`pose::edge_stretch`），每帧取峰值、报告全帧最大。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example min3_stretch_ab -- "D:/TLGL/.scratch/dyn/min3_pairs.json"
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes, pose, Anim};

fn main() {
    let pairs_file = std::env::args().nth(1).unwrap_or_default();
    let json = std::fs::read_to_string(&pairs_file).expect("配对文件读不到");
    // [mesh_pak, mesh_hash, ani_pak, ani_hash]
    let mut pairs: Vec<(String, u64, String, u64)> = Vec::new();
    for row in json.trim().trim_start_matches('[').trim_end_matches(']').split("],") {
        let p: Vec<&str> = row
            .trim()
            .trim_start_matches('[')
            .trim_end_matches(']')
            .split(',')
            .map(|s| s.trim().trim_matches('"'))
            .collect();
        if p.len() < 4 {
            continue;
        }
        if let (Ok(m), Ok(a)) = (u64::from_str_radix(p[1], 16), u64::from_str_radix(p[3], 16)) {
            pairs.push((p[0].to_string(), m, p[2].to_string(), a));
        }
    }
    println!("配对 {} 组", pairs.len());
    let root = PathBuf::from("D:/TLGL");
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut done = 0usize;
    let mut better = 0usize;
    let (mut sum_fill, mut sum_zero, mut sum_d0) = (0f64, 0f64, 0f64);
    for (mpk, mh, apk, ah) in &pairs {
        for k in [mpk, apk] {
            if !paks.contains_key(k) {
                if let Ok(p) = Pak::open(root.join(format!("{k}.pak"))) {
                    paks.insert(k.clone(), p);
                }
            }
        }
        let (Some(mp), Some(ap)) = (paks.get(mpk), paks.get(apk)) else { continue };
        let Some(rm) = mp.records().find(|r| r.hash == *mh && r.stored > 0) else { continue };
        let Some(ra) = ap.records().find(|r| r.hash == *ah && r.stored > 0) else { continue };
        let (Ok(mraw), Ok(araw)) = (
            payload::decode(mp, &rm).map(|d| d.bytes),
            payload::decode(ap, &ra).map(|d| d.bytes),
        ) else {
            continue;
        };
        if araw.get(0x8c..0x90) != Some(&b"MIN3"[..]) {
            continue;
        }
        let (Ok(layout), Some(h), Some(a)) =
            (parse_mesh(&mraw), parse_hierarchy(&mraw), parse_ani(&araw))
        else {
            println!("  跳过 {mh:016x}：网格/骨架/动作有一项解不出");
            continue;
        };
        let nodes = parse_nodes(&mraw);
        let g = &layout.geometry;
        if g.positions.is_empty() || g.indices.is_empty() {
            continue;
        }
        // 标志区闭式：0xD2 + 78×骨数；bit1 = 有位移块
        let flags_at = 0xd2 + 78 * a.bones;
        let mut zeroed = a.clone();
        let mut no_pos_blocks = 0usize;
        for (i, t) in zeroed.tracks.iter_mut().enumerate() {
            let f = araw
                .get(flags_at + i * 4..flags_at + i * 4 + 4)
                .map(|b| u32::from_le_bytes(b.try_into().unwrap()))
                .unwrap_or(0);
            if f & 2 == 0 {
                no_pos_blocks += 1;
                t.positions = vec![[0.0, 0.0, 0.0]; t.positions.len()];
            }
        }
        // 第三个变体：把骨名标签退回「同名同序」（δ=0，改前的读法），数据一个字节不动
        let mut d0 = a.clone();
        for (i, t) in d0.tracks.iter_mut().enumerate() {
            let o = 0xd2 + i * 30;
            let slot = araw.get(o..o + 30);
            t.bone = match slot {
                Some(b) => {
                    let end = b.iter().position(|&c| c == 0).unwrap_or(30);
                    String::from_utf8_lossy(&b[..end]).into_owned()
                }
                None => String::new(),
            };
        }
        let bind = pose::bind_worlds(&h);
        // 只数「边长被拉开 >1.5 倍的边」：max_ratio 会被焊接微边顶到天文数字，
        // 档案里明写「均值/极值一律不许引」，这条尺子数的是撕边条数。
        let peak = |anim: &Anim| -> Option<(usize, usize)> {
            let mut worst = (0usize, 0usize); // (单帧最多撕边, 全帧合计撕边)
            let mut sum = 0usize;
            for f in 0..anim.frames {
                let world = pose::pose_frame(&h, anim, f);
                let pal = pose::skin_palette(&h, &bind, &world)?;
                let posed = pose::posed_vertices(&h, &pal, &nodes, &g.positions)?;
                let s = pose::edge_stretch(&g.positions, &posed, &g.indices);
                worst.0 = worst.0.max(s.over15);
                sum += s.over15;
            }
            worst.1 = sum;
            Some(worst)
        };
        let (Some(fill), Some(zero), Some(old)) = (peak(&a), peak(&zeroed), peak(&d0)) else { continue };
        done += 1;
        sum_fill += fill.1 as f64;
        sum_zero += zero.1 as f64;
        sum_d0 += old.1 as f64;
        if fill.1 < zero.1 {
            better += 1;
        }
        println!(
            "  {mh:016x} 骨{} 帧{} 无位移块 {} 根 · 现在(δ1+填绑定) 合计 {:7} · δ0 同名同序 合计 {:7} · δ1+填零 {:7}",
            a.bones, a.frames, no_pos_blocks, fill.1, old.1, zero.1
        );
    }
    if done > 0 {
        println!(
            "MIN3 {done} 份 · 全帧撕边合计：现在(δ1+填绑定) {:.0} · δ0 同名同序 {:.0} · δ1+填零 {:.0}（填绑定更少的 {better} 份）",
            sum_fill,
            sum_d0,
            sum_zero
        );
    }
}
