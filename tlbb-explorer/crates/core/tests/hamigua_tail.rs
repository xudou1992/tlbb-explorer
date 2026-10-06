//! hamigua 尾部变体闸门（2026-10-05）。`.mesh` 尾部还有一族没有 origin/top 前奏的
//! 变体：根条目以 `[u32 -1][名字×2]` 直接开始、挂点段挂点数可以为 0、影响顶点表
//! 按「绘制序」（互异但有相邻交换的排列）而不是排序序存。字节证据与全库验证见
//! `crates/core/src/preview/geometry.rs` 的 `parse_hierarchy` 注释块与
//! `.scratch/hamigua_尾部变体_20261005.md`。真数据缺席时降级跳过。
//!
//! 1. 主样本 `w1351_caiji_hamigua_01`（2 骨）：无前奏也能整文件走到 EOF、
//!    条目数 = 声明数、挂点段收在 `[1][0]`；
//! 2. 家族大样本 `w1351_caiji_heihou_01`（29 骨）：链与 Biped 解剖一致 +
//!    16 对父子矩阵位移全带内 + 三个实测值逐对复现；
//! 3. 带挂点的变体 `w1351_model_fenghuang_h001`（43 骨、5 挂点）照常解出；
//! 4. 反向验红 ×2：改孩子槽名字 / 抹掉根条目的 -1 标志 → 整体拒绝；
//! 5. 挂点段锚定（2026-10-06）：合成样本——真挂点头 `[u32 1][u32 n]` + n×128B 收到
//!    EOF 照常解出；把收尾换成 `[u32 x≠1][u32 0]` 这种「假空挂点段」（旧口径会白收，
//!    条目链就此停在 EOF 之前）→ 必须整体拒绝。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{bone_count, parse_hierarchy, BoneNode, SkeletonHierarchy};

/// w1351_caiji_hamigua_01.mesh：族名样本，2 骨、无 origin/top、挂点数 0（data.pak）
const HAMIGUA: u64 = 0x9965146e8d18307d;
/// w1351_caiji_heihou_01.mesh：29 骨 bip01 家族样本（data.pak）
const HEIHOU: u64 = 0x9eee824e77088ebc;
/// w1351_model_fenghuang_h001.mesh：43 骨带 5 挂点的变体样本（data3.pak）
const FENGHUANG: u64 = 0xc246a7afd506c05e;

fn raw_of(pak: &str, hash: u64) -> Option<Vec<u8>> {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

fn by_name<'a>(h: &'a SkeletonHierarchy, name: &str) -> &'a BoneNode {
    h.bones.iter().find(|b| b.name == name).expect("骨架里该有这根骨")
}

fn parent_name<'a>(h: &'a SkeletonHierarchy, name: &str) -> Option<&'a str> {
    let b = h.bones.iter().find(|b| b.name == name)?;
    b.parent.map(|p| h.bones[p].name.as_str())
}

/// 主样本：2 骨、无前奏、挂点 0；bone001 的绑定矩阵来自根条目孩子名单里的记录槽。
#[test]
fn hamigua_mesh_without_origin_prelude_parses_to_exact_eof() {
    let Some(mesh) = raw_of("data", HAMIGUA) else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let declared = bone_count(&mesh).expect("头部该有骨骼数");
    assert_eq!(declared, 2, "hamigua 声明 2 根骨");
    // 变体特征自证：全文件没有名叫 origin 的 96B 记录，尾部直接 -1 起步。
    assert!(
        mesh.windows(36).all(|w| w[..4] != *b"origin\0\0"),
        "这份样本不该有 origin 记录"
    );
    let h = parse_hierarchy(&mesh).expect("变体应能解出");
    assert_eq!(h.bones.len(), declared, "条目数应等于头部声明数");
    let roots: Vec<&str> = h
        .bones
        .iter()
        .filter(|b| b.parent.is_none())
        .map(|b| b.name.as_str())
        .collect();
    assert_eq!(roots, vec!["000"], "唯一根是 000（根条目标志 -1 起步）");
    let bone001 = by_name(&h, "bone001");
    assert_eq!(bone001.parent, Some(0), "bone001 应挂在 000 下");
    assert_eq!(h.bones[0].children, vec![1], "000 的孩子名单里恰有 bone001");
    // 挂点数 0 的收尾：没有挂点不算失败。
    assert!(h.sockets.is_empty(), "hamigua 的挂点段是 [1][0]，应为空");
    // bone001 没有自己的 96B 记录，绑定矩阵来自「父条目孩子名单里那条记录」。
    let m = bone001.bind.expect("bone001 应带绑定矩阵");
    assert!((m[15] - 1.0).abs() < 1e-3, "齐次位应为 1");
    assert!(m[12].abs() < 1e-3 && m[13].abs() < 1e-3 && m[14].abs() < 1e-3, "绑定位移在原点");
}

