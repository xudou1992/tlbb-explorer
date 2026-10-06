//! 复合层闸门（v0.5.0「复合」一步）。被测对象：`preview::pose`——bind 世界
//! 矩阵、逐帧世界矩阵、蒙皮。口径与证据链：
//!
//! 1. **存储绑定矩阵 = 世界空间 bind 姿态**（冻结结论，本闸门复现两条实测）：
//!    三个已知骨距（pelvis←bip01 = 1.0991、foot←calf = 0.4052、
//!    toe0←foot = 0.5460，`.scratch/父骨链_验证_20261005.md` 档案）从
//!    `bind_worlds` 输出逐对复现；「存储当局部沿链复合」与存储值逐元素差
//!    实测 1.0~3.8（29 根可算骨全部超 1.0）——局部口径被数字否掉。
//! 2. 单位四元数在复合管线里不爆：15 条动作全帧扫描无 NaN/panic。
//! 3. 蒙皮 bind 姿态恒等式：`world == bind` 时带表顶点 v' == v（容差 1e-4）。
//! 4. **蒙皮的物理判据**：单骨权重 1 的顶点到该骨原点的距离在整条动作里守恒
//!    （皮肤跟着骨头刚体走）。这条只讲物理、不讲矩阵约定，所以它能钉住
//!    调色板的**乘序**——`bind⁻¹·world` 守恒、`world·bind⁻¹` 不守恒，而两者
//!    在 bind 姿态下都退化为单位阵，恒等式那条盯不住（2026-10-05 就是这条
//!    查出乘序写反，改正见 `skin_keeps_rigid_vertices...`）。
//! 5. **bind 姿态外的蒙皮如实报数、不硬凑**：位移统计印在输出与注释里，
//!    实测仍远超骨长量级（怀疑点见 `displacement` 那条测试的注释），
//!    闸门只钉「不 panic 且无 NaN」。
//!
//! 真数据缺失时降级跳过（打印说明，不算失败）——照 `bone_hierarchy.rs` 的做法。

use std::collections::HashSet;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::pose::{
    bind_worlds, mat_identity, mat_inverse_affine, mat_mul, pose_frame, posed_vertices,
    skin_palette,
};
use tlbb_core::preview::{bone_count, parse_ani, parse_hierarchy, parse_mesh, parse_nodes};

/// w1351_monster_xiyuqiezei_yifu_001.mesh：46 骨主样本
const MESH: u64 = 0xbcd65050a62986b7;
/// w1351_monster_xiyuqiezei_idle01.ani（41 帧）
const ANI_IDLE01: u64 = 0x4ec2478a169d5e73;
/// w1351_monster_xiyuqiezei_walk.ani（31 帧；anim.rs 记载这份名字表 45/46）
const ANI_WALK: u64 = 0x361180fe30a07e32;

/// 该怪同目录 ani/ 下的全部 15 条动作（清单 resources.db 里按路径枚举，
/// hash 与容器逐一核实；容器都是 data.pak）。
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
    ("walk", ANI_WALK),
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

fn dist_t(a: &[f32; 16], b: &[f32; 16]) -> f32 {
    ((a[12] - b[12]).powi(2) + (a[13] - b[13]).powi(2) + (a[14] - b[14]).powi(2)).sqrt()
}

/// 存储矩阵是**世界**矩阵的对照实验：把它当**局部**沿父链复合（缺矩阵的骨
/// 按恒等——主样本里只有根 `000` 缺），结果应与存储值天差地别。
/// 若哪天偏差变小，说明世界口径被推翻——先回 `.scratch` 复核再动代码。
fn chain_product_as_local(
    h: &tlbb_core::preview::SkeletonHierarchy,
) -> (f32, String, usize) {
    let n = h.bones.len();
    let id = mat_identity();
    let mut l = vec![id; n];
    let mut done = vec![false; n];
    for _ in 0..=n {
        let mut progress = false;
        for i in 0..n {
            if done[i] {
                continue;
            }
            let li = h.bones[i].bind.unwrap_or(id);
            match h.bones[i].parent {
                None => {
                    l[i] = li;
                    done[i] = true;
                    progress = true;
                }
                Some(p) if done[p] => {
                    l[i] = mat_mul(&li, &l[p]);
                    done[i] = true;
                    progress = true;
                }
                Some(_) => {}
            }
        }
        if !progress {
            break;
        }
    }
    let mut max_dev = 0f32;
    let mut worst = String::new();
    let mut counted = 0usize;
    for (i, b) in h.bones.iter().enumerate() {
        let Some(m) = b.bind else { continue };
        counted += 1;
        let dev = m.iter().zip(l[i].iter()).map(|(a, c)| (a - c).abs()).fold(0f32, f32::max);
        if dev > max_dev {
            max_dev = dev;
            worst = b.name.clone();
        }
    }
    (max_dev, worst, counted)
}

