//! 静态区反解重建闸门（2026-10-07）。`.ani` 骨架静态区把无 96B 记录骨的 bind 位置
//! 补出来（口径与证据见 `crates/core/src/preview/rest.rs` 与
//! `.scratch/ani_axis/锚点判定_20261007.md` §二/§三）。真容器字节钉四件事：
//!
//! 1. 主样本（46 骨怪）：自检命中率 15/20（miss 的 5 根 = 根运动 pelvis + 武器/挂件
//!    链 bone01/bone08/bone09/bone10_mirror02_mirror01，与研究班一致）；
//! 2. 补全：无记录的 16 根里 15 根拿到位置（footsteps 轨道平移非常量，不硬给），
//!    骨线 20 → 45 条，头颈链（spine→spine1→neck→head）与手臂链完整；
//! 3. 解剖对账：重建位全部有限、父子距 ≤ 4.5（骨长量级）、头颈自下而上单调；
//! 4. 跨怪复现：heihou（29 骨）13/16、duchanchu（26 骨）14/16——命中率如实进断言；
//!    拿错怪的静态区（轨道名对不上骨架）→ 整体 `None`，不硬给。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::rest::{rebuild_bind_positions, RestSource};
use tlbb_core::preview::{parse_ani, parse_hierarchy, rest_poses};

/// w1351_monster_xiyuqiezei：主样本（yifu_001.mesh + behit01.ani——消费路径取
/// 同组按名排序的第一条动作，这里与其同源。注意轨道常量逐动作略有出入：
/// walk 的 r_upperarm 平移常量与 bind 差 0.031，命中率会从 15 掉到 14，
/// 闸门按 ≥2/3 兜住这种波动）
const MESH: u64 = 0xbcd65050a62986b7;
const ANI: u64 = 0x1a2545b8c7c1d09a;
/// w1351_caiji_heihou_01：跨怪 1（29 骨）
const MESH_HEIHOU: u64 = 0x9eee824e77088ebc;
const ANI_HEIHOU: u64 = 0x955c4ec855257de4;
/// w1351_caiji_duchanchu_01：跨怪 2（26 骨）
const MESH_DUCHANCHU: u64 = 0xd68f6f2e9f55c3da;
const ANI_DUCHANCHU: u64 = 0x21ecff4206786170;

