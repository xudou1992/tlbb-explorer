//! 重锚闸门（v0.5.0 播放锚）：**播放用的调色板锚 = 每条动作自己的第 0 帧世界
//! 矩阵的逆**，不是 `.mesh` 的 bind。裁决与证据：`.scratch/ani_axis/锚点判定_20261007.md`
//! ——四种锚 × 15 条动作全量比对，裸 bind 锚 15/15 条动作撕裂、逐动作 frame0
//! 锚 15/15 全胜无一例外、全局单锚对半程动作明显变差。静止渲染维持 bind 锚
//! 不动（同档案 §四第 1 条），本文件只盯播放口径 [`reanchored_palette`]。
//!
//! 四条闸门：
//! 1. **frame0 恒等式**：每条动作 frame=0 时调色板 ≈ 单位阵，蒙皮把全部顶点
//!    送回存储位置（这是「与前端 mesh_data 灰模同源同序」能在画面上成立的前提）；
//! 2. **全量有限性**：15 条动作 × 全帧，palette 与 posed 全有限、长度对；
//! 3. **重锚后位移收口**：idle01 帧均 < 0.8、全最大 < 1.2（研究班实测
//!    0.171/0.606，bind 锚对照 1.022/2.828；上限给宽松防脆，不钉死研究值）；
//! 4. **刚体守恒**：权重 1 的顶点 |v'(t) − world_t(骨).平移| == |v −
//!    frame0_world(骨).平移|——皮肤跟着骨头刚体走，锚换成了 frame0 也不许变。
//!
//! 真数据缺失时降级跳过（打印说明，不算失败）——照 `pose_compose.rs` 的做法。

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::pose::{mat_identity, pose_frame, posed_vertices, reanchored_palette};
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes};

/// w1351_monster_xiyuqiezei_yifu_001.mesh：46 骨主样本（与 pose_compose.rs 同一份）
const MESH: u64 = 0xbcd65050a62986b7;
/// w1351_monster_xiyuqiezei_idle01.ani（41 帧）
const ANI_IDLE01: u64 = 0x4ec2478a169d5e73;

/// 该怪同目录 ani/ 下的全部 15 条动作（hash 与容器逐一核实，照 pose_compose.rs）。
const ACTIONS: [(&str, u64); 15] = [
    ("behit01", 0x1a2545b8c7c1d09a),
    ("dead", 0xa50e431940a097dc),
    ("deadbegin", 0x028c25ec805e675b),
    ("fight_idle01", 0xd45db4390f240632),
    ("flyingdead", 0x1b75afc8147d04ce),
    ("flyingdeadbegin", 0x0e4233fda4e17b36),
    ("hit01", 0x9efcf3fb82b1bed8),
    ("hit02", 0xe2e952fcb84533a5),
    ("hit03", 0x26d5b1fdbd015af9),
    ("idle01", ANI_IDLE01),
    ("idle02", 0x92aea68b139cb4ee),
    ("idle03", 0xd69b058c136af83e),
    ("run", 0xb2a014f2fe102122),
    ("vertigo", 0x61c90a473d53209b),
    ("walk", 0x361180fe30a07e32),
];

