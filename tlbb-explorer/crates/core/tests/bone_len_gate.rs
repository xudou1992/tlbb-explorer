//! 骨长闸门：纯旋转动作里，每根骨到父骨原点的距离必须基本恒定。
//!
//! 起因：西域窃贼的 `idle01` 在蹲伏帧看起来「腿被拉长」，怀疑是局部平移通道读错或
//! 合成顺序错。用世界矩阵量骨长：除根骨/脚步（本来就带平移动画）外，全部骨的
//! 距离波动 ≤0.01%，因此蹲伏的长腿是姿势本身，不是骨架被拉长。
//!
//! 这条闸门钉住「我们这侧不许把骨长改坏」：一旦有人改合成/平移口径，比例会立刻跳起来。
//! 真数据缺失时降级跳过（夹具不入库，照 `stretch_gate.rs` 的做法）。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, pose};

const MESH: u64 = 0xbcd65050a62986b7;
/// idle01（41 帧）与 behit01（21 帧）：一条常态、一条最极端。
const IDLE01: u64 = 0x4ec2478a169d5e73;
const BEHIT01: u64 = 0x1a2545b8c7c1d09a;

fn raw_of(root: &PathBuf, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join("data.pak")).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

/// 返回（最大距离比，波动 >5% 的骨数，参与统计的骨数）。
fn len_ratios(ani_hash: u64) -> Option<(f32, usize, usize)> {
    let root = PathBuf::from("D:/TLGL");
    let mraw = raw_of(&root, MESH)?;
    let araw = raw_of(&root, ani_hash)?;
    let h = parse_hierarchy(&mraw).expect("骨架解析失败");
    let anim = parse_ani(&araw).expect("动作解析失败");
    let mut stat: Vec<Option<(f32, f32)>> = vec![None; h.bones.len()];
    let step = (anim.frames / 12).max(1);
    let mut f = 0;
    while f < anim.frames {
        let world = pose::pose_frame(&h, &anim, f);
        for (i, b) in h.bones.iter().enumerate() {
            let Some(p) = b.parent else { continue };
            let d = dist(&world[i], &world[p]);
            if d <= 1e-6 {
                continue;
            }
            let e = stat[i].get_or_insert((d, d));
            e.0 = e.0.min(d);
            e.1 = e.1.max(d);
        }
        f += step;
    }
    let ratios: Vec<f32> = stat
        .iter()
        .filter_map(|s| s.map(|(mn, mx)| mx / mn))
        .collect();
    let max = ratios.iter().copied().fold(1.0f32, f32::max);
    let bad = ratios.iter().filter(|r| **r > 1.05).count();
    Some((max, bad, ratios.len()))
}

fn dist(m: &[f32; 16], p: &[f32; 16]) -> f32 {
    let dx = m[12] - p[12];
    let dy = m[13] - p[13];
    let dz = m[14] - p[14];
    (dx * dx + dy * dy + dz * dz).sqrt()
}

#[test]
fn 纯旋转动作里骨长不许被拉长() {
    if !PathBuf::from("D:/TLGL/data.pak").is_file() {
        eprintln!("跳过：本机没有客户端 data.pak");
        return;
    }
    for (name, hash) in [("idle01", IDLE01), ("behit01", BEHIT01)] {
        let (max, bad, n) = len_ratios(hash).expect("样本应在 data.pak 里");
        eprintln!("{name}: 最大距离比 {max:.3}，>5% 的骨 {bad}/{n}");
        assert!(
            max < 1.12,
            "{name}：某根骨到父骨的距离被拉开到 {max:.3} 倍——合成或平移通道改坏了"
        );
        assert!(
            bad <= 3,
            "{name}：{bad}/{n} 根骨的距离波动 >5%，只允许根骨/脚步这类带平移通道的骨"
        );
    }
}
