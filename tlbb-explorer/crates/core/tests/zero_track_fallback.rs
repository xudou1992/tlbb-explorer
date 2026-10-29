//! 全零轨道回退：`w1351_model_jingji_r_h03` 的动作静态区对部分骨写的是
//! 四元数 (0,0,0,0) + 缩放 0。照用会得到零矩阵、逆不出蒙皮调色板，整份动作被拒。
//! 修法是把这种记录当「没有这条轨道」，回退到绑定姿态/恒等。
//!
//! 真数据缺失时降级跳过（夹具不入库，照 `stretch_gate.rs` 的做法）。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, pose};

const MESH: u64 = 0x9dfd99ef62e5bc21;
const ANI: u64 = 0x6e7ed282b8240397;

fn raw_of(root: &PathBuf, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join("data.pak")).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}


#[test]
fn 全零轨道回退后每根骨的矩阵都可逆() {
    let root = PathBuf::from("D:/TLGL");
    if !root.join("data.pak").is_file() {
        eprintln!("跳过：本机没有客户端 data.pak");
        return;
    }
    let mraw = raw_of(&root, MESH).expect("样本网格应在 data.pak 里");
    let araw = raw_of(&root, ANI).expect("样本动作应在 data.pak 里");
    let h = parse_hierarchy(&mraw).expect("骨架解析失败");
    let anim = parse_ani(&araw).expect("动作解析失败");
    for f in [0usize, anim.frames / 2, anim.frames.saturating_sub(1)] {
        let world = pose::pose_frame(&h, &anim, f);
        let bad: Vec<&str> = world
            .iter()
            .enumerate()
            .filter(|(_, m)| pose::mat_inverse_affine(m).is_none())
            .map(|(i, _)| h.bones[i].name.as_str())
            .collect();
        assert!(
            bad.is_empty(),
            "第 {f} 帧还有不可逆的骨：{bad:?}（全零轨道回退没生效）"
        );
        assert!(
            world.iter().flat_map(|m| m.iter()).all(|v| v.is_finite()),
            "第 {f} 帧矩阵出现非有限值"
        );
    }
}