fn raw_of(root: &PathBuf, pak: &str, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

fn sample(hash_mesh: u64, hash_ani: u64) -> Option<(Vec<u8>, Vec<u8>)> {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    Some((raw_of(&root, "data", hash_mesh)?, raw_of(&root, "data", hash_ani)?))
}

fn dist(a: [f32; 3], b: [f32; 3]) -> f32 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

/// 骨线对（父, 子）名对：两端都有位置才算一条线。
fn line_pairs(
    h: &tlbb_core::preview::SkeletonHierarchy,
    pos: &[Option<[f32; 3]>],
) -> Vec<(String, String)> {
    let mut out = Vec::new();
    for (i, b) in h.bones.iter().enumerate() {
        let Some(p) = b.parent else { continue };
        if pos.get(p).copied().flatten().is_some() && pos[i].is_some() {
            out.push((h.bones[p].name.clone(), b.name.clone()));
        }
    }
    out
}

#[test]
fn 主样本_自检命中率与解剖对账() {
    let Some((mesh, ani)) = sample(MESH, ANI) else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("主样本应解出挂接");
    let a = parse_ani(&ani).expect("动作应解出");
    let rests = rest_poses(&ani).expect("静态区应解出");
    let rb = rebuild_bind_positions(&h, &a, &rests).expect("自检应通过");

    // —— 自检命中率（研究班实测 15/20，miss = pelvis + 武器/挂件链）——
    assert_eq!(rb.stats.clean_bones, 20, "干净记录骨数");
    assert_eq!(rb.stats.rotation_hits, 15, "qrest 旋转语义命中");
    assert_eq!(rb.stats.translation_hits, 15, "轨道常量平移语义命中");
    eprintln!(
        "主样本自检：干净 {}/旋转命中 {}/平移命中 {}",
        rb.stats.clean_bones, rb.stats.rotation_hits, rb.stats.translation_hits
    );

    // —— 补全：16 根无记录骨里 15 根拿到位置，footsteps 保持 None ——
    let missing: Vec<&str> = h
        .bones
        .iter()
        .filter(|b| b.bind.is_none())
        .map(|b| b.name.as_str())
        .collect();
    assert_eq!(missing.len(), 16);
    assert_eq!(rb.stats.solved + rb.stats.fallback, 15, "反解+顺推补上的骨数");
    assert_eq!(rb.stats.unresolved, 1, "只有 footsteps 补不上");
    let footsteps = h.bones.iter().position(|b| b.name == "bip01_footsteps").unwrap();
    assert_eq!(rb.positions[footsteps], None, "轨道平移非常量的骨不硬给");
    assert_eq!(rb.sources[footsteps], RestSource::Unresolved);
    for name in [
        "000",
        "bip01_spine1",
        "bip01_neck",
        "bip01_head",
        "bip01_l_clavicle",
        "bip01_l_forearm",
        "bip01_l_finger0",
        "bip01_r_finger1",
        "bip01_l_thigh",
        "bip01_r_thigh",
        "bone10",
        "bone10_mirror01",
    ] {
        let j = h.bones.iter().position(|b| b.name == name).unwrap();
        assert!(rb.positions[j].is_some(), "{name} 应补上位置");
    }

    // —— 头颈链：自下而上单调（站立解剖高度；网格 bbox 顶 2.240）——
    let y = |name: &str| {
        let j = h.bones.iter().position(|b| b.name == name).unwrap();
        rb.positions[j].expect(name)[1]
    };
    let (pelvis_y, spine1_y, neck_y, head_y) =
        (y("bip01_pelvis"), y("bip01_spine1"), y("bip01_neck"), y("bip01_head"));
    assert!(
        pelvis_y < spine1_y && spine1_y < neck_y && neck_y < head_y,
        "头颈链应自下而上单调：{pelvis_y} < {spine1_y} < {neck_y} < {head_y}"
    );
    assert!(
        (1.95..=2.20).contains(&head_y),
        "head 应在颅底高度（实测 2.09，网格顶 2.240），实际 {head_y}"
    );
    eprintln!(
        "主样本重建高度：spine1 y={spine1:.4} neck y={neck:.4} head y={head:.4}",
        spine1 = spine1_y,
        neck = neck_y,
        head = head_y
    );

    // —— 镜像对账：l_clavicle/l_forearm 的反解位与对侧存储位镜像吻合 ——
    assert!(rb.stats.mirror_checked >= 2, "至少查 clavicle/forearm 两对");
    assert_eq!(rb.stats.mirror_checked, rb.stats.mirror_matched, "全部吻合");
    let pos_of = |name: &str| {
        let j = h.bones.iter().position(|b| b.name == name).unwrap();
        rb.positions[j].expect(name)
    };
    let (l, r) = (pos_of("bip01_l_clavicle"), pos_of("bip01_r_clavicle"));
    assert!((l[1] - r[1]).abs() < 1e-3 && (l[2] - r[2]).abs() < 1e-3 && (l[0] + r[0]).abs() < 1e-2,
        "l_clavicle 反解位应与 r_clavicle 存储位镜像：{l:?} vs {r:?}");

    // —— 解剖对账：全部重建位有限、父子距 ≤ 4.5 ——
    for (i, b) in h.bones.iter().enumerate() {
        let Some(p) = rb.positions[i] else { continue };
        assert!(p.iter().all(|v| v.is_finite()), "{} 位置非有限", b.name);
        if let Some(pp) = b.parent.and_then(|k| rb.positions[k]) {
            let d = dist(p, pp);
            assert!(d <= 4.5, "{} 到父骨距离 {d} 超出骨长量级", b.name);
        }
    }

    // —— 骨线：改前 20 条（记录骨互联）→ 改后 45 条 ——
    let before = h
        .bones
        .iter()
        .filter(|b| b.bind.is_some())
        .filter(|b| b.parent.map(|p| h.bones[p].bind.is_some()).unwrap_or(false))
        .count();
    let after = line_pairs(&h, &rb.positions);
    assert_eq!(before, 20, "改前只有记录骨互联");
    assert_eq!(after.len(), 44, "补全后骨线显著增加（45 对里只缺 footsteps 一对）");
    assert!(
        !after.iter().any(|(a, b)| a == "bip01" && b == "bip01_footsteps"),
        "footsteps 没有位置，bip01→footsteps 这条线不该出现"
    );
    let has = |a: &str, b: &str| after.iter().any(|(x, y)| x == a && y == b);
    assert!(has("bip01_spine", "bip01_spine1"), "头颈链 spine→spine1");
    assert!(has("bip01_spine1", "bip01_neck"), "头颈链 spine1→neck");
    assert!(has("bip01_neck", "bip01_head"), "头颈链 neck→head");
    assert!(has("bip01_l_clavicle", "bip01_l_upperarm"), "手臂链 clavicle→upperarm");
    assert!(has("bip01_l_upperarm", "bip01_l_forearm"), "手臂链 upperarm→forearm");
    assert!(has("bip01_l_forearm", "bip01_l_hand"), "手臂链 forearm→hand");
    eprintln!("主样本骨线：{before} → {} 条（const_mismatches={}，如实报数不当闸门）",
        after.len(), rb.stats.const_mismatches);
}

/// 跨怪复现：heihou（29 骨）与 duchanchu（26 骨）跑同一道自检，命中率如实钉进断言。
#[test]
fn 跨怪复现_命中率如实() {
    for (tag, hm, ha, clean, rot, tr, missing_n, filled) in [
        ("heihou", MESH_HEIHOU, ANI_HEIHOU, 16usize, 13usize, 12usize, 7usize, 7usize),
        ("duchanchu", MESH_DUCHANCHU, ANI_DUCHANCHU, 16, 14, 14, 5, 5),
    ] {
        let Some((mesh, ani)) = sample(hm, ha) else {
            eprintln!("跳过：{tag} 的资源不在本机容器里");
            continue;
        };
        let h = parse_hierarchy(&mesh).unwrap_or_else(|| panic!("{tag} 应解出挂接"));
        let a = parse_ani(&ani).unwrap_or_else(|| panic!("{tag} 动作应解出"));
        let rests = rest_poses(&ani).unwrap_or_else(|| panic!("{tag} 静态区应解出"));
        let Some(rb) = rebuild_bind_positions(&h, &a, &rests) else {
            panic!("{tag} 自检应通过（命中率见研究班 k3_vote）");
        };
        assert_eq!(rb.stats.clean_bones, clean, "{tag} 干净骨");
        assert_eq!(rb.stats.rotation_hits, rot, "{tag} 旋转命中");
        assert_eq!(rb.stats.translation_hits, tr, "{tag} 平移命中");
        assert_eq!(
            rb.stats.solved + rb.stats.fallback,
            filled,
            "{tag} 补上的骨数（缺失 {missing_n}）"
        );
        for (i, b) in h.bones.iter().enumerate() {
            if let Some(p) = rb.positions[i] {
                assert!(p.iter().all(|v| v.is_finite()), "{tag} {} 非有限", b.name);
                if let Some(pp) = b.parent.and_then(|k| rb.positions[k]) {
                    assert!(dist(p, pp) <= 4.5, "{tag} {} 父子距 {}", b.name, dist(p, pp));
                }
            }
        }
        eprintln!(
            "{tag}：干净 {} 旋转 {rot} 平移 {tr} · 缺失 {missing_n} 补上 {} · 镜像 {}/{}",
            rb.stats.clean_bones, filled, rb.stats.mirror_matched, rb.stats.mirror_checked
        );
    }
}

/// 拿错怪的静态区：heihou 的动作喂给 xiyuqiezei 的骨架——轨道名对不上 → 整体 None。
/// 这是「另一只怪的静态区布局不同就不硬给」红线的落码形态。
#[test]
fn 错怪的静态区整体回退() {
    let Some((mesh, ani_heihou)) = sample(MESH, ANI_HEIHOU) else {
        eprintln!("跳过：本机没有 data.pak");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("主样本应解出挂接");
    let a = parse_ani(&ani_heihou).expect("heihou 动作应解出");
    let rests = rest_poses(&ani_heihou).expect("heihou 静态区应解出");
    assert_eq!(
        rebuild_bind_positions(&h, &a, &rests),
        None,
        "heihou 的轨道名对不上 xiyuqiezei 的骨架，必须整体回退"
    );
}
