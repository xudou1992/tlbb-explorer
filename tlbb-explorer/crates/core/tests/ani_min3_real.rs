//! MIN3 动作的端到端闸门（2026-10-27）。真容器字节钉四件事：
//!
//! 1. **解析**：`w1351_npc_xinmurongfu_skill07-2.ani`（189 骨 / 17 帧 / 标志 177 条）能解，
//!    轨数 == 骨数；
//! 2. **骨名晚一格**：第 0 条轨道拿的是名表第 1 格（`bip002`），最后一条落在名表外 ⇒ 空串
//!    （不是把静态区字节读成名字——那曾经读出过控制字符）；
//! 3. **骨架静态区**：`rest_poses` 解得 189 条，且带 MIN3 的绑定局部平移（`pos` 有值）；
//! 4. **能摆**：`pose_frame` 在第 0/8/16 帧都给出 189 个有限矩阵。
//!
//! 数据不在就跳过（与 `rest_rebuild.rs` 同约定）：网格在 `data1`、动作在 `data_1`，
//! **路径哈希跨容器会撞名，两条必须各查各的容器**。

use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{parse_ani, parse_hierarchy, pose, rest_poses};

fn is_unit_quat(q: &[f32; 4]) -> bool {
    let n = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt();
    n < 1e-6 || (0.98..=1.02).contains(&n)
}

const MESH: u64 = 0x000b7690ae6394ea;
const ANI: u64 = 0x0408cc44ae4cf595;

fn grab(root: &PathBuf, pak: &str, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

#[test]
fn min3_真数据_解析骨名静态区与摆姿势() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let (Some(mesh), Some(ani)) = (grab(&root, "data1", MESH), grab(&root, "data_1", ANI)) else {
        eprintln!("跳过：本机没有 data1.pak / data_1.pak 或样本不在容器里");
        return;
    };
    assert_eq!(ani.get(0x8c..0x90), Some(&b"MIN3"[..]), "样本应是 MIN3 容器");

    let a = parse_ani(&ani).expect("MIN3 应能解");
    assert_eq!((a.bones, a.frames), (189, 17), "骨/帧数与实测一致");
    assert_eq!(a.tracks.len(), 189, "轨数 == 骨数（没有块的骨给空轨道）");
    // 2026-10-28：客户端采样器按「索引表[骨] → 通道块」间接取数据（`sub_140732190` 里
    // `v13 = a1[36][骨]`、`记录 = a1[37] + 76×v13`），表里 `>0xFFFF0000` 是哨兵 = 该骨没有块。
    // ⇒ 轨道名按**骨下标**取名表那一格，不再是「晚一格」。
    assert_eq!(a.tracks[0].bone, "000", "轨道名按骨下标取名表那一格");
    assert!(!a.tracks[1].bone.is_empty(), "第 1 根骨应有名字");
    let bones2 = u32::from_le_bytes(ani[0xbe..0xc2].try_into().unwrap()) as usize;
    let no_block = a.tracks.iter().filter(|t| t.rotations.is_empty()).count();
    assert_eq!(
        no_block,
        a.bones - bones2,
        "空轨道条数该等于「骨数 − 通道块数」（索引表哨兵数）"
    );
    assert!(
        a.tracks.iter().all(|t| t.rotations.iter().all(is_unit_quat)),
        "所有帧旋转都应是单位长（全零按静止骨放行）"
    );

    let rests = rest_poses(&ani).expect("MIN3 骨架静态区应能读");
    assert_eq!(rests.len(), 189);
    assert!(
        rests.iter().any(|r| r.pos.is_some()),
        "MIN3 静态区带绑定局部平移（+4），不能整片 None"
    );
    assert!(rests.iter().all(|r| is_unit_quat(&r.rotation)));

    let h = parse_hierarchy(&mesh).expect("骨架应能解");
    assert_eq!(h.bones.len(), 189);
    for f in [0usize, 8, 16] {
        let world = pose::pose_frame(&h, &a, f);
        assert_eq!(world.len(), 189);
        assert!(
            world.iter().all(|m| m.iter().all(|v| v.is_finite())),
            "第 {f} 帧出现了非有限数"
        );
    }
}
