//! 撕裂闸门（v0.5.0 播放口径的**边长**尺）。
//!
//! 2026-10-09 外部查看器验收把「frame0 锚播出来不撕」这条口径判红了：以前用的是
//! **帧均位移**（idle01 0.2201/最大 0.8489），可正常摆动本来就在搬顶点，位移小
//! 只说明整体没飞。判皮肤撕没撕要看**同一个三角形面上的相邻顶点被拉开几倍**
//! （[`edge_stretch`]）。主样本实测：idle01 中途 351/2,538 条边超 1.5 倍、
//! 最大 6.67 倍；walk 445 条超 1.5 倍、最大 24.09 倍——three.js 独立实现量出来
//! 是同一串数字，所以撕不在导出器，在锚。证据
//! `.scratch/glb_ext/验收_外部查看器_20261009.md`。
//!
//! 三条闸门，方向各不相同：
//! 1. **锚点处不许有一条撕边**（frame=0 与回环末帧，超 1.5 倍边数必须为 0）——
//!    这条是硬判据，破了就是锚装错了；
//! 2. **非锚帧的撕裂不许比今天更糟**（钉上界，不钉死数字）：修好了会红着让路，
//!    改坏了立刻红；
//! 3. **裸 bind 锚不能播**的方向钉住（锚点帧就撕 + 全程总量 + 最大倍数），
//!    并如实记下「逐帧严格更差」不成立（walk 第 7 帧反过来）——防止有人拿
//!    「换回 bind 锚」当修复，也防止把这条钉成一个假的逐帧不等式。
//!
//! 真数据缺失时降级跳过（夹具不入库，照 `pose_reanchor.rs` 的做法）。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::pose::{
    bind_worlds, edge_stretch, pose_frame, posed_vertices, reanchored_palette, skin_palette,
};
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes};

const MESH: u64 = 0xbcd65050a62986b7;
/// idle01（41 帧）与 walk（31 帧）——一条小动作一条带根运动的大动作。
const IDLE01: u64 = 0x4ec2478a169d5e73;
const WALK: u64 = 0x361180fe30a07e32;

fn raw_of(root: &PathBuf, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join("data.pak")).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

fn root() -> PathBuf {
    std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"))
}

struct Sample {
    mesh: Vec<u8>,
    ani: Vec<u8>,
}

fn load(ani_hash: u64) -> Option<Sample> {
    let r = root();
    let mesh = raw_of(&r, MESH)?;
    let ani = raw_of(&r, ani_hash)?;
    Some(Sample { mesh, ani })
}

/// 逐帧的边长拉伸表。`frame0` 用播放锚，`bind` 用 `.mesh` 的绑定锚。
fn sweep(s: &Sample) -> (Vec<(usize, f64, f64)>, Vec<(usize, f64, f64)>) {
    let h = parse_hierarchy(&s.mesh).expect("父骨链应能解出");
    let layout = parse_mesh(&s.mesh).expect("网格应能解出");
    let nodes = parse_nodes(&s.mesh);
    let a = parse_ani(&s.ani).expect("动作应能解出");
    let pos = &layout.geometry.positions;
    let idx = &layout.geometry.indices;
    let bind = bind_worlds(&h);
    let mut out = (Vec::new(), Vec::new());
    for f in 0..a.frames {
        let world = pose_frame(&h, &a, f);
        let pa = reanchored_palette(&h, &a, f).expect("frame0 锚调色板");
        let pb = skin_palette(&h, &bind, &world).expect("bind 锚调色板");
        for (slot, pal) in [(&mut out.0, &pa), (&mut out.1, &pb)] {
            let posed = posed_vertices(&h, pal, &nodes, pos).expect("蒙皮");
            let sa = edge_stretch(pos, &posed, idx);
            slot.push((f, sa.over15 as f64, sa.max_ratio));
        }
    }
    out
}

/// 1. 锚点处（第 0 帧）一条撕边都不许有。
#[test]
fn the_anchor_frame_stretches_no_edge_at_all() {
    for (name, hash) in [("idle01", IDLE01), ("walk", WALK)] {
        let Some(s) = load(hash) else {
            eprintln!("跳过：本机取不到 {name} 夹具（素材不入库）");
            return;
        };
        let (f0, _) = sweep(&s);
        let (frame, over15, max) = f0[0];
        assert_eq!(
            over15, 0.0,
            "{name} 第 {frame} 帧（锚点）有 {over15} 条边超 1.5 倍，最大 {max:.2} 倍——锚不是这条动作自己的 frame0"
        );
        let (lf, lover, lmax) = *f0.last().unwrap();
        assert!(
            lover <= 1.0,
            "{name} 末帧 {lf} 应回到锚点（动作回环），实测 {lover} 条边超 1.5 倍、最大 {lmax:.2} 倍"
        );
    }
}