/// 家族大样本：29 骨；链与 Biped 解剖一致（head 走 neck1 中间骨）；16 对
/// 「父子都有矩阵」的位移差全带内，三个实测值逐对复现（容差 2e-3）。
#[test]
fn variant_family_follows_biped_anatomy_and_bone_lengths() {
    let Some(mesh) = raw_of("data", HEIHOU) else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let declared = bone_count(&mesh).expect("头部该有骨骼数");
    assert_eq!(declared, 29, "heihou 声明 29 根骨");
    let h = parse_hierarchy(&mesh).expect("变体应能解出");
    assert_eq!(h.bones.len(), declared);
    let roots: Vec<&str> = h
        .bones
        .iter()
        .filter(|b| b.parent.is_none())
        .map(|b| b.name.as_str())
        .collect();
    assert_eq!(roots, vec!["000"]);
    let expect = [
        ("bip01", "000"),
        ("bip01_pelvis", "bip01"),
        ("bip01_spine", "bip01_pelvis"),
        ("bip01_spine1", "bip01_spine"),
        ("bip01_neck", "bip01_spine1"),
        ("bip01_neck1", "bip01_neck"),
        ("bip01_head", "bip01_neck1"),
        ("bip01_l_thigh", "bip01_spine"),
        ("bip01_l_calf", "bip01_l_thigh"),
        ("bip01_l_foot", "bip01_l_calf"),
        ("bip01_l_toe0", "bip01_l_foot"),
        ("bip01_r_calf", "bip01_r_thigh"),
        ("bip01_r_foot", "bip01_r_calf"),
        ("bip01_l_forearm", "bip01_l_upperarm"),
        ("bip01_l_hand", "bip01_l_forearm"),
    ];
    for (child, parent) in expect {
        assert_eq!(parent_name(&h, child), Some(parent), "{child} 的父骨应为 {parent}");
    }
    // 几何对账：父子都有矩阵的对，位移差落在骨长量级；三个实测值复现。
    let mut pairs = 0;
    for b in &h.bones {
        let Some(p) = b.parent else { continue };
        let (Some(bc), Some(bp)) = (b.bind, h.bones[p].bind) else {
            continue;
        };
        let d = ((bc[12] - bp[12]).powi(2) + (bc[13] - bp[13]).powi(2) + (bc[14] - bp[14]).powi(2))
            .sqrt();
        pairs += 1;
        assert!(d > 1e-3 && d <= 2.0, "{} 与父骨位移差 {:.4} 出带", b.name, d);
    }
    assert_eq!(pairs, 16, "父子双矩阵的对数变了");
    let dist = |child: &str, parent: &str| {
        let bc = by_name(&h, child).bind.expect("该骨应有绑定矩阵");
        let bp = by_name(&h, parent).bind.expect("该骨应有绑定矩阵");
        ((bc[12] - bp[12]).powi(2) + (bc[13] - bp[13]).powi(2) + (bc[14] - bp[14]).powi(2)).sqrt()
    };
    assert!((dist("bip01_r_upperarm", "bip01_r_clavicle") - 1.1017).abs() < 2e-3);
    assert!((dist("bip01_l_forearm", "bip01_l_upperarm") - 0.8503).abs() < 2e-3);
    assert!((dist("bip01_l_foot", "bip01_l_calf") - 0.3728).abs() < 2e-3);
}

