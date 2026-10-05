//! 父骨链闸门（2026-10-05）。`.mesh` 尾部的父子挂接已解出（口径与字节证据见
//! `crates/core/src/preview/geometry.rs` 的 `parse_hierarchy` 注释块），
//! 这份测试用真容器字节（data.pak）钉住四条硬证据 + 一条反向验红：
//!
//! 1. 主样本（46 骨的怪）：条目数 = 头部声明数、单根、无环、每个非根骨恰有一个父；
//! 2. 父链与 Biped 解剖一致（thigh→calf→foot→toe0、clavicle→upperarm→forearm…）；
//! 3. 几何对账：全部「父子都有绑定矩阵」的对，|Δ位移| 落在骨长量级，三个手算值
//!    （pelvis←bip01 = 1.0991、foot←calf = 0.4052、toe0←foot = 0.5460）逐一对上；
//! 4. 差分样本（25 骨）同样走通——口径不挑模型；
//! 5. 验红：把 bip01 的孩子记录 `bip01_pelvis` 改名，孩子名对不上条目 → 整体拒绝。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{bone_count, parse_ani, parse_hierarchy};

/// w1351_monster_xiyuqiezei_yifu_001.mesh：46 骨主样本
const MESH: u64 = 0xbcd65050a62986b7;
/// w1351_monster_xiyuqiezei_walk.ani：同怪走路动作（对骨名表）
const ANI: u64 = 0x361180fe30a07e32;
/// w1351_monster_baimaocaoren_yifu_001.mesh：25 骨差分样本
const MESH2: u64 = 0x56b92d10b2d7b4a4;

fn raw_of(root: &PathBuf, pak: &str, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

fn mesh_bytes(hash: u64) -> Option<Vec<u8>> {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    raw_of(&root, "data", hash)
}

/// 名字段固定 32 字节：找某名字在原文里的（第一处）位置。
fn slot_of(raw: &[u8], name: &str) -> Option<usize> {
    let mut needle = [0u8; 32];
    needle[..name.len()].copy_from_slice(name.as_bytes());
    raw.windows(32).position(|w| w == needle)
}

fn parent_name<'a>(h: &'a tlbb_core::preview::SkeletonHierarchy, name: &str) -> Option<&'a str> {
    let b = h.bones.iter().find(|b| b.name == name)?;
    b.parent.map(|p| h.bones[p].name.as_str())
}

fn by_name<'a>(h: &'a tlbb_core::preview::SkeletonHierarchy, name: &str) -> &'a tlbb_core::preview::BoneNode {
    h.bones.iter().find(|b| b.name == name).expect("骨架里该有这根骨")
}

/// 主样本：46 根、单根 `000`、无环、除根外每个骨的 parent 都是合法下标。
#[test]
fn hierarchy_is_a_single_rooted_tree_of_declared_size() {
    let Some(mesh) = mesh_bytes(MESH) else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let declared = bone_count(&mesh).expect("头部该有骨骼数");
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    assert_eq!(h.bones.len(), declared, "解出的骨数应等于头部声明");
    assert_eq!(declared, 46, "主样本声明 46 根骨");
    let roots: Vec<&str> = h.bones.iter().filter(|b| b.parent.is_none()).map(|b| b.name.as_str()).collect();
    assert_eq!(roots, vec!["000"], "唯一根是 000");
    // 每个非根骨的 parent 指回一个存在的骨，且不构成环（向上走到根必须有出口）。
    for b in &h.bones {
        let mut cur = Some(b);
        let mut steps = 0;
        while let Some(x) = cur {
            assert!(steps <= h.bones.len(), "沿父链走超过节点数，有环：{}", b.name);
            steps += 1;
            cur = x.parent.map(|p| &h.bones[p]);
        }
        if b.name != "000" {
            assert!(b.parent.is_some(), "{} 没有父骨", b.name);
        }
    }
    // 绑定矩阵：46 根里 30 根带 96B 记录（2026-09-29 实测值），其余以名字挂在孩子名单里。
    let with_bind = h.bones.iter().filter(|b| b.bind.is_some()).count();
    assert_eq!(with_bind, 30, "带绑定矩阵的骨应为 30 根，实际 {with_bind}");
    // 挂点表：4 条，名字与骨名对得上主样本的实测。
    assert_eq!(h.sockets.len(), 4);
    assert_eq!(h.sockets[0].name, "tx_head");
    assert_eq!(h.sockets[0].bone, "Bip01_Head");
}

