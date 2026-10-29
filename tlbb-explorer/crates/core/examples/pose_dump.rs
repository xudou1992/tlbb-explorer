//! 把某一帧的**我们的世界矩阵**导成 JSON，供与客户端运行时矩阵逐骨对账。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example pose_dump -- <网格包> <网格哈希> <动作包> <动作哈希> <帧号> <输出.json>
//! ```
//! 输出：`{"bones":N,"frame":F,"names":[...],"matrices":[[16 floats], ...]}`（行向量约定，与 `pose::pose_frame` 一致）。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, pose};

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 6 {
        eprintln!("需要：网格包 网格哈希 动作包 动作哈希 帧号 输出.json");
        return;
    }
    let root = PathBuf::from("D:/TLGL");
    let mp = Pak::open(root.join(format!("{}.pak", a[0]))).expect("网格包打不开");
    let ap = Pak::open(root.join(format!("{}.pak", a[2]))).expect("动作包打不开");
    let mh = u64::from_str_radix(&a[1], 16).expect("网格哈希");
    let ah = u64::from_str_radix(&a[3], 16).expect("动作哈希");
    let frame: usize = a[4].parse().expect("帧号");
    let rm = mp.records().find(|r| r.hash == mh && r.stored > 0).expect("网格不在包里");
    let ra = ap.records().find(|r| r.hash == ah && r.stored > 0).expect("动作不在包里");
    let mraw = payload::decode(&mp, &rm).expect("网格解压失败").bytes;
    let araw = payload::decode(&ap, &ra).expect("动作解压失败").bytes;
    let h = parse_hierarchy(&mraw).expect("骨架解析失败");
    let anim = parse_ani(&araw).expect("动作解析失败");
    let f = frame.min(anim.frames.saturating_sub(1));
    let world = pose::pose_frame(&h, &anim, f);
    let mut names = String::new();
    let mut mats = String::new();
    for (i, m) in world.iter().enumerate() {
        if i > 0 {
            names.push(',');
            mats.push(',');
        }
        names.push_str(&format!("\"{}\"", h.bones[i].name.replace('"', "")));
        mats.push('[');
        for (k, v) in m.iter().enumerate() {
            if k > 0 {
                mats.push(',');
            }
            mats.push_str(&format!("{v:.6}"));
        }
        mats.push(']');
    }
    let json = format!(
        "{{\"bones\":{},\"frame\":{},\"names\":[{}],\"matrices\":[{}]}}",
        world.len(),
        f,
        names,
        mats
    );
    std::fs::write(&a[5], json).expect("写文件失败");
    println!("已写 {}：骨 {} 帧 {}", a[5], world.len(), f);
}