/// 三个已知骨距逐对复现 + 「存储当局部」被数字否掉 + 无矩阵骨沿链补齐。
///
/// 注意这条闸门**分辨不了 S 与 S⁻¹**（骨距在求逆下几乎不变），钉的是「链结构
/// 与补齐口径」。真正钉住读法的是 `bind_origins_sit_inside_their_skinned_geometry`。
#[test]
fn bind_worlds_reproduce_known_bone_distances_and_reject_the_local_reading() {
    let Some(mesh) = mesh_bytes() else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let declared = bone_count(&mesh).expect("头部该有骨骼数");
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    assert_eq!(h.bones.len(), declared);
    assert_eq!(declared, 46);
    let worlds = bind_worlds(&h);
    assert_eq!(worlds.len(), h.bones.len());

    // —— 三个 2026-09-29 手算、10-05 归档的骨距，从复合输出逐对复现（容差 1e-3）
    let idx = |name: &str| h.bones.iter().position(|b| b.name == name).expect("骨架里该有这根骨");
    let cases = [
        ("bip01_pelvis", "bip01", 1.0991),
        ("bip01_l_foot", "bip01_l_calf", 0.4052),
        // 第三个值档案里记的是 0.5460——那是**存储矩阵 S 直接当骨位**量出来的；
        // 现口径（B = S⁻¹）给 0.5539，差 1.4%。前两个值两种读法一字不差，
        // 因为 |t| 在求逆下不变（t' = −Rᵀt）——这正是旧口径能骗过这条闸门的原因。
        ("bip01_l_toe0", "bip01_l_foot", 0.5539),
    ];
    for (child, parent, want) in cases {
        let d = dist_t(&worlds[idx(child)], &worlds[idx(parent)]);
        assert!(
            (d - want).abs() < 1e-3,
            "{child}←{parent} 骨距 {d:.4} 应为 {want}"
        );
        eprintln!("骨距 {child}←{parent} = {d:.4}（档案值 {want}）");
    }

    // —— 对照实验：存储矩阵当局部沿链复合，与存储值逐元素差实测 1.0~3.8
    let (max_dev, worst, counted) = chain_product_as_local(&h);
    eprintln!(
        "存储当局部沿链复合 vs 存储值：{counted} 根带矩阵骨，最大元素偏差 {max_dev:.4} @ {worst}"
    );
    assert!(
        max_dev > 0.5,
        "偏差只有 {max_dev:.4}——「存储既不是世界矩阵也不是局部矩阵」，口径要重新审（先复核 .scratch 档案，别直接改代码）"
    );

    // —— 无矩阵的骨沿父链补齐：46 根里 30 根带存储矩阵（既有闸门钉过），
    //     其余 16 根 world = 父骨 world（恒等局部，占位口径见 pose.rs 注释）。
    let with_bind = h.bones.iter().filter(|b| b.bind.is_some()).count();
    assert_eq!(with_bind, 30);
    for (i, b) in h.bones.iter().enumerate() {
        if b.bind.is_none() {
            match b.parent {
                None => assert_eq!(worlds[i], mat_identity(), "根 000 的补齐应为单位阵"),
                Some(p) => assert_eq!(worlds[i], worlds[p], "{} 的补齐应等于父骨世界", b.name),
            }
        }
    }
    eprintln!("bind 世界矩阵：{with_bind} 根用存储值的逆，{} 根沿父链补齐", h.bones.len() - with_bind);
    // 结构抽查：脊柱链平移（W 口径下骨位的实况，供人工核对）
    for name in ["bip01", "bip01_pelvis", "bip01_spine", "bip01_l_calf", "bip01_l_toe0"] {
        let t = &worlds[idx(name)][12..15];
        eprintln!("  {name:>14} t=({:.4}, {:.4}, {:.4})", t[0], t[1], t[2]);
    }
}