/// 父链与 Biped 解剖一致——这些关系直接从文件的孩子名单读出，不是按名字猜的。
#[test]
fn parent_chain_follows_biped_anatomy() {
    let Some(mesh) = mesh_bytes(MESH) else {
        eprintln!("跳过：本机没有 data.pak");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let expect = [
        ("bip01", "000"),
        ("bip01_pelvis", "bip01"),
        ("bip01_spine", "bip01_pelvis"),
        ("bip01_spine1", "bip01_spine"),
        ("bip01_neck", "bip01_spine1"),
        ("bip01_head", "bip01_neck"),
        ("bip01_l_clavicle", "bip01_neck"),
        ("bip01_l_upperarm", "bip01_l_clavicle"),
        ("bip01_l_forearm", "bip01_l_upperarm"),
        ("bip01_l_hand", "bip01_l_forearm"),
        ("bip01_l_finger0", "bip01_l_hand"),
        ("bip01_l_thigh", "bip01_spine"),
        ("bip01_l_calf", "bip01_l_thigh"),
        ("bip01_l_foot", "bip01_l_calf"),
        ("bip01_l_toe0", "bip01_l_foot"),
        ("bip01_r_thigh", "bip01_spine"),
        ("bip01_r_calf", "bip01_r_thigh"),
        ("bip01_r_foot", "bip01_r_calf"),
        ("bip01_r_toe0", "bip01_r_foot"),
        ("bone10", "bip01_spine"),
        ("bone11", "bone10"),
        ("bone12", "bone11"),
        ("bone05", "bip01_spine1"),
        ("bone06", "bone05"),
        ("bone07", "bone06"),
    ];
    for (child, parent) in expect {
        assert_eq!(
            parent_name(&h, child),
            Some(parent),
            "{child} 的父骨应为 {parent}"
        );
    }
    // 孩子名单抽验：bip01 的孩子 = footsteps + pelvis；spine 挂着 spine1 和两条 thigh。
    let kids = |name: &str| -> Vec<String> {
        by_name(&h, name)
            .children
            .iter()
            .map(|&i| h.bones[i].name.clone())
            .collect()
    };
    assert_eq!(kids("bip01"), vec!["bip01_footsteps", "bip01_pelvis"]);
    let spine_kids = kids("bip01_spine");
    for k in ["bip01_spine1", "bip01_l_thigh", "bip01_r_thigh", "bone10"] {
        assert!(spine_kids.contains(&k.to_string()), "spine 的孩子里该有 {k}");
    }
}

/// 几何对账：父子都有绑定矩阵的对，绑定位移差落在骨长量级；三个 2026-09-29
/// 手算出的值（当时还不知道链，只量了距离）逐一复现。
#[test]
fn bind_distance_between_parent_and_child_stays_in_bone_length_range() {
    let Some(mesh) = mesh_bytes(MESH) else {
        eprintln!("跳过：本机没有 data.pak");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let mut pairs = 0;
    let mut over2 = Vec::new();
    for b in &h.bones {
        let Some(p) = b.parent else { continue };
        let (Some(bc), Some(bp)) = (b.bind, h.bones[p].bind) else {
            continue;
        };
        let d = ((bc[12] - bp[12]).powi(2) + (bc[13] - bp[13]).powi(2) + (bc[14] - bp[14]).powi(2))
            .sqrt();
        pairs += 1;
        assert!(d > 1e-3, "{} 与父骨的绑定位移重合，链有误", b.name);
        if d > 2.0 {
            over2.push((b.name.clone(), d));
        }
    }
    assert!(pairs >= 15, "父子都有矩阵的对太少（{pairs}）");
    // 三个超 2.0 的例外全是 accessory 链（武器/挂件）或这只怪的长臂：
    assert_eq!(over2.len(), 3, "超 2.0 的对数变了：{over2:?}");
    // 手算值复现（2026-09-29 的表，当时只有距离没有链）：
    let dist = |child: &str, parent: &str| {
        let bc = by_name(&h, child).bind.expect("该骨应有绑定矩阵");
        let bp = by_name(&h, parent).bind.expect("该骨应有绑定矩阵");
        ((bc[12] - bp[12]).powi(2) + (bc[13] - bp[13]).powi(2) + (bc[14] - bp[14]).powi(2)).sqrt()
    };
    // 容差给 2e-3：浮点建模不对称的量级（与 node_tests::near 一致）。
    assert!((dist("bip01_pelvis", "bip01") - 1.0991).abs() < 2e-3);
    assert!((dist("bip01_l_foot", "bip01_l_calf") - 0.4052).abs() < 2e-3);
    assert!((dist("bip01_l_toe0", "bip01_l_foot") - 0.5460).abs() < 2e-3);
}

/// 差分：骨数不同的第二份网格（25 骨）用同一套口径同样走通。
#[test]
fn second_mesh_with_different_bone_count_parses_the_same_way() {
    let Some(mesh) = mesh_bytes(MESH2) else {
        eprintln!("跳过：本机没有 data.pak 或差分样本不在里面");
        return;
    };
    let declared = bone_count(&mesh).expect("头部该有骨骼数");
    assert_eq!(declared, 25, "差分样本声明 25 根骨");
    let h = parse_hierarchy(&mesh).expect("差分样本也应能解出父骨链");
    assert_eq!(h.bones.len(), declared);
    let roots: Vec<&str> = h.bones.iter().filter(|b| b.parent.is_none()).map(|b| b.name.as_str()).collect();
    assert_eq!(roots.len(), 1, "差分样本也应单根");
    for b in &h.bones {
        let mut cur = Some(b);
        let mut steps = 0;
        while let Some(x) = cur {
            assert!(steps <= h.bones.len(), "有环：{}", b.name);
            steps += 1;
            cur = x.parent.map(|p| &h.bones[p]);
        }
    }
}

/// 骨架名字集盖住 `.ani` 的全部轨道——播放时按名字把轨道挂到父链上即可。
#[test]
fn hierarchy_names_cover_the_ani_tracks() {
    let Some((mesh, ani)) = mesh_bytes(MESH).zip(mesh_bytes(ANI)) else {
        eprintln!("跳过：本机没有 data.pak");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let a = parse_ani(&ani).expect("动作应能解出");
    assert_eq!(a.bones, h.bones.len(), "轨道数应等于骨数");
    for t in &a.tracks {
        if t.bone.is_empty() {
            continue;
        }
        assert!(
            h.bones.iter().any(|b| b.name == t.bone),
            ".ani 轨道 {} 在骨架里找不到",
            t.bone
        );
    }
}

/// 反向验红：把 bip01 的孩子记录 `bip01_pelvis` 改名（只动那 32 字节名字段），
/// 孩子名就对不上条目了——整棵树多出一个没人引用的根，`parse_hierarchy` 必须拒绝。
#[test]
fn tampering_a_child_slot_breaks_the_parse() {
    let Some(mut mesh) = mesh_bytes(MESH) else {
        eprintln!("跳过：本机没有 data.pak");
        return;
    };
    assert!(parse_hierarchy(&mesh).is_some(), "未改动的样本应能解出");
    // 第一处 `bip01_pelvis` 就是那条 96B 孩子记录（0x78bc），后面跟的是矩阵；
    // 确认是记录再改名，改名后名字段仍是合法 ASCII + NUL 填充。
    let at = slot_of(&mesh, "bip01_pelvis").expect("名字槽应在原文里");
    assert_eq!(&mesh[at + 32 + 60..at + 32 + 64], &1.0f32.to_le_bytes(), "第一处应是带矩阵的记录");
    mesh[at..at + 13].copy_from_slice(b"bip01_pelvis2");
    assert!(
        parse_hierarchy(&mesh).is_none(),
        "改了孩子槽的名字还能解出，闸门是假的"
    );
}
