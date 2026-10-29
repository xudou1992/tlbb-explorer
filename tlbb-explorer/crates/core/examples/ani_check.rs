//! 读两份 `.ani` 交给真解析器，报它到底认不认、认出来多少骨/帧。
//! 用法：cargo run --offline --example ani_check -- <file> [<file> ...]
use std::path::PathBuf;

use tlbb_core::preview::parse_ani;

fn main() {
    for p in std::env::args().skip(1) {
        let path = PathBuf::from(&p);
        let raw = std::fs::read(&path).expect("读不到文件");
        match parse_ani(&raw) {
            Some(a) => {
                // 「会动」判据：该骨旋转或位移的帧间极差 > 1e-4（与 skeleton.rs::track_moves 同口径）。
                let moving = a
                    .tracks
                    .iter()
                    .filter(|t| {
                        let dr = spread(&t.rotations.iter().map(|q| q.to_vec()).collect::<Vec<_>>());
                        let dp = spread(&t.positions.iter().map(|p| p.to_vec()).collect::<Vec<_>>());
                        let ds = spread(&t.scales.iter().map(|s| vec![*s]).collect::<Vec<_>>());
                        dr > 1e-4 || dp > 1e-4 || ds > 1e-4
                    })
                    .count();
                println!(
                    "{} · len={} · 认出：骨 {} 帧 {} tick {:.2} · 会动的骨 {moving}",
                    path.file_name().unwrap_or_default().to_string_lossy(),
                    raw.len(),
                    a.tracks.len(),
                    a.frames,
                    a.tick
                );
            }
            None => println!(
                "{} · len={} · 不认（None）",
                path.file_name().unwrap_or_default().to_string_lossy(),
                raw.len()
            ),
        }
    }
}

/// 一列向量的逐分量极差的最大值（旋转 4 维、位移 3 维、缩放 1 维都能用）。
fn spread(vals: &[Vec<f32>]) -> f32 {
    let Some(first) = vals.first() else {
        return 0.0;
    };
    let n = first.len();
    let mut lo = first.clone();
    let mut hi = first.clone();
    for v in vals.iter().skip(1) {
        for k in 0..n.min(v.len()) {
            if v[k] < lo[k] {
                lo[k] = v[k];
            }
            if v[k] > hi[k] {
                hi[k] = v[k];
            }
        }
    }
    (0..n).map(|k| (hi[k] - lo[k]).abs()).fold(0.0, f32::max)
}