/// 单位四元数在复合管线里不爆：15 条动作 × 全帧 × 46 骨，输出必须全有限。
#[test]
fn pose_frames_across_all_actions_stay_finite() {
    let Some(mesh) = mesh_bytes() else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let mut ran = 0usize;
    let mut missing = Vec::new();
    let mut total_frames = 0usize;
    let mut total_mats = 0usize;
    let mut unnamed_tracks = 0usize;
    for (name, hash) in ACTIONS {
        let Some(raw) = ani_bytes(hash) else {
            missing.push(name);
            continue;
        };
        ran += 1;
        let a = parse_ani(&raw).unwrap_or_else(|| panic!("{name} 应能解出"));
        assert_eq!(a.bones, h.bones.len(), "{name} 轨道数应等于骨数");
        unnamed_tracks += a.tracks.iter().filter(|t| t.bone.is_empty()).count();
        for f in 0..a.frames {
            let w = pose_frame(&h, &a, f);
            assert_eq!(w.len(), h.bones.len());
            for (bi, m) in w.iter().enumerate() {
                assert!(
                    m.iter().all(|v| v.is_finite()),
                    "{name} 第 {f} 帧骨 {}（#{bi}）出现非有限值",
                    h.bones[bi].name
                );
            }
            total_mats += w.len();
        }
        total_frames += a.frames;
    }
    if ran == 0 {
        eprintln!("跳过：一条动作都取不到（夹具不入库，见 README「测试夹具」）");
        return;
    }
    if !missing.is_empty() {
        eprintln!("缺 {} 条动作（不影响其余闸门）：{:?}", missing.len(), missing);
    }
    eprintln!(
        "动作扫描：{ran}/{} 条 · 全帧 {total_frames} 帧 · 复合 {total_mats} 张矩阵全部有限 · 未命名轨道 {unnamed_tracks} 条",
        ACTIONS.len()
    );
    // 轨道名覆盖：主样本 idle01 的 46 条轨道里恰有 1 条未命名（anim.rs 记档
    // 的「名字表 45/46」，15 条动作每条都一样），45 条有名轨道恰好盖住
    // 除框架根 `000` 外的全部骨；未命名那条按缺处理，`000` 落到恒等局部。
    let idle = parse_ani(&ani_bytes(ANI_IDLE01).expect("idle01 已在上面取到")).expect("解出");
    let tracked: HashSet<&str> = idle.tracks.iter().map(|t| t.bone.as_str()).collect();
    let untracked: Vec<&str> = h
        .bones
        .iter()
        .map(|b| b.name.as_str())
        .filter(|n| !tracked.contains(n))
        .collect();
    assert_eq!(untracked, vec!["000"], "idle01 里除框架根外每根骨都该有轨道");
    assert_eq!(
        idle.tracks.iter().filter(|t| t.bone.is_empty()).count(),
        1,
        "idle01 该恰有 1 条未命名轨道（45/46）"
    );
}