/// 带挂点的变体：43 骨 + 挂点段 `[1][5]`，挂点名/骨名照常解出。
#[test]
fn variant_with_sockets_parses_sockets_too() {
    let Some(mesh) = raw_of("data3", FENGHUANG) else {
        eprintln!("跳过：本机没有 data3.pak 或这份资源不在里面");
        return;
    };
    let declared = bone_count(&mesh).expect("头部该有骨骼数");
    assert_eq!(declared, 43, "fenghuang 声明 43 根骨");
    let h = parse_hierarchy(&mesh).expect("变体应能解出");
    assert_eq!(h.bones.len(), declared);
    let roots: Vec<&str> = h
        .bones
        .iter()
        .filter(|b| b.parent.is_none())
        .map(|b| b.name.as_str())
        .collect();
    assert_eq!(roots, vec!["000"]);
    assert_eq!(h.sockets.len(), 5, "fenghuang 的挂点段声明 5 条");
    assert_eq!(h.sockets[0].name, "tx_head");
    assert_eq!(h.sockets[0].bone, "Bip001_Head");
    assert!(h.sockets.iter().all(|s| (s.bind[15] - 1.0).abs() < 1e-3));
}

/// 反向验红一：把根条目孩子名单里的记录槽 `bone001` 改名——孩子名对不上条目，
/// 多出没人引用的根，整体必须拒绝。
#[test]
fn tampering_child_slot_still_breaks_the_parse() {
    let Some(mut mesh) = raw_of("data", HAMIGUA) else {
        eprintln!("跳过：本机没有 data.pak");
        return;
    };
    assert!(parse_hierarchy(&mesh).is_some(), "未改动样本应能解出");
    // 第一处 bone001 名字槽就是孩子槽记录（后随矩阵，齐次位 1.0 在 +32+60）。
    let mut needle = [0u8; 32];
    needle[..7].copy_from_slice(b"bone001");
    let at = mesh.windows(32).position(|w| w == needle).expect("孩子槽应在原文里");
    assert_eq!(
        &mesh[at + 32 + 60..at + 32 + 64],
        &1.0f32.to_le_bytes(),
        "第一处应是带矩阵的记录槽"
    );
    mesh[at..at + 7].copy_from_slice(b"bone002");
    assert!(
        parse_hierarchy(&mesh).is_none(),
        "改了孩子槽名字还能解出，闸门是假的"
    );
}

/// 反向验红二：把根条目的 -1 标志抹掉——变体起点就没了（文件里也没有 origin），
/// 必须整体拒绝。
#[test]
fn tampering_root_flag_breaks_the_variant_start() {
    let Some(mut mesh) = raw_of("data", HAMIGUA) else {
        eprintln!("跳过：本机没有 data.pak");
        return;
    };
    assert!(parse_hierarchy(&mesh).is_some(), "未改动样本应能解出");
    // 根条目标志 = 第一个 "000" 名字槽前 4 字节，应为 ff ff ff ff。
    let mut needle = [0u8; 32];
    needle[..3].copy_from_slice(b"000");
    let at = mesh.windows(32).position(|w| w == needle).expect("根名应在原文里");
    assert!(at >= 4);
    assert_eq!(&mesh[at - 4..at], &[0xFF; 4], "根条目标志应为 -1");
    mesh[at - 4..at].copy_from_slice(&1u32.to_le_bytes());
    assert!(
        parse_hierarchy(&mesh).is_none(),
        "抹掉 -1 起点还能解出，闸门是假的"
    );
}

// === 挂点段的收束判据（2026-10-06）===========================================
// 尾部是「条目链 → 挂点段 → EOF」。挂点段真头 = `[u32 1][u32 挂点数]` + 挂点数×128B，
// 而且**正好收到文件尾**（`at + 8 + 128×count == len`）。老口径只把标志读出来丢掉、
// 要求 count ≤ 4096 且不越界，于是任何 `[x][00 00 00 00]` 收尾都被当「空挂点段」收下，
// 条目链就此停在 EOF 之前。下面两条用合成样本（不依赖 pak）把这条锚定钉住：
// 真头照收（正向）、假收尾必须拒（反向验红）。