fn raw_of(root: &PathBuf, pak: &str, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

fn mesh_bytes() -> Option<Vec<u8>> {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    raw_of(&root, "data", MESH)
}

fn ani_bytes(hash: u64) -> Option<Vec<u8>> {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    raw_of(&root, "data", hash)
}

fn dist3(a: &[f32; 3], b: &[f32; 3]) -> f32 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

fn trans(m: &[f32; 16]) -> [f32; 3] {
    [m[12], m[13], m[14]]
}

/// **frame0 恒等式**：每条动作自己的 frame0 锚在 frame=0 处必须把顶点原样
/// 送回。锚 = 世界(0) 的逆，palette(0) = 世界(0)⁻¹·世界(0) ≈ I（f32 舍入），
/// 蒙皮恒等式的容差与既有闸门 `pose_compose.rs::skin_at_bind_pose_reproduces_the_original_vertices`
/// 同量级（1e-4）。15 条动作逐条验——锚是**逐动作**取的，每条都有自己的 frame0，
/// 少验一条就少堵一个「某条动作的 frame0 锚装错了」的口子。
#[test]
fn frame0_anchor_returns_every_vertex_to_its_stored_position() {
    let Some(mesh) = mesh_bytes() else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let layout = parse_mesh(&mesh).expect("网格应能解出");
    let nodes = parse_nodes(&mesh);
    let positions = &layout.geometry.positions;
    let id = mat_identity();

    let mut ran = 0usize;
    let mut missing = Vec::new();
    let mut worst_pal = 0f32;
    let mut worst_v = 0f32;
    for (name, hash) in ACTIONS {
        let Some(raw) = ani_bytes(hash) else {
            missing.push(name);
            continue;
        };
        let a = parse_ani(&raw).unwrap_or_else(|| panic!("{name} 应能解出"));
        ran += 1;
        let pal = reanchored_palette(&h, &a, 0).expect("frame0 调色板");
        assert_eq!(pal.len(), h.bones.len(), "{name} 调色板长度应等于骨数");
        for (bi, m) in pal.iter().enumerate() {
            let dev = m
                .iter()
                .zip(id.iter())
                .map(|(x, y)| (x - y).abs())
                .fold(0f32, f32::max);
            assert!(
                dev < 1e-4,
                "{name} frame0 锚下骨 {}（#{bi}）的调色板偏离单位阵 {dev:.2e}——锚不是这条动作自己的 frame0",
                h.bones[bi].name
            );
            worst_pal = worst_pal.max(dev);
        }
        let out = posed_vertices(&h, &pal, &nodes, positions).expect("蒙皮");
        assert_eq!(out.len(), positions.len());
        for (i, (o, p)) in out.iter().zip(positions.iter()).enumerate() {
            let d = dist3(o, p);
            assert!(
                d < 1e-4,
                "{name} frame0 恒等式破了：顶点 {i} |v'−v| = {d:.2e}"
            );
            worst_v = worst_v.max(d);
        }
    }
    if ran == 0 {
        eprintln!("跳过：一条动作都取不到（夹具不入库，见 README「测试夹具」）");
        return;
    }
    eprintln!(
        "frame0 恒等式：{ran}/{} 条动作 · 调色板偏离单位阵最大 {worst_pal:.2e} · 全顶点 |v'−v| 最大 {worst_v:.2e}（{} 顶点）",
        ACTIONS.len(),
        positions.len()
    );
    if !missing.is_empty() {
        eprintln!("缺 {} 条动作（不影响其余闸门）：{:?}", missing.len(), missing);
    }
}

/// **全量有限性**：15 条动作 × 全帧，重锚调色板与蒙皮输出全有限、长度对
/// （调色板 = 骨架骨数、蒙皮 = 顶点数）。这是底线闸门：不 panic、无 NaN。
#[test]
fn reanchored_palettes_and_poses_stay_finite_across_all_actions() {
    let Some(mesh) = mesh_bytes() else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let layout = parse_mesh(&mesh).expect("网格应能解出");
    let nodes = parse_nodes(&mesh);
    let positions = &layout.geometry.positions;

    let mut ran = 0usize;
    let mut missing = Vec::new();
    let mut total_frames = 0usize;
    let mut total_palettes = 0usize;
    let mut total_posed = 0usize;
    for (name, hash) in ACTIONS {
        let Some(raw) = ani_bytes(hash) else {
            missing.push(name);
            continue;
        };
        ran += 1;
        let a = parse_ani(&raw).unwrap_or_else(|| panic!("{name} 应能解出"));
        for f in 0..a.frames {
            let pal = reanchored_palette(&h, &a, f)
                .unwrap_or_else(|| panic!("{name} 第 {f} 帧调色板该调得出来"));
            assert_eq!(pal.len(), h.bones.len(), "{name} 第 {f} 帧调色板长度");
            for m in &pal {
                assert!(
                    m.iter().all(|v| v.is_finite()),
                    "{name} 第 {f} 帧调色板出现非有限值"
                );
            }
            let out = posed_vertices(&h, &pal, &nodes, positions)
                .unwrap_or_else(|| panic!("{name} 第 {f} 帧蒙皮该摆得出来"));
            assert_eq!(out.len(), positions.len(), "{name} 第 {f} 帧蒙皮长度");
            for p in &out {
                assert!(p.iter().all(|v| v.is_finite()), "{name} 第 {f} 帧顶点非有限");
            }
            total_palettes += pal.len();
            total_posed += out.len();
        }
        total_frames += a.frames;
    }
    if ran == 0 {
        eprintln!("跳过：一条动作都取不到（夹具不入库，见 README「测试夹具」）");
        return;
    }
    eprintln!(
        "全量扫描：{ran}/{} 条动作 · 全帧 {total_frames} 帧 · 调色板 {total_palettes} 张 · 蒙皮 {total_posed} 顶点，全部有限",
        ACTIONS.len()
    );
    if !missing.is_empty() {
        eprintln!("缺 {} 条动作（不影响其余闸门）：{:?}", missing.len(), missing);
    }
}

/// **重锚后位移收口**：idle01 全 41 帧，带表顶点（555 个，与研究班同一口径
/// ——未被影响表覆盖的顶点跟恒等的框架根，本来就不动）的蒙皮位移
/// **帧均最大 < 0.8、全局最大 < 1.2**。
///
/// 研究班实测（档案 §一，GLB 侧独立管线）：重锚 0.171/0.606；bind 锚对照
/// 1.022/2.828（另一班的旧口径 1.7471/2.4338 同量级）。上限取宽松值防脆
/// ——这条闸门否的是「锚装错」（撕裂会到 1.0+/2.4+），不是钉死动作幅度。
#[test]
fn reanchored_idle01_displacement_stays_within_motion_amplitude() {
    let Some((mesh, ani)) = mesh_bytes().zip(ani_bytes(ANI_IDLE01)) else {
        eprintln!("跳过：本机没有 data.pak 或这两份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let layout = parse_mesh(&mesh).expect("网格应能解出");
    let nodes = parse_nodes(&mesh);
    let positions = &layout.geometry.positions;
    let a = parse_ani(&ani).expect("idle01 应能解出");
    assert_eq!(a.frames, 41);

    // 带表顶点 = 影响表覆盖的那些；未覆盖的跟恒等框架根，位移恒 0，不进统计
    // （研究班的「剔 root_only」就是这一批）。
    let mut seen = vec![false; positions.len()];
    for nd in &nodes {
        if let Some(s) = &nd.skin {
            for &v in &s.vertices {
                seen[v as usize] = true;
            }
        }
    }
    let covered = seen.iter().filter(|t| **t).count();

    let mut mean_max = 0f64;
    let mut global_max = 0f64;
    for f in 0..a.frames {
        let pal = reanchored_palette(&h, &a, f).expect("调色板");
        let out = posed_vertices(&h, &pal, &nodes, positions).expect("蒙皮");
        assert_eq!(out.len(), positions.len());
        let mut mean = 0f64;
        let mut mx = 0f64;
        let mut n = 0usize;
        for (i, t) in seen.iter().enumerate() {
            if !t {
                continue;
            }
            let d = dist3(&out[i], &positions[i]) as f64;
            assert!(d.is_finite(), "第 {f} 帧顶点 {i} 位移非有限");
            mean += d;
            mx = mx.max(d);
            n += 1;
        }
        mean /= n as f64;
        mean_max = mean_max.max(mean);
        global_max = global_max.max(mx);
    }
    let frames = a.frames;
    eprintln!(
        "idle01 重锚位移（{covered} 带表顶点 · {frames} 帧）：帧均最大 {mean_max:.4} · 全局最大 {global_max:.4}（研究班 0.171/0.606；bind 锚对照 1.022/2.828）"
    );
    assert!(
        mean_max < 0.8,
        "重锚后帧均位移 {mean_max:.4} 超了 0.8——画面在撕，先查锚是不是装回了 bind"
    );
    assert!(
        global_max < 1.2,
        "重锚后全局最大位移 {global_max:.4} 超了 1.2——画面在撕，先查锚是不是装回了 bind"
    );
}

/// **刚体守恒**（不依赖任何矩阵约定的物理判据）：单骨权重 1 的顶点是钉死在
/// 骨头上的，换锚只换「骨头在世界里的哪一段历史」，不改变「皮肤跟着骨头走」——
/// |v'(t) − world_t(骨).平移| 必须等于 |v − frame0_world(骨).平移|（容差 1e-3）。
///
/// 数学上严格成立：v' = v·(world0⁻¹·world_t)，v−t_t = (v−t_0)·R_0ᵀ·R_t，
/// 旋转不动长度（world0 的平移在求逆时消掉，缩放前后相消）。违例超差就是
/// 调色板乘序或锚装错了。
#[test]
fn rigid_vertices_keep_their_distance_to_the_frame0_anchored_bone() {
    let Some((mesh, ani)) = mesh_bytes().zip(ani_bytes(ANI_IDLE01)) else {
        eprintln!("跳过：本机没有 data.pak 或这两份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let layout = parse_mesh(&mesh).expect("网格应能解出");
    let nodes = parse_nodes(&mesh);
    let positions = &layout.geometry.positions;
    let a = parse_ani(&ani).expect("idle01 应能解出");

    // 逐顶点汇总影响：取「恰好一根骨、权重 1」的顶点（照 pose_compose.rs 的办法）
    let mut infl: Vec<Vec<(usize, f32)>> = vec![Vec::new(); positions.len()];
    let mut index: HashMap<&str, usize> = HashMap::new();
    for (i, b) in h.bones.iter().enumerate() {
        index.insert(b.name.as_str(), i);
    }
    for nd in &nodes {
        let Some(s) = &nd.skin else { continue };
        let Some(&bi) = index.get(nd.name.as_str()) else { continue };
        for (&v, &w) in s.vertices.iter().zip(s.weights.iter()) {
            infl[v as usize].push((bi, w));
        }
    }
    let rigid: Vec<(usize, usize)> = (0..positions.len())
        .filter_map(|v| match infl[v].as_slice() {
            [(bi, w)] if (w - 1.0).abs() <= 1e-6 => Some((v, *bi)),
            _ => None,
        })
        .collect();
    assert!(
        !rigid.is_empty(),
        "单骨权重 1 的顶点应当存在（实测一个都没有就是读表坏了）"
    );

    let world0 = pose_frame(&h, &a, 0);
    let mut worst = 0f64;
    let mut worst_at = (String::new(), 0usize, 0usize);
    for f in 0..a.frames {
        let world = pose_frame(&h, &a, f);
        let pal = reanchored_palette(&h, &a, f).expect("调色板");
        let out = posed_vertices(&h, &pal, &nodes, positions).expect("蒙皮");
        for &(v, bi) in &rigid {
            let want = dist3(&positions[v], &trans(&world0[bi])) as f64;
            let got = dist3(&out[v], &trans(&world[bi])) as f64;
            let dev = (got - want).abs();
            if dev > worst {
                worst = dev;
                worst_at = (h.bones[bi].name.clone(), v, f);
            }
        }
    }
    eprintln!(
        "刚体守恒（frame0 锚 · idle01 全 {} 帧 · {} 个刚体顶点）：|v'(t)−world_t| 与 |v−world_0| 的最大差 {worst:.3e}（骨 {} 顶点 {} 第 {} 帧）",
        a.frames,
        rigid.len(),
        worst_at.0,
        worst_at.1,
        worst_at.2
    );
    assert!(
        worst < 1e-3,
        "刚体守恒破了：最大差 {worst:.3e}（骨 {} 顶点 {} 第 {} 帧）——皮肤被拉伸或乘序/锚装错",
        worst_at.0,
        worst_at.1,
        worst_at.2
    );
}