/// 蒙皮 bind 姿态恒等式：world == bind 时带表顶点 v' == v。
/// 权重和不归一（缺的份额属于没有 96B 记录的骨，归一 = 编造），所以
/// 恒等式只在 Σw≈1 的顶点上钉死；Σw<1 的顶点钉「v' == (Σw)·v」——
/// 谁要是把权重归一化了，这条立刻红。
#[test]
fn skin_at_bind_pose_reproduces_the_original_vertices() {
    let Some(mesh) = mesh_bytes() else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let binds = bind_worlds(&h);
    let layout = parse_mesh(&mesh).expect("网格应能解出");
    let nodes = parse_nodes(&mesh);
    let positions = &layout.geometry.positions;

    // —— 调色板自检：bind·bind⁻¹ ≈ I（f32 舍入 ~1e-6）
    let palette = skin_palette(&h, &binds, &binds).expect("调色板");
    let id = mat_identity();
    let mut palette_dev = 0f32;
    for p in &palette {
        palette_dev = p
            .iter()
            .zip(id.iter())
            .map(|(a, b)| (a - b).abs())
            .fold(palette_dev, f32::max);
    }
    eprintln!("bind 调色板与单位阵的最大元素偏差 {palette_dev:.2e}");
    assert!(palette_dev < 1e-4, "bind·bind⁻¹ 偏差 {palette_dev:.2e} 过大");

    // —— 蒙皮
    let out = posed_vertices(&h, &palette, &nodes, positions).expect("蒙皮应走通");
    assert_eq!(out.len(), positions.len());

    // 逐顶点权重和
    let mut wsum = vec![0f32; positions.len()];
    let mut seen = vec![false; positions.len()];
    let mut tables = 0usize;
    for nd in &nodes {
        let Some(s) = &nd.skin else { continue };
        tables += 1;
        for (&v, &w) in s.vertices.iter().zip(s.weights.iter()) {
            wsum[v as usize] += w;
            seen[v as usize] = true;
        }
    }
    let covered: Vec<usize> = (0..positions.len()).filter(|&i| seen[i]).collect();
    // 两个窗口：1e-3 是 README「441 个权重和正好 1.0」的口径；恒等式断言
    // 只钉**精确和**（1e-6）的子集——窗口放宽到 1e-3 时会混进 Σw−1≈2e-4 的
    // 顶点，它的 |v'−v| = (Σw−1)·|v| ≈ 4e-4，是权重本身的性质不是蒙皮错了。
    let ones: Vec<usize> = covered.iter().copied().filter(|&i| (wsum[i] - 1.0).abs() < 1e-3).collect();
    let exact: Vec<usize> = covered.iter().copied().filter(|&i| (wsum[i] - 1.0).abs() < 1e-6).collect();
    assert!(tables >= 20, "带影响表的骨该有 20 根以上（实际 {tables}）");
    assert!(ones.len() >= 400, "Σw≈1 的顶点实测 441 个，掉到 {} 就是读表坏了", ones.len());
    eprintln!(
        "权重和：覆盖 {} 顶点，Σw≈1e-3 窗口 {} 个（README 口径 441），精确和（1e-6 窗口）{} 个",
        covered.len(),
        ones.len(),
        exact.len()
    );

    // 精确 Σw=1 的顶点：bind 姿态下 v' == v（恒等式，容差 1e-4）
    let dist = |a: &[f32; 3], b: &[f32; 3]| {
        ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
    };
    let mut worst = 0f32;
    let mut worst_i = 0usize;
    for &i in &exact {
        let d = dist(&out[i], &positions[i]);
        if d > worst {
            worst = d;
            worst_i = i;
        }
    }
    eprintln!(
        "蒙皮恒等式：{} 根带表骨 · 覆盖 {}/{} 顶点（精确 Σw=1 的 {} 个）· |v'−v| 最大 {worst:.2e}",
        tables,
        covered.len(),
        positions.len(),
        exact.len()
    );
    assert!(
        !exact.is_empty(),
        "精确 Σw=1 的顶点一个都没有——权重表口径变了，先复核再跑"
    );
    assert!(worst < 1e-4, "bind 姿态下恒等式破了：最大偏差 {worst:.2e}（最差顶点 #{worst_i}）");

    // Σw 不等于 1.0 的顶点：差额按 `pose::unify_weights` 挂根骨。bind 姿态下
    // 每根骨（根骨也在内）的调色板都是单位阵，所以 v' 仍应**严格回到 v**。
    // 旧口径「照原样加权」会给出 (Σw)·v——顶点被吸向世界原点，那是数学错而不
    // 是数据缺口；glTF 要求权重和为 1.0 正是为了不出现这种吸收。
    let partial: Vec<usize> =
        covered.iter().copied().filter(|&i| (wsum[i] - 1.0).abs() >= 1e-6).collect();
    let mut worst_partial = 0f32;
    for &i in &partial {
        for k in 0..3 {
            worst_partial = worst_partial.max((out[i][k] - positions[i][k]).abs());
        }
    }
    eprintln!(
        "Σw≠1 的 {} 个顶点（差额挂根骨）：bind 姿态 |v'−v| 最大 {worst_partial:.2e}",
        partial.len()
    );
    assert!(
        worst_partial < 1e-4,
        "差额挂根骨后这些顶点在 bind 姿态也应回到存储位置，实测偏差 {worst_partial:.2e}"
    );

    // 没被任何表覆盖的顶点原样
    let untouched = (0..positions.len()).filter(|i| !seen[*i]).count();
    for i in 0..positions.len() {
        if !seen[i] {
            assert_eq!(out[i], positions[i]);
        }
    }
    eprintln!("未覆盖顶点 {untouched} 个原样输出（无权重信息，不编跟随关系）");
}