/// 拼一份最小尾部：0x118 头（0x8C 顶点数、0x110 声明 1 骨）+ 根条目
/// `[u32 -1]["bone001"×2][u32 0 孩子]`，尾段由调用方给。
fn synth_one_bone(tail: &[u8]) -> Vec<u8> {
    let mut v = vec![0u8; 0x118 + 4 + 64 + 4];
    v[0x8C..0x90].copy_from_slice(&8u32.to_le_bytes()); // 顶点数（影响表判据要用）
    v[0x110..0x114].copy_from_slice(&1u32.to_le_bytes()); // 声明 1 根骨
    v[0x118..0x11c].copy_from_slice(&u32::MAX.to_le_bytes()); // 根条目标志 -1
    let mut nm = [0u8; 32];
    nm[..7].copy_from_slice(b"bone001");
    v[0x11c..0x13c].copy_from_slice(&nm);
    v[0x13c..0x15c].copy_from_slice(&nm);
    // 0x15c..0x160 = 孩子数 0
    v.extend_from_slice(tail);
    v
}

/// 128B 挂点记录：`tx_01` → `Bone001` + 单位矩阵（齐次位 1）。
fn synth_socket_record() -> Vec<u8> {
    let mut rec = vec![0u8; 128];
    rec[..5].copy_from_slice(b"tx_01");
    rec[32..40].copy_from_slice(b"Bone001\0");
    for i in 0..4 {
        rec[64 + (i * 4 + i) * 4..64 + (i * 4 + i) * 4 + 4].copy_from_slice(&1.0f32.to_le_bytes());
    }
    rec
}

/// 挂点段头 `[u32 1][u32 1]` + 一条 128B 记录，正好收到 EOF。
fn synth_socket_true_head() -> Vec<u8> {
    let mut tail = Vec::new();
    tail.extend_from_slice(&1u32.to_le_bytes());
    tail.extend_from_slice(&1u32.to_le_bytes());
    tail.extend_from_slice(&synth_socket_record());
    tail
}

/// 正向：真挂点头 `[1][1]` + 一条 128B，正好收到 EOF → 照常解出，挂点解得 1 条。
#[test]
fn socket_segment_with_true_head_ending_at_eof_is_accepted() {
    let mesh = synth_one_bone(&synth_socket_true_head());
    let h = parse_hierarchy(&mesh).expect("真挂点头应能解出");
    assert_eq!(h.bones.len(), 1, "条目数 = 声明数");
    assert_eq!(h.sockets.len(), 1, "挂点段声明 1 条");
    assert_eq!(h.sockets[0].name, "tx_01");
    assert_eq!(h.sockets[0].bone, "Bone001");
}

/// 反向验红：以 `[u32 12592][u32 0]` 假收尾（就是骨名第 5–8 字节 + 4 个 0 的形状，
/// 恰好停在 EOF）。老口径在这里「收到空挂点段」→ 整份文件被收下；锚定后这个点
/// 既不是 flag==1、块链也接不上任何真头，必须整体拒绝。
#[test]
fn fake_socket_footer_x_zero_is_no_longer_accepted() {
    // 假收尾：4B 非 1 的标志 + 4B 的 count=0，之后就是 EOF。
    let mut tail = Vec::new();
    tail.extend_from_slice(&12592u32.to_le_bytes()); // ASCII "01\0\0"——名字里的字节，不是挂点标志
    tail.extend_from_slice(&0u32.to_le_bytes());
    let mesh = synth_one_bone(&tail);
    assert_eq!(
        &mesh[mesh.len() - 8..],
        [0x30, 0x31, 0, 0, 0, 0, 0, 0],
        "现场就是「[x][00 00 00 00]」收尾"
    );
    assert!(
        parse_hierarchy(&mesh).is_none(),
        "[x][0] 假收尾还能收下，说明挂点段的 EOF 锚定没生效"
    );
}
