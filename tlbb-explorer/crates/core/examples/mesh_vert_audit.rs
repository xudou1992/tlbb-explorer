//! 网格顶点体检：包围盒、逐轴中位/σ、离群顶点（>5σ）。
//!
//! 用途：静态预览里出现「尖刺」时，先分清是数据本来如此还是位置流读歪。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example mesh_vert_audit -- <包> <哈希16进制>
//! ```

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::parse_mesh;

fn main() {
    let a: Vec<String> = std::env::args().skip(1).collect();
    if a.len() < 2 {
        eprintln!("需要：包名 网格哈希");
        return;
    }
    let root = PathBuf::from("D:/TLGL");
    let p = Pak::open(root.join(format!("{}.pak", a[0]))).expect("包打不开");
    let h = u64::from_str_radix(&a[1], 16).expect("哈希");
    let Some(rec) = p.records().find(|r| r.hash == h && r.stored > 0) else {
        println!("包里没有这个哈希");
        return;
    };
    let raw = payload::decode(&p, &rec).expect("解压失败").bytes;
    let l = parse_mesh(&raw).expect("网格解析失败");
    let g = &l.geometry;
    let n = g.positions.len();
    println!(
        "顶点 {n} · 面 {} · 子网格 {} · bbox {:?} … {:?}",
        g.face_count, g.submesh_count, g.bbox_min, g.bbox_max
    );
    let mut med = [0f32; 3];
    let mut sig = [0f32; 3];
    for k in 0..3 {
        let mut v: Vec<f32> = g.positions.iter().map(|p| p[k]).collect();
        v.sort_by(|a, b| a.total_cmp(b));
        med[k] = v[v.len() / 2];
        let mean = v.iter().sum::<f32>() / v.len() as f32;
        sig[k] = (v.iter().map(|x| (x - mean) * (x - mean)).sum::<f32>() / v.len() as f32).sqrt();
    }
    let mut out: Vec<(usize, [f32; 3], f32)> = Vec::new();
    for (i, p) in g.positions.iter().enumerate() {
        let z = ((0..3)
            .map(|k| ((p[k] - med[k]) / sig[k].max(1e-6)).abs())
            .fold(0f32, f32::max));
        if z > 5.0 {
            out.push((i, *p, z));
        }
    }
    println!("逐轴中位 {med:?} · σ {sig:?} · 离群(>5σ) {} 个 / {n}", out.len());
    out.sort_by(|a, b| b.2.total_cmp(&a.2));
    for (i, p, z) in out.iter().take(8) {
        println!("  #{i} {p:?} z={z:.1}");
    }
}