/// bind 姿态外的蒙皮：**只钉「不 panic、无 NaN、长度对」**。
///
/// 实测（README 口径：bind = 存储世界矩阵、pose = `.ani` 局部沿链复合，
/// idle01 共 41 帧、555 个带表顶点；以测试输出为准）：
///
/// * 逐帧位移帧均值 1.41~1.46、全局最大 2.37——骨长量级是 0.2~1.7，
///   位移明显超了；首帧与末帧的统计**一字不差**是数据本身性质：idle01 是
///   闭环，逐字节比对 44/46 条轨道的末帧与首帧只在浮点低位不同，
///   组合骨位最大差 < 1e-4。
/// * 变形后顶点重心没有贴回姿势骨位（第 0 帧 26 根带表骨平均偏 2.40、
///   最大 3.32，见输出）。
///
/// 怀疑点（都有数字，见 `.scratch/pose_probe.py` 的预探，未硬凑口径）：
/// 1. 存储 bind 骨架「躺平」：30 根带矩阵骨的平移 y 全在 −0.16..0.78、
///    多数 ≈0，而网格立在 y 0.019..2.240；骨位与它影响顶点的加权重心
///    平均偏 1.84。存储矩阵若是「世界 bind」，世界跟网格不重合。
/// 2. `.ani` 组合骨架（world = local·parent_world，缺轨道恒等）水平走向与
///    网格一致（spine 的 x/z 与重心分毫不差），但整体比网格低 ~1.7~2.2；
///    尾部前奏 `top` 的矩阵平移是 (0, 2.3455, 0)，像骨架根 `000` 的定位
///    ——`top→000` 的挂接没实证，先不动。
/// 3. `.ani` 静态区 +48 首条浮点 (−0.0007, 0.0507, 1.0979) 恰好是存储
///    pelvis 平移 (0.0507, 0.0007, −1.0979) 的定轴轮换——bind 数据在两份
///    容器里的轴系标注 unresolved，与 64B 局部矩阵 / 88B 对角块两个记档
///    开口同源（那两件不归本任务）。
/// 以上任何一条都不够格当结论，闸门只保底线：全帧可算、无 NaN。
#[test]
fn skin_at_pose_frames_is_safe_and_reports_displacement() {
    let Some((mesh, ani)) = mesh_bytes().zip(ani_bytes(ANI_IDLE01)) else {
        eprintln!("跳过：本机没有 data.pak 或这两份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let binds = bind_worlds(&h);
    let layout = parse_mesh(&mesh).expect("网格应能解出");
    let nodes = parse_nodes(&mesh);
    let positions = &layout.geometry.positions;
    let a = parse_ani(&ani).expect("idle01 应能解出");
    assert_eq!(a.frames, 41);

    let mut seen = vec![false; positions.len()];
    for nd in &nodes {
        if let Some(s) = &nd.skin {
            for &v in &s.vertices {
                seen[v as usize] = true;
            }
        }
    }
    let covered = seen.iter().filter(|t| **t).count();

    // 全帧扫描：位移统计（最小/最大的帧均值 + 全局最大）+ 非有限值检查
    let mut mean_min = f64::INFINITY;
    let mut mean_max = f64::NEG_INFINITY;
    let mut global_max = 0f64;
    for frame in 0..a.frames {
        let posed = pose_frame(&h, &a, frame);
        let palette = skin_palette(&h, &binds, &posed).expect("调色板");
        let out = posed_vertices(&h, &palette, &nodes, positions).expect("蒙皮");
        assert_eq!(out.len(), positions.len());
        let mut mean = 0f64;
        let mut max = 0f64;
        let mut n = 0usize;
        for (i, t) in seen.iter().enumerate() {
            if !t {
                continue;
            }
            let d = (((out[i][0] - positions[i][0]).powi(2)
                + (out[i][1] - positions[i][1]).powi(2)
                + (out[i][2] - positions[i][2]).powi(2)) as f64)
                .sqrt();
            assert!(d.is_finite(), "第 {frame} 帧顶点 {i} 位移非有限");
            mean += d;
            max = max.max(d);
            n += 1;
        }
        mean /= n as f64;
        mean_min = mean_min.min(mean);
        mean_max = mean_max.max(mean);
        global_max = global_max.max(max);
        // 诊断（不进闸门）：第 0 帧变形后顶点重心离姿势骨位多远
        if frame == 0 {
            let mut acc = vec![[0f64; 3]; h.bones.len()];
            let mut wsum = vec![0f64; h.bones.len()];
            for nd in &nodes {
                let Some(s) = &nd.skin else { continue };
                let bi = h.bones.iter().position(|b| b.name == nd.name).expect("骨名");
                for (&v, &w) in s.vertices.iter().zip(s.weights.iter()) {
                    for k in 0..3 {
                        acc[bi][k] += (w * out[v as usize][k]) as f64;
                    }
                    wsum[bi] += w as f64;
                }
            }
            let mut cmean = 0f64;
            let mut cmax = 0f64;
            let mut cbones = 0usize;
            for (bi, _b) in h.bones.iter().enumerate() {
                if wsum[bi] <= 1e-6 {
                    continue;
                }
                let c = [
                    acc[bi][0] / wsum[bi],
                    acc[bi][1] / wsum[bi],
                    acc[bi][2] / wsum[bi],
                ];
                let t = &posed[bi][12..15];
                let d = (((c[0] - t[0] as f64).powi(2)
                    + (c[1] - t[1] as f64).powi(2)
                    + (c[2] - t[2] as f64).powi(2)) as f64)
                    .sqrt();
                cmean += d;
                cmax = cmax.max(d);
                cbones += 1;
            }
            eprintln!(
                "  第 0 帧变形后顶点重心 vs 姿势骨位：{} 根带表骨平均偏 {:.3} · 最大 {:.3}（若蒙皮贴合，应为骨长量级以下）",
                cbones,
                cmean / cbones as f64,
                cmax
            );
        }
    }
    eprintln!(
        "idle01 全帧蒙皮位移（{covered} 个带表顶点）：帧均值 {mean_min:.4}~{mean_max:.4} · 全局最大 {global_max:.4}（骨长量级 0.2~1.7）"
    );
}

/// 蒙皮的物理判据（不依赖任何矩阵约定）：**单骨权重 1 的顶点，到该骨原点的
/// 距离在整条动作里守恒**。
///
/// 皮肤跟着骨头刚体走——顶点在 bind 姿态下离骨原点多远，摆完姿势还离多远
/// （世界带等比缩放时按 world 第一行的长度折算）。这条判据只讲物理，所以它
/// 能分辨调色板的乘序：`bind⁻¹ · world`（先把顶点换算进这根骨的局部坐标系，
/// 再用该骨当前位姿放回世界）严格守恒；反过来写 `world · bind⁻¹` 不守恒。
/// 两种顺序在 bind 姿态下都退化成单位阵，所以「bind 恒等式」那类闸门盯不住
/// 这个错——2026-10-05 由这条查出乘序写反（同时被 `glb_spec_skin.rs` 的
/// 规范侧对账独立证实：换序后与 glTF 规范的蒙皮结果差 0e0）。
///
/// 反向验红：同一份数据把乘序倒过来重算，违例必须显著变大，否则这条判据
/// 是空转的。
#[test]
fn skin_keeps_rigid_vertices_at_their_bone_distance() {
    let Some(mesh) = mesh_bytes() else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let binds = bind_worlds(&h);
    let layout = parse_mesh(&mesh).expect("网格应能解出");
    let nodes = parse_nodes(&mesh);
    let positions = &layout.geometry.positions;

    // 逐顶点汇总影响：只取「恰好一根骨、权重 1」的顶点（刚体附着，语义最干净）
    let mut infl: Vec<Vec<(usize, f32)>> = vec![Vec::new(); positions.len()];
    let mut index: std::collections::HashMap<&str, usize> = std::collections::HashMap::new();
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
    assert!(!rigid.is_empty(), "单骨权重 1 的顶点应当存在（实测一个都没有就是读表坏了）");

    let mut worst = 0f64;
    let mut worst_at = (String::new(), 0usize, 0usize);
    let mut worst_flipped = 0f64;
    let mut frames_scanned = 0usize;
    for (name, hash) in ACTIONS {
        let Some(ani) = ani_bytes(hash) else {
            eprintln!("跳过动作 {name}：不在本机库里");
            continue;
        };
        let a = parse_ani(&ani).expect("动作应能解出");
        for frame in 0..a.frames {
            let world = pose_frame(&h, &a, frame);
            let palette = skin_palette(&h, &binds, &world).expect("调色板");
            let out = posed_vertices(&h, &palette, &nodes, positions).expect("蒙皮");
            // 反向验红用的倒序调色板（本层公开函数现算，不复制实现）
            let flipped: Vec<[f32; 16]> = (0..h.bones.len())
                .map(|i| mat_mul(&world[i], &mat_inverse_affine(&binds[i]).unwrap()))
                .collect();
            let out_flipped = posed_vertices(&h, &flipped, &nodes, positions).expect("倒序蒙皮");
            frames_scanned += 1;
            for &(v, bi) in &rigid {
                // 骨原点：平移在第 4 行；世界等比缩放 = 第一行的长度
                let bt = [binds[bi][12] as f64, binds[bi][13] as f64, binds[bi][14] as f64];
                let wt = [world[bi][12] as f64, world[bi][13] as f64, world[bi][14] as f64];
                let scale = ((world[bi][0] as f64).powi(2)
                    + (world[bi][1] as f64).powi(2)
                    + (world[bi][2] as f64).powi(2))
                    .sqrt();
                let p = [positions[v][0] as f64, positions[v][1] as f64, positions[v][2] as f64];
                let want = vec_len([p[0] - bt[0], p[1] - bt[1], p[2] - bt[2]]) * scale;
                if want < 1e-5 {
                    continue; // 顶点正压在骨原点上，比值无意义
                }
                let rel = |o: &[[f32; 3]]| -> f64 {
                    let q = [o[v][0] as f64, o[v][1] as f64, o[v][2] as f64];
                    ((vec_len([q[0] - wt[0], q[1] - wt[1], q[2] - wt[2]]) - want) / want).abs()
                };
                let r = rel(&out);
                if r > worst {
                    worst = r;
                    worst_at = (h.bones[bi].name.clone(), v, frame);
                }
                worst_flipped = worst_flipped.max(rel(&out_flipped));
            }
        }
    }
    eprintln!(
        "刚体距离守恒：{} 个单骨权重 1 顶点 · {} 帧 · 最大相对违例 {:.3e}（骨 {} 顶点 {} 第 {} 帧）",
        rigid.len(),
        frames_scanned,
        worst,
        worst_at.0,
        worst_at.1,
        worst_at.2
    );
    eprintln!("反向验红：同一批顶点把乘序倒过来算，最大相对违例 {worst_flipped:.4}");
    assert!(worst < 1e-4, "乘序正确时刚体距离应守恒，实测违例 {worst:.3e}");
    assert!(
        worst_flipped > 1e-2,
        "倒序必须被这条判据抓出来（现口径的错就在这），实测只差 {worst_flipped:.3e}"
    );
}

fn vec_len(v: [f64; 3]) -> f64 {
    (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt()
}

/// **口径判据（物理的，不依赖任何既有结论）**：一根骨的绑定原点应当落在它
/// 蒙皮顶点的加权重心附近。主样本 26 根带表骨实测：
///
/// | 把什么当骨位 | mean | rms | max | 父子骨原点距离 |
/// |---|---|---|---|---|
/// | 存储值 S（2026-10-05 旧口径） | 1.4393 | 1.5848 | 2.6391 | 0.000~3.180 |
/// | **S 的逆 B（现口径）** | **0.1488** | 0.1606 | 0.2531 | 0.000~1.099 |
///
/// 差近十倍，而且 B 的平移是**站立的解剖高度**（脚趾 y≈0.14、脚踝 y≈0.69、
/// 胸口 y≈1.27），与网格立在 y 0.019..2.240 同空间；S 的平移 y 多数≈0，
/// 骨架躺在地上。2026-10-06 靠这条翻案：`.mesh` 里存的 96B 矩阵是
/// **世界绑定矩阵的逆**（= glTF 的 inverseBindMatrix = D3DX 的 bone offset）。
///
/// 反向钉：旧读法（S 直接当骨位）的 mean 必须显著大于现读法，否则这条判据
/// 没有分辨力，口径随时可能被人再翻回去。
#[test]
fn bind_origins_sit_inside_their_skinned_geometry() {
    let Some(mesh) = mesh_bytes() else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let l = parse_mesh(&mesh).expect("几何应能解出");
    let pos = &l.geometry.positions;
    let nodes = parse_nodes(&mesh);
    let worlds = bind_worlds(&h);

    let mut cur = Vec::new();
    let mut old = Vec::new();
    let mut heights: Vec<(String, [f32; 3])> = Vec::new();
    for nd in &nodes {
        let Some(sk) = &nd.skin else { continue };
        let Some(i) = h.bones.iter().position(|b| b.name == nd.name) else { continue };
        let (mut c, mut wsum) = ([0f64; 3], 0f64);
        for (&v, &w) in sk.vertices.iter().zip(sk.weights.iter()) {
            let p = &pos[v as usize];
            for k in 0..3 {
                c[k] += w as f64 * p[k] as f64;
            }
            wsum += w as f64;
        }
        if wsum <= 0.0 {
            continue;
        }
        for k in 0..3 {
            c[k] /= wsum;
        }
        let b = &worlds[i];
        // 现口径：bind_worlds 已经是 B = S⁻¹；旧口径 = 存储的 S，从 B 再逆回去拿
        let s_mat = mat_inverse_affine(b).expect("正交矩阵必可逆");
        let d = |m: &[f32; 16]| {
            ((0..3).map(|k| (m[12 + k] as f64 - c[k]).powi(2)).sum::<f64>()).sqrt()
        };
        cur.push(d(b));
        old.push(d(&s_mat));
        heights.push((nd.name.clone(), [b[12], b[13], b[14]]));
    }
    let mean = |v: &Vec<f64>| v.iter().sum::<f64>() / v.len() as f64;
    let rms = |v: &Vec<f64>| (v.iter().map(|x| x * x).sum::<f64>() / v.len() as f64).sqrt();
    let mx = |v: &Vec<f64>| v.iter().fold(0f64, |a, &b| a.max(b));
    assert!(cur.len() >= 20, "带表骨该有 20 根以上（实际 {}）", cur.len());
    eprintln!(
        "骨位↔蒙皮重心：现口径(B=S⁻¹) mean {:.4} rms {:.4} max {:.4} ｜ 旧口径(S) mean {:.4} rms {:.4} max {:.4}（{} 根带表骨）",
        mean(&cur), rms(&cur), mx(&cur), mean(&old), rms(&old), mx(&old), cur.len()
    );
    assert!(mean(&cur) < 0.3, "绑定原点应贴着蒙皮重心，实测 mean {:.4}", mean(&cur));
    assert!(
        mean(&old) > 3.0 * mean(&cur),
        "反向验红：旧口径必须差出一个量级，否则这条判据没有分辨力（旧 {:.4} 新 {:.4}）",
        mean(&old),
        mean(&cur)
    );

    // 解剖抽查：脚在低处、髋在身高一半上下，且左右镜像。
    // 注意查的是**全部 46 根骨**的世界平移（`bip01_pelvis` 这类根段没有影响表，
    // 不在上面 heights 里），别拿带表骨那 26 根去查。
    let at = |n: &str| {
        h.bones
            .iter()
            .position(|b| b.name == n)
            .map(|i| [worlds[i][12], worlds[i][13], worlds[i][14]])
    };
    for (bone, lo, hi) in [("bip01_l_toe0", 0.02f32, 0.30), ("bip01_l_foot", 0.30, 1.00), ("bip01_pelvis", 0.90, 1.30)] {
        let t = at(bone).unwrap_or_else(|| panic!("{bone} 该在带表骨里"));
        assert!(t[1] > lo && t[1] < hi, "{bone} 的 y={:.3} 不在站立高度区间 {lo}..{hi}", t[1]);
        eprintln!("  {bone:>14} y={:.3} ✓ 站立", t[1]);
    }
    let (lt, rt) = (at("bip01_l_toe0").unwrap(), at("bip01_r_toe0").unwrap());
    assert!(lt[0] > 0.0 && rt[0] < 0.0, "左右脚趾应关于 x 镜像：左 {:.3} 右 {:.3}", lt[0], rt[0]);
    assert!((lt[1] - rt[1]).abs() < 0.02 && (lt[2] - rt[2]).abs() < 0.02, "左右等高等深");
}