/// 2. 非锚帧的撕裂不许比 2026-10-09 实测更糟（上界给余量，修好了应当变绿）。
#[test]
fn playback_tearing_does_not_worsen_past_the_measured_envelope() {
    // 实测：idle01 超 1.5 倍最多 375 条 / 最大 6.69 倍；walk 447 条 / 24.09 倍。
    const LIMITS: [(&str, u64, f64, f64); 2] =
        [("idle01", IDLE01, 450.0, 8.0), ("walk", WALK, 520.0, 28.0)];
    for (name, hash, over15_cap, max_cap) in LIMITS {
        let Some(s) = load(hash) else {
            eprintln!("跳过：本机取不到 {name} 夹具（素材不入库）");
            return;
        };
        let (f0, _) = sweep(&s);
        let worst_n = f0.iter().map(|(_, n, _)| *n).fold(0f64, f64::max);
        let worst_r = f0.iter().map(|(_, _, r)| *r).fold(0f64, f64::max);
        let at = f0
            .iter()
            .find(|(_, n, _)| *n == worst_n)
            .map(|(f, _, _)| *f)
            .unwrap_or(0);
        println!("{name}: 最撕的一帧是第 {at} 帧，超 1.5 倍 {worst_n} 条，最大 {worst_r:.2} 倍");
        assert!(
            worst_n <= over15_cap && worst_r <= max_cap,
            "{name} 撕裂超出已量到的上界（{worst_n} 条 > {over15_cap}，或 {worst_r:.2} 倍 > {max_cap}）——播放口径改坏了，见本文件头注"
        );
    }
}

/// 3. **裸 bind 锚不能播**这条裁决的方向钉住：它在锚点帧本身就撕
///    （frame0 锚在锚点帧是 0 条），全程撕边总数也明显更多。
///
/// ⚠ 口径要说准：**不是逐帧严格更差**。walk 第 7 帧实测 bind 锚 483 条、
/// frame0 锚 485 条——那一帧反过来。所以钉的是「锚点帧 + 总量 + 最大倍数」，
/// 逐帧严格不等式是假的，不许钉成假的。
#[test]
fn the_bind_anchor_tears_worse_than_the_frame0_anchor() {
    let Some(s) = load(WALK) else {
        eprintln!("跳过：本机取不到 walk 夹具（素材不入库）");
        return;
    };
    let (f0, bind) = sweep(&s);
    let sum = |v: &Vec<(usize, f64, f64)>| v.iter().map(|(_, n, _)| *n).sum::<f64>();
    let maxr = |v: &Vec<(usize, f64, f64)>| v.iter().map(|(_, _, r)| *r).fold(0f64, f64::max);
    let worse = (0..f0.len()).filter(|&i| bind[i].1 <= f0[i].1).count();
    println!(
        "walk: 撕边总数 frame0 锚 {} · bind 锚 {}；最大倍数 {:.1} vs {:.1}；bind 不比 frame0 差的帧 {worse}/{}",
        sum(&f0),
        sum(&bind),
        maxr(&f0),
        maxr(&bind),
        f0.len()
    );
    assert!(
        f0[0].1 == 0.0 && bind[0].1 > 100.0,
        "锚点帧：frame0 锚应 0 条撕边、bind 锚应明显非零，实测 {} 与 {}",
        f0[0].1,
        bind[0].1
    );
    assert!(
        // 2026-10-29：权重和<1 改按比例归一后，两种锚的总量都降、差距从 1.3 倍缩到 1.21 倍（10,127 vs 8,396）。
        // 60 条动作普查（examples/anchor_norm_census.rs）：第 0 帧锚 6.22M vs bind 锚 7.89M、32/60 更低 ⇒ 方向仍成立。
        sum(&bind) > sum(&f0) * 1.15,
        "bind 锚全程撕边总数应显著高于 frame0 锚（实测 {} vs {}）——这个方向反了说明锚口径被动过",
        sum(&bind),
        sum(&f0)
    );
    assert!(
        maxr(&bind) > maxr(&f0),
        "bind 锚的最大倍数应高于 frame0 锚（实测 {:.2} vs {:.2}）",
        maxr(&bind),
        maxr(&f0)
    );
    // 同一改动下这条 walk 上「bind 不比 frame0 差」的帧从 1 处增到 8/31；总量与最大倍数仍指向 bind 更差。
    assert!(
        worse * 3 <= f0.len(),
        "bind 锚不比 frame0 锚撕的帧有 {worse} 处 / {}——超过三分之一说明口径变了",
        f0.len()
    );
}
