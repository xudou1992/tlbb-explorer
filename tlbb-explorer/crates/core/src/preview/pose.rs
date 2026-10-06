//! 复合层（v0.5.0 播放的「复合」一步）：把解析层已解出的三样输入——
//! 父骨链与绑定矩阵（[`geometry::parse_hierarchy`]）、逐骨影响顶点表
//! （[`geometry::parse_nodes`]）、局部 TRS 轨道（[`anim::parse_ani`]）——
//! 按引擎的行向量约定复合成逐骨世界矩阵，再做蒙皮加权。
//!
//! 本层是**纯数学**：std only、无新依赖、不吃原始字节，输入都是上游解析器
//! 给出的类型化数据。所有矩阵都是行主序 4×4 的 `[f32; 16]`，行向量约定
//! （D3DX，引擎是 DX11）：`v' = v · M`，前三行是基向量，第 4 行
//! `(tx, ty, tz, 1)` 是平移。复合公式（README 已定）：
//!
//! ```text
//! world = local · parent_world      （局部先作用，再父链）
//! ```
//!
//! # 实测基线（w1351_monster_xiyuqiezei_yifu_001，46 骨主样本）
//!
//! 数字由闸门 `crates/core/tests/pose_compose.rs` 盯着，来历见各函数注释：
//!
//! * 存储的 96B 绑定矩阵是**世界绑定矩阵的逆**（`B = S⁻¹`，= glTF 的
//!   inverseBindMatrix = D3DX 的 bone offset）。判据是物理的、不依赖任何既有结论：
//!   骨位应贴着它蒙皮顶点的加权重心——现口径 mean 0.1488，旧口径（直接把 S 当
//!   骨位）mean 1.4393。证据链与「为什么旧口径能骗过骨距与恒等式闸门」见
//!   [`bind_worlds`]（2026-10-06 翻案）；
//! * bind 矩阵是纯正交旋转 + 平移（det 恒 1.0000、基向量长度恒 1.0000），
//!   仿射逆的舍入误差 ~1e-6，蒙皮恒等式容差 1e-4 是稳的；
//! * 三个已知骨距（pelvis←bip01 = 1.0991、foot←calf = 0.4052、
//!   toe0←foot = 0.5460）从 [`bind_worlds`] 的输出逐对复现；
//! * 蒙皮调色板的乘序是 **`bind⁻¹ · world`**（先把顶点换算进这根骨的局部坐标系，
//!   再用该骨当前位姿放回世界）。写成 `world · bind⁻¹` 在 bind 姿态下同样退化成
//!   单位阵，恒等式闸门盯不住；抓得住它的是**刚体距离守恒**（单骨权重 1 的顶点
//!   到骨原点的距离全程不变）和与 glTF 规范侧实现的互认，见 [`skin_palette`]；
//! * bind 姿态外的蒙皮（`.ani` 驱动）位移仍**明显大于骨长量级**：乘序改正后重测
//!   idle01 全 41 帧，帧均值 2.4703~2.5411、全局最大 4.6806（骨长量级 0.2~1.7；
//!   旧乘序量出来是 1.41~1.46 / 2.37，顶点没真跟着骨转所以偏小）。但「变形后
//!   顶点重心离该骨位姿原点」反而更近：第 0 帧 26 根带表骨平均偏 1.184（旧 2.40）、
//!   最大 2.441（旧 3.32）。残差与三个数据开口如实写在 [`posed_vertices`] 和
//!   闸门注释里，没硬凑口径。

use std::collections::HashMap;

use super::anim::Anim;
use super::geometry::{Node, SkeletonHierarchy};

/// 行主序 4×4 单位阵。
pub fn mat_identity() -> [f32; 16] {
    let mut m = [0f32; 16];
    m[0] = 1.0;
    m[5] = 1.0;
    m[10] = 1.0;
    m[15] = 1.0;
    m
}

/// 行向量约定下的 4×4 乘法：`v · (a·b) == (v · a) · b`。
/// 复合公式 `world = local · parent_world` 对应 `mat_mul(&local, &parent_world)`。
pub fn mat_mul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
    let mut o = [0f32; 16];
    for r in 0..4 {
        for c in 0..4 {
            o[r * 4 + c] =
                a[r * 4] * b[c] + a[r * 4 + 1] * b[4 + c] + a[r * 4 + 2] * b[8 + c] + a[r * 4 + 3] * b[12 + c];
        }
    }
    o
}

/// 单位四元数 → 旋转矩阵（行向量约定，即列向量惯用式的转置）。
///
/// **分量序按 D3DX 惯例取 `(x, y, z, w)`**——`.ani` 的四个 f32 的分量序
/// 没有从字节上钉死（anim.rs 只证了「单位长」），这里选 D3DX 惯例并如实标注。
/// 实测旁证（`.scratch/pose_probe.py`）：按 `(w, x, y, z)` 组合 idle01 第 0 帧，
/// 整副骨架塌成 y ∈ ±0.2 的平面（错）；按 `(x, y, z, w)` 水平走向与网格一致。
/// 全零四元数（静止骨的存法）数学上正好得单位阵，不特判也不出 NaN。
pub fn quat_to_mat(q: &[f32; 4]) -> [f32; 16] {
    let [x, y, z, w] = *q;
    let (xx, yy, zz) = (x * x, y * y, z * z);
    let (xy, xz, yz) = (x * y, x * z, y * z);
    let (wx, wy, wz) = (w * x, w * y, w * z);
    let mut m = [0f32; 16];
    m[0] = 1.0 - 2.0 * (yy + zz);
    m[1] = 2.0 * (xy + wz);
    m[2] = 2.0 * (xz - wy);
    m[4] = 2.0 * (xy - wz);
    m[5] = 1.0 - 2.0 * (xx + zz);
    m[6] = 2.0 * (yz + wx);
    m[8] = 2.0 * (xz + wy);
    m[9] = 2.0 * (yz - wx);
    m[10] = 1.0 - 2.0 * (xx + yy);
    m[15] = 1.0;
    m
}

/// 局部 TRS → 局部矩阵。行向量约定下作用顺序是 缩放 → 旋转 → 平移
/// （`v·S·R·T`），等比缩放乘进前三行，平移进第 4 行。
pub fn trs_matrix(rotation: &[f32; 4], position: [f32; 3], scale: f32) -> [f32; 16] {
    let mut m = quat_to_mat(rotation);
    for v in m.iter_mut().take(12) {
        *v *= scale;
    }
    m[12] = position[0];
    m[13] = position[1];
    m[14] = position[2];
    m[15] = 1.0;
    m
}

/// 仿射矩阵求逆（末行必须是 `(tx, ty, tz, 1)`）：左上 3×3 用伴随法，
/// 平移行 = `−t·R⁻¹`。奇异（|det| 过小）或布局不对返回 `None`。
/// 蒙皮要用它算 `bind⁻¹`；bind 矩阵实测 det 恒 1.0，条件数极好。
pub fn mat_inverse_affine(m: &[f32; 16]) -> Option<[f32; 16]> {
    if !m.iter().all(|v| v.is_finite()) || (m[15] - 1.0).abs() > 1e-3 {
        return None;
    }
    let (a, b, c) = (m[0], m[1], m[2]);
    let (d, e, f) = (m[4], m[5], m[6]);
    let (g, h, i) = (m[8], m[9], m[10]);
    let det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if !det.is_finite() || det.abs() < 1e-12 {
        return None;
    }
    let iv = 1.0 / det;
    // adj(R)/det，行主序
    let (r00, r01, r02) = ((e * i - f * h) * iv, -(b * i - c * h) * iv, (b * f - c * e) * iv);
    let (r10, r11, r12) = (-(d * i - f * g) * iv, (a * i - c * g) * iv, -(a * f - c * d) * iv);
    let (r20, r21, r22) = ((d * h - e * g) * iv, -(a * h - b * g) * iv, (a * e - b * d) * iv);
    let t = [m[12], m[13], m[14]];
    let mut o = [0f32; 16];
    o[0] = r00;
    o[1] = r01;
    o[2] = r02;
    o[4] = r10;
    o[5] = r11;
    o[6] = r12;
    o[8] = r20;
    o[9] = r21;
    o[10] = r22;
    // −t·R⁻¹（行向量）
    o[12] = -(t[0] * r00 + t[1] * r10 + t[2] * r20);
    o[13] = -(t[0] * r01 + t[1] * r11 + t[2] * r21);
    o[14] = -(t[0] * r02 + t[1] * r12 + t[2] * r22);
    o[15] = 1.0;
    Some(o)
}

/// 沿父链复合：`world_i = local_i · world_parent`。根骨世界 = 自身局部。
/// 不依赖「父先于子」的存储顺序（未解的骨先挂起，逐轮直到不再有进展；
/// `parse_hierarchy` 已拒绝有环，循环必然终止）。父链走不到的骨保持单位阵
/// ——上游保证这种情况不存在，留作兜底不 panic。
fn compose_worlds(h: &SkeletonHierarchy, local: &[[f32; 16]]) -> Vec<[f32; 16]> {
    let n = h.bones.len();
    debug_assert_eq!(local.len(), n);
    let mut worlds = vec![mat_identity(); n];
    let mut done = vec![false; n];
    for _ in 0..=n {
        let mut progress = false;
        for i in 0..n {
            if done[i] {
                continue;
            }
            match h.bones[i].parent {
                None => {
                    worlds[i] = local[i];
                    done[i] = true;
                    progress = true;
                }
                Some(p) if done[p] => {
                    worlds[i] = mat_mul(&local[i], &worlds[p]);
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
    worlds
}

/// 每根骨的 **bind 世界矩阵**，下标与 `h.bones` 一致。
///
/// # 口径决定（2026-10-06 翻案）：存储矩阵是 **世界绑定矩阵的逆**
///
/// `.mesh` 尾部 96B 记录里那张矩阵 S，语义是 `bone → world` 那张矩阵 B 的**逆**
/// （`B = S⁻¹`）——也就是 glTF 的 `inverseBindMatrices`、D3DX 的 bone offset
/// matrix 是同一个东西。本函数返回的是 **B**，不是 S。
///
/// 判据是**物理的**，不依赖任何既有结论：一根骨的绑定原点应当落在它蒙皮顶点的
/// 加权重心附近。主样本 26 根带表骨实测（`tests/pose_compose.rs`
/// 的 `bind_origins_sit_inside_their_skinned_geometry` 盯着）：
///
/// | 把什么当骨位 | 到蒙皮重心 mean | rms | max | 父子骨原点距离 |
/// |---|---|---|---|---|
/// | 存储值 S（旧口径） | 1.4393 | 1.5848 | 2.6391 | 0.000~3.180 |
/// | **S 的逆 B（现口径）** | **0.1488** | 0.1606 | 0.2531 | 0.000~1.099 |
///
/// 而且 B 的平移给的是**站立的解剖高度**：`bip01_l_toe0` y=0.140、
/// `bip01_l_foot` y=0.693、`bone09` y=1.136、`bone11_mirror*` y=1.270——
/// 与网格立在 y 0.019..2.240 同空间；旧口径的 S 平移 y 多数≈0（骨架躺平）。
///
/// # 为什么旧口径能一路骗过所有闸门
///
/// 旧口径的证据链有三条，**三条都不分辨 S 与 S⁻¹**：
/// ① 三个手算骨距 1.0991 / 0.4052 / 0.5460 复现——但 `|t|` 在求逆下不变
///   （`t' = −Rᵀt`），实测前两个值两种读法**一字不差**，第三个 0.5460 → 0.5539
///   只差 1.4%；② 左右同名骨平移镜像——求逆保持镜像；③ 「存储当局部沿链复合
///   与存储值差 1.0~3.8」只否掉了「S 是局部」，从没否掉「S 是世界矩阵的逆」。
///   再加蒙皮恒等式：`G·IBM` 在 `(node=S, IBM=S⁻¹)` 与 `(node=S⁻¹, IBM=S)` 两种
///   装法下都是单位阵，所以 **bind 姿态渲染、自吃闸门、规范侧对账全都看不出破绽**
///   ——只有把骨架画出来或播动画才会露。这条教训写进闸门注释。
///
/// # 无矩阵的骨怎么补（16/46 根）
///
/// 没有 96B 记录的骨（`bip01_spine1`/`bip01_neck`/`bip01_head`/两条
/// `thigh`/`bone10` 系等）**没有 bind 数据**（64B 局部矩阵块的语义未证，是记档
/// 的开口，不在本层解释）。这里按「恒等局部」沿父链补：`world = world_parent`，
/// 即该骨暂时与父骨重合。这是**占位**不是真值，画骨架线时这些骨会贴在父骨上——
/// 真 bind 位姿要等 64B 块解出才能补，不编造。
pub fn bind_worlds(h: &SkeletonHierarchy) -> Vec<[f32; 16]> {
    let n = h.bones.len();
    let mut worlds = vec![mat_identity(); n];
    let mut done = vec![false; n];
    for _ in 0..=n {
        let mut progress = false;
        for i in 0..n {
            if done[i] {
                continue;
            }
            if let Some(s) = h.bones[i].bind {
                // 口径的关键：存储的是逆矩阵，这里**求逆回来**才是骨的世界绑定。
                // parse_hierarchy 的正交判据保证可逆；真遇到不可逆就是数据坏了，
                // 给单位阵占位（界面照样打得开），不 panic、不硬算。
                worlds[i] = mat_inverse_affine(&s).unwrap_or(mat_identity());
                done[i] = true;
                progress = true;
            } else {
                match h.bones[i].parent {
                    None => {
                        worlds[i] = mat_identity();
                        done[i] = true;
                        progress = true;
                    }
                    Some(p) if done[p] => {
                        // 恒等局部沿父链补：world = 父世界（占位，见上）。
                        worlds[i] = worlds[p];
                        done[i] = true;
                        progress = true;
                    }
                    Some(_) => {}
                }
            }
        }
        if !progress {
            break;
        }
    }
    worlds
}

/// 逐帧世界矩阵：取 `anim` 第 `frame` 帧的局部 TRS，沿父链复合
/// （`world = local · parent_world`），输出下标与 `h.bones` 一致。
///
/// # 局部矩阵的取法（按纪律，能对上的才用）
///
/// * 轨道按**骨名**挂到骨架（`.ani` 轨道名 ↔ `parse_hierarchy` 骨名，
///   未命名轨道对不上骨名，按缺处理，不按位置硬配）；
/// * 帧号超出轨道长度时夹到最后一帧（`parse_ani` 保证各轨道帧数一致，
///   这是防御，不是常态路径）；轨道数组为空的骨当没有轨道；
/// * 对不上轨道的骨：有存储矩阵就用它的**世界绑定 B = S⁻¹** 当局部，没有就恒等
///   局部（世界 = 父骨世界，「沿父链推」）。
///   **近似，如实标注**：B 是世界空间矩阵，父骨不动时它当局部才严格成立；
///   父骨动了，这根骨的位姿只有近似意义。主样本实测：每条动作
///   46 条轨道里恰有 1 条未命名（anim.rs 记档的「名字表 45/46」），按缺
///   处理；45 条有名轨道恰好盖住除框架根 `000` 外的全部骨，`000` 无轨道
///   也无 bind → 恒等局部，该路径实际只兜框架骨。
///
/// 输出只保证「有限」：四元数上游闸门保证单位长（全零按恒等旋转），
/// 复合纯乘加，正常数据不会出 NaN——闸门对全部动作全帧扫的是这条底线。
pub fn pose_frame(h: &SkeletonHierarchy, anim: &Anim, frame: usize) -> Vec<[f32; 16]> {
    let n = h.bones.len();
    let mut index: HashMap<&str, usize> = HashMap::with_capacity(n);
    for (i, b) in h.bones.iter().enumerate() {
        index.insert(b.name.as_str(), i);
    }
    let id = mat_identity();
    let mut local = vec![id; n];
    let mut has_track = vec![false; n];
    for t in &anim.tracks {
        if t.bone.is_empty() {
            continue; // 未命名轨道：对不上骨名，不按位置硬配
        }
        let Some(&i) = index.get(t.bone.as_str()) else {
            continue; // 轨道名不在骨架里：缺，不硬挂
        };
        if t.rotations.is_empty() || t.positions.is_empty() || t.scales.is_empty() {
            continue; // 空轨道当没有
        }
        let f = frame.min(t.rotations.len() - 1).min(t.positions.len() - 1).min(t.scales.len() - 1);
        local[i] = trs_matrix(&t.rotations[f], t.positions[f], t.scales[f]);
        has_track[i] = true;
    }
    // 无轨道的骨：有 bind 用 bind（近似，见函数注释），没有保持恒等。
    for i in 0..n {
        if !has_track[i] {
            if let Some(b) = h.bones[i].bind {
                local[i] = b;
            }
        }
    }
    compose_worlds(h, &local)
}

/// 蒙皮调色板：每根骨一张 `bind_i⁻¹ · world_i`，下标与 `h.bones` 一致。
/// `bind` 传 [`bind_worlds`] 的输出、`world` 传同骨序的 [`pose_frame`] 输出。
/// `world == bind` 时调色板 ≈ 单位阵（舍入 ~1e-6），这正是 bind 姿态恒等式。
/// 长度与骨架不符 → `None`（数据不自洽，不硬算）。
///
/// # 乘序：先 `bind⁻¹` 再 `world`，反过来就是错的（2026-10-05 对账改正）
///
/// 行向量约定下 `v·A·B` 是**先 A 后 B**。蒙皮要的语义是：把顶点从 bind 世界
/// 换算进这根骨的**局部坐标系**（`bind⁻¹` 干这件事），再用该骨当前位姿
/// `world` 放回世界——所以必须是 `bind⁻¹ · world`。
///
/// 三条独立证据，不靠本层自证：
/// 1. **刚体附着守恒**（不依赖任何实现口径）：权重 1 挂在某单骨上的顶点，
///    它到该骨原点的距离在整条动作里必须不变（皮肤跟着骨头走，不许被拉伸）。
///    `bind⁻¹·world` 下 |v' − world平移| = |v − bind平移| 严格成立；
///    `world·bind⁻¹` 下不成立。闸门见 `tests/pose_compose.rs`
///    与 `tests/glb_spec_skin.rs`（后者是反向验红：换回旧乘序立刻红）。
/// 2. **与 glTF 规范互认**：规范的 `skinning = G_joint · IBM`（列向量、IBM =
///    bind 世界求逆）换成引擎行向量口径正好是 `bind⁻¹ · world`。真样品
///    `.scratch/glb_rigged/*.glb` 丢进规范侧实现算出的顶点，与这里
///    差 0e0；旧乘序差 3.91。
/// 3. D3DX 蒙皮样本的配方 `offset · world`（offset = bind 逆矩阵）同序。
///
/// 旧乘序在 **bind 姿态下退化为单位阵**（`bind·bind⁻¹` 与 `bind⁻¹·bind` 都是
/// I），所以「bind 恒等式」那类闸门盯不住它——只有动起来才会露。
pub fn skin_palette(
    h: &SkeletonHierarchy,
    bind: &[[f32; 16]],
    world: &[[f32; 16]],
) -> Option<Vec<[f32; 16]>> {
    if bind.len() != h.bones.len() || world.len() != h.bones.len() {
        return None;
    }
    h.bones
        .iter()
        .enumerate()
        .map(|(i, _)| {
            let inv = mat_inverse_affine(&bind[i])?;
            Some(mat_mul(&inv, &world[i]))
        })
        .collect()
}

/// glTF 给每个顶点的骨骼影响槽位数（导出与播放共用这一个常量，不许各写一份）。
pub const MAX_INFLUENCES: usize = 4;

/// 权重和与 1.0 的判据：|Σw − 1| ≤ 这个值才按和归一（清浮点尾差用的窗口，
/// 与既有闸门 `skin_influences_sum_to_one_per_vertex` 的容差一致）。
pub const WEIGHT_SUM_TOLERANCE: f32 = 0.02;

/// 一个顶点的影响表整形成「和为 1」时走的是哪条路（导出侧按这条分类报数）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WeightCase {
    /// 没有任何影响表覆盖：整份权重挂根骨（根骨世界恒等时顶点原地不动）。
    Uncovered,
    /// Σw 落在 1.0 的容差窗口内：按和归一，清掉浮点尾差。
    Normalized,
    /// Σw 明显不足 1.0：差额 `1 − Σw` 挂根骨 = 那一份不跟随变形。
    RootFilled,
    /// 其余（Σw > 1，或 4 个槽位被占满装不下差额）：只能按和归一。
    Rescaled,
}

/// 把「一个顶点的 (骨下标, 权重)」影响表整形成 glTF 要求的和为 1 的写法。
///
/// 为什么两侧必须共用这一份：`.mesh` 的权重按骨组织，一部分顶点只读到一部分骨
/// （缺的那些骨没有 96B 记录），而 glTF **硬要求**每顶点权重和为 1.0——官方
/// 校验器把不合的报成 `ACCESSOR_WEIGHTS_NON_NORMALIZED`（主样本实测 114 个顶点
/// Σw≈0.815）。给缺失的骨编一个影响比例是造假，所以差额挂根骨：根骨没有轨道、
/// 导出的世界矩阵是恒等阵，权重落在它身上就是「这一份顶点不跟随变形」，与
/// 「未覆盖顶点跟模型走」是同一条既有口径。两侧分开写迟早分叉——查看器里的姿势
/// 和界面里的姿势就对不上（2026-10-05 的对账闸门撞的就是这类分叉）。
///
/// 0 权重项应由调用方先行剔除：它们只是噪声，还会白占 4 个槽位之一，官方校验器
/// 会报 `ACCESSOR_JOINTS_USED_ZERO_WEIGHT`。
pub fn unify_weights(infl: &[(usize, f32)], root: usize) -> (Vec<(usize, f32)>, WeightCase) {
    if infl.is_empty() {
        return (vec![(root, 1.0)], WeightCase::Uncovered);
    }
    let sum: f32 = infl.iter().map(|(_, w)| w).sum();
    let mut out = infl.to_vec();
    // 根骨已经在表里时把差额**并进它那一项**：另起一项会让同一个骨号在 4 个槽位里
    // 出现两次，官方校验器按 ACCESSOR_JOINTS_INDEX_DUPLICATE 判 error，蒙皮也会把根骨
    // 算两遍（本样本根骨 `000` 没有影响表，今天 0 命中，但这是数据形状一换就会踩的坑）。
    let root_slot = out.iter().position(|(j, _)| *j == root);
    let case;
    if (sum - 1.0).abs() <= WEIGHT_SUM_TOLERANCE {
        case = WeightCase::Normalized;
    } else if sum < 1.0 && (out.len() < MAX_INFLUENCES || root_slot.is_some()) {
        match root_slot {
            Some(k) => out[k].1 += 1.0 - sum,
            None => out.push((root, 1.0 - sum)),
        }
        return (out, WeightCase::RootFilled);
    } else {
        case = WeightCase::Rescaled;
    }
    if sum > f32::EPSILON {
        for (_, w) in out.iter_mut() {
            *w /= sum;
        }
    }
    (out, case)
}

/// 蒙皮：`v' = Σ_b w_b · v · (bind_b⁻¹ · world_b(t))`（行向量，`v` 在左；
/// 乘序的理由见 [`skin_palette`]）。
///
/// 输入：骨架（骨名 → 下标）、[`skin_palette`] 的调色板、网格侧节点表
/// （[`geometry::parse_nodes`]，带按骨影响顶点表）、顶点数组。
/// 输出与 `positions` 等长的逐顶点位置。
///
/// # 三条如实口径
///
/// * **权重按 [`unify_weights`] 整形成和为 1**：影响表按骨组织，一部分顶点只
///   读到一部分骨（缺的那些骨没有 96B 记录，主样本实测 114 个顶点 Σw≈0.815）。
///   不给缺失骨编影响比例，差额挂根骨 = 那一份不跟随变形。导出侧走**同一份**
///   代码，所以查看器与界面摆出同一个姿势（两侧各写一套正是 2026-10-05
///   对账闸门撞出来的分叉）。
/// * **没被任何表覆盖的顶点跟随根骨**：没有权重信息 = 不知道它跟哪根骨动，而
///   glTF 的 skin 对整份网格生效、不存在「不蒙皮」的顶点；实测样本的根骨 `000`
///   既无轨道也无 bind（世界恒等），所以它们**保持存储位置不动**。
/// * **对不上就 `None`**：带表的骨名不在骨架里、顶点号越界、长度不符——
///   都是数据不自洽，不猜。影响超过 4 根的顶点截到权重最大的前 4 根（实测 0 个）。
///
/// # bind 姿态外的实测残差（v0.5.0 记档，未硬凑）
///
/// 乘序改正后重测 idle01（41 帧、555 个带表顶点）：位移帧均值 2.4703~2.5411、
/// 全局最大 4.6806（骨长量级 0.2~1.7）——比旧乘序的 1.41~1.46 / 2.37 **更大**，
/// 因为顶点这回真的跟着骨的旋转走了。而「变形后顶点重心 vs 该骨位姿原点」反而
/// 更贴合：第 0 帧 26 根带表骨平均偏 1.184（旧口径 2.40）、最大 2.441（旧 3.32）。
/// 剩下的偏离仍归下面三个**数据开口**，不是蒙皮数学：存储 bind 骨架躺平在
/// y≈0 而网格立在 y 0..2.24（偏 1.84）；`.ani` 组合骨架水平走向与网格一致但
/// 整体低 ~1.7~2.2（`top` 前奏矩阵平移 (0, 2.3455, 0) 像 `000` 根的定位，
/// `top→000` 挂接未实证）；`.ani` 静态区 +48 首条 = 存储 pelvis 平移的定轴轮换
/// ——bind 数据的轴系标注 unresolved，与 64B 局部矩阵、88B 对角块两个记档开口
/// 同源。这些**不在本层解释**，闸门钉「不 panic、无 NaN、长度对」+
/// 刚体距离守恒（[`skin_palette`] 的乘序判据）。

pub fn posed_vertices(
    h: &SkeletonHierarchy,
    palette: &[[f32; 16]],
    nodes: &[Node],
    positions: &[[f32; 3]],
) -> Option<Vec<[f32; 3]>> {
    if palette.len() < h.bones.len() {
        return None;
    }
    let mut index: HashMap<&str, usize> = HashMap::with_capacity(h.bones.len());
    for (i, b) in h.bones.iter().enumerate() {
        index.insert(b.name.as_str(), i);
    }
    let root = h.bones.iter().position(|b| b.parent.is_none()).unwrap_or(0);
    // 先按顶点汇总影响，再交给 unify_weights 整形——导出侧走的是同一份规则。
    let mut lists: Vec<Vec<(usize, f32)>> = vec![Vec::new(); positions.len()];
    for nd in nodes {
        let Some(skin) = &nd.skin else { continue };
        let Some(&bi) = index.get(nd.name.as_str()) else {
            return None; // 带表的骨名不在骨架里：缺，不猜
        };
        for (&v, &w) in skin.vertices.iter().zip(skin.weights.iter()) {
            let vi = v as usize;
            if positions.get(vi).is_none() {
                return None; // 顶点号越界：数据不自洽
            }
            if w.is_finite() && w > 0.0 {
                lists[vi].push((bi, w)); // 0 权重不占槽位
            }
        }
    }
    let mut out = positions.to_vec();
    for (vi, list) in lists.iter_mut().enumerate() {
        if list.len() > MAX_INFLUENCES {
            list.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
            list.truncate(MAX_INFLUENCES);
        }
        let (packed, _case) = unify_weights(list, root);
        let p = positions[vi];
        let mut acc = [0f32; 3];
        for (j, w) in packed {
            let m = &palette[j];
            acc[0] += w * (p[0] * m[0] + p[1] * m[4] + p[2] * m[8] + m[12]);
            acc[1] += w * (p[0] * m[1] + p[1] * m[5] + p[2] * m[9] + m[13]);
            acc[2] += w * (p[0] * m[2] + p[1] * m[6] + p[2] * m[10] + m[14]);
        }
        out[vi] = acc;
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::preview::geometry::{BoneNode, SkeletonHierarchy};

    fn hierarchy(bones: Vec<(&str, Option<usize>, Option<[f32; 16]>)>) -> SkeletonHierarchy {
        // 孩子名单按「谁的孩子」重排成下标表，保证树一致
        let mut nodes: Vec<BoneNode> = bones
            .iter()
            .map(|(name, _, bind)| BoneNode {
                name: name.to_string(),
                parent: None,
                bind: *bind,
                children: Vec::new(),
            })
            .collect();
        for (i, (_, parent, _)) in bones.iter().enumerate() {
            if let Some(p) = parent {
                nodes[i].parent = Some(*p);
                nodes[*p].children.push(i);
            }
        }
        SkeletonHierarchy { bones: nodes, sockets: Vec::new() }
    }

    fn translation(x: f32, y: f32, z: f32) -> [f32; 16] {
        let mut m = mat_identity();
        m[12] = x;
        m[13] = y;
        m[14] = z;
        m
    }

    const Z90_Q: [f32; 4] = [0.0, 0.0, std::f32::consts::FRAC_1_SQRT_2, std::f32::consts::FRAC_1_SQRT_2];

    #[test]
    fn mat_mul_composes_translations_additively() {
        let a = translation(1.0, 2.0, 3.0);
        let b = translation(10.0, 20.0, 30.0);
        let c = mat_mul(&a, &b);
        assert_eq!(&c[12..15], &[11.0, 22.0, 33.0]);
        // v·(a·I) == v·a
        assert_eq!(mat_mul(&a, &mat_identity()), a);
        assert_eq!(mat_mul(&mat_identity(), &a), a);
    }

    #[test]
    fn quat_to_mat_matches_hand_computed_rotations() {
        // (0,0,√2/2,√2/2)：绕 z 转 90°（行向量约定，(1,0,0)·M = (0,1,0)）
        let m = quat_to_mat(&Z90_Q);
        for (k, want) in [0.0, 1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0].iter().enumerate() {
            assert!((m[[0, 1, 2, 4, 5, 6, 8, 9, 10][k]] - want).abs() < 1e-6);
        }
        // 单位四元数与全零四元数都是单位阵
        assert_eq!(quat_to_mat(&[0.0, 0.0, 0.0, 1.0]), mat_identity());
        assert_eq!(quat_to_mat(&[0.0; 4]), mat_identity());
    }

    #[test]
    fn trs_scales_rows_and_puts_translation_in_the_last_row() {
        let m = trs_matrix(&[0.0, 0.0, 0.0, 1.0], [1.0, 2.0, 3.0], 2.0);
        assert_eq!(m[0], 2.0);
        assert_eq!(m[5], 2.0);
        assert_eq!(m[10], 2.0);
        assert_eq!(&m[12..16], &[1.0, 2.0, 3.0, 1.0]);
    }

    #[test]
    fn affine_inverse_roundtrips() {
        let m = trs_matrix(&Z90_Q, [3.0, -2.0, 7.0], 1.0);
        let inv = mat_inverse_affine(&m).expect("可逆");
        let p = mat_mul(&m, &inv);
        for (a, b) in p.iter().zip(mat_identity().iter()) {
            assert!((a - b).abs() < 1e-5, "m·m⁻¹ 偏差 {a} vs {b}");
        }
        assert!(mat_inverse_affine(&[0.0; 16]).is_none(), "奇异阵该回 None");
    }

    /// 存储的是**世界绑定矩阵的逆**，所以纯平移 S=(1,0,0) 的骨，其世界绑定是
    /// (−1,0,0)；无矩阵的骨沿父链补成父骨的世界值。
    #[test]
    fn bind_worlds_inverts_the_stored_and_fills_the_chain() {
        let h = hierarchy(vec![
            ("root", None, Some(translation(1.0, 0.0, 0.0))),
            ("mid", Some(0), None),                       // 无矩阵：补成父骨世界
            ("tip", Some(1), Some(translation(0.0, 2.0, 0.0))), // 有矩阵：直接用
            ("leaf", Some(2), None),                      // 无矩阵：跟 tip
        ]);
        let w = bind_worlds(&h);
        assert_eq!(w[0], translation(-1.0, 0.0, 0.0), "存储值取逆才是骨的世界绑定");
        assert_eq!(w[1], translation(-1.0, 0.0, 0.0), "无矩阵的骨沿父链补");
        assert_eq!(w[2], translation(0.0, -2.0, 0.0), "有矩阵的骨用存储值的逆");
        assert_eq!(w[3], translation(0.0, -2.0, 0.0));
    }

    #[test]
    fn pose_frame_composes_trs_along_parents() {
        let h = hierarchy(vec![
            ("a", None, None),
            ("b", Some(0), None),
            ("c", Some(0), Some(translation(5.0, 0.0, 0.0))), // 无轨道有 bind：bind 当局部（近似路径）
        ]);
        let anim = Anim {
            envelope: crate::preview::Envelope {
                banner: "t".into(),
                tag: "ani".into(),
                version: 2,
                note: String::new(),
            },
            bones: 2,
            frames: 2,
            tick: 40.0,
            tracks: vec![
                crate::preview::Track {
                    bone: "a".into(),
                    rotations: vec![[0.0, 0.0, 0.0, 1.0]; 2],
                    positions: vec![[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
                    scales: vec![1.0; 2],
                },
                crate::preview::Track {
                    bone: "b".into(),
                    rotations: vec![[0.0, 0.0, 0.0, 1.0]; 2],
                    positions: vec![[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
                    scales: vec![1.0; 2],
                },
            ],
        };
        let w0 = pose_frame(&h, &anim, 0);
        assert_eq!(&w0[1][12..15], &[1.0, 1.0, 0.0], "第 0 帧：父 (1,0,0) + 子 (0,1,0)");
        assert_eq!(&w0[2][12..15], &[6.0, 0.0, 0.0], "无轨道的骨：bind 当局部 · 父世界（近似路径钉住）");
        let w1 = pose_frame(&h, &anim, 1);
        assert_eq!(&w1[1][12..15], &[2.0, 1.0, 0.0]);
        // 帧号越界夹到最后一帧
        let w9 = pose_frame(&h, &anim, 9);
        assert_eq!(&w9[1][12..15], &[2.0, 1.0, 0.0]);
        let _ = w9;
    }

    /// 把行主序行向量矩阵作用到点上（本层测试自带，不借实现里的私有工具）。
    fn apply_row(m: &[f32; 16], p: [f32; 3]) -> [f32; 3] {
        [
            p[0] * m[0] + p[1] * m[4] + p[2] * m[8] + m[12],
            p[0] * m[1] + p[1] * m[5] + p[2] * m[9] + m[13],
            p[0] * m[2] + p[1] * m[6] + p[2] * m[10] + m[14],
        ]
    }

    fn dist(a: [f32; 3], b: [f32; 3]) -> f32 {
        ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
    }

    /// 乘序的物理判据（合成数据，不吃客户端）：**骨带着自己的顶点刚体走**——
    /// 顶点到骨原点的距离必须守恒。这里让骨在原地将姿态旋转卸掉（bind 带 90°
    /// 扭转，world 是同一原点不转），旧乘序 `world · bind⁻¹` 会把顶点甩离骨原点，
    /// 这条立刻红；而 bind 姿态恒等式对两种乘序都成立，盯不住它
    /// （2026-10-05 就是靠这条查出乘序写反）。
    #[test]
    fn skin_palette_order_keeps_vertex_attached_to_its_bone() {
        // bind：绕 z 转 90° + 平移到 (0,1,0)；world：同一原点、不转
        let mut bind = quat_to_mat(&Z90_Q);
        bind[13] = 1.0;
        let world = translation(0.0, 1.0, 0.0);
        let origin = [0.0f32, 1.0, 0.0];
        let h = hierarchy(vec![("j", None, Some(bind))]);
        let pal = skin_palette(&h, &[bind], &[world]).expect("调色板");
        let v = [1.0f32, 1.0, 0.0]; // 离骨原点正好 1.0
        let p = apply_row(&pal[0], v);
        assert!(
            (dist(p, origin) - 1.0).abs() < 1e-5,
            "正确乘序下顶点到骨原点的距离应守恒，实际 {p:?} 离原点 {}",
            dist(p, origin)
        );
        assert!(
            (p[0].abs() < 1e-5 && p[1].abs() < 1e-5 && p[2].abs() < 1e-5),
            "顶点应从 (1,1,0) 随骨卸转回到 (0,0,0)，实际 {p:?}"
        );
        // 反序：同一条顶点被甩到离骨原点 2.0 的地方（这条断言就是判据有分辨力）
        let wrong = mat_mul(&world, &mat_inverse_affine(&bind).unwrap());
        let q = apply_row(&wrong, v);
        assert!(
            (dist(q, origin) - 1.0).abs() > 0.1,
            "反序必须被这条判据区分出来，实际 {q:?} 离原点 {}",
            dist(q, origin)
        );
        // 两种乘序在 bind 姿态下都是单位阵——恒等式盯不住乘序，记在这里
        let p0 = skin_palette(&h, &[bind], &[bind]).unwrap();
        assert!(
            dist(apply_row(&p0[0], v), v) < 1e-5,
            "bind 姿态恒等式对两种顺序都成立（所以它盯不住乘序），实际 {:?}",
            apply_row(&p0[0], v)
        );
        let wrong0 = mat_mul(&bind, &mat_inverse_affine(&bind).unwrap());
        assert!(
            dist(apply_row(&wrong0, v), v) < 1e-5,
            "反序在 bind 姿态同样回到原位：恒等式对它也绿，实测 {:?}",
            apply_row(&wrong0, v)
        );
    }

    /// 权重整形的四种情形（导出与播放共用这份，分类必须说得清）。
    #[test]
    fn unify_weights_covers_the_four_cases() {
        let (p, case) = unify_weights(&[], 7);
        assert_eq!(p, vec![(7, 1.0)]);
        assert_eq!(case, WeightCase::Uncovered, "没表覆盖：整份权重挂根骨");

        let (p, case) = unify_weights(&[(0, 0.5001), (1, 0.5001)], 7);
        assert_eq!(case, WeightCase::Normalized);
        assert!((p.iter().map(|(_, w)| *w).sum::<f32>() - 1.0).abs() < 1e-6, "清尾差");

        let (p, case) = unify_weights(&[(0, 0.5)], 7);
        assert_eq!(case, WeightCase::RootFilled);
        assert_eq!(p, vec![(0, 0.5), (7, 0.5)], "差额原样挂根骨，已知那项的比例一动不动");

        // 4 个槽位占满，差额没地方放：只能按和归一
        let (p, case) = unify_weights(&[(0, 0.2), (1, 0.2), (2, 0.2), (3, 0.2)], 7);
        assert_eq!(case, WeightCase::Rescaled);
        assert!((p.iter().map(|(_, w)| *w).sum::<f32>() - 1.0).abs() < 1e-6);

        let (_, case) = unify_weights(&[(0, 0.9), (1, 0.9)], 7);
        assert_eq!(case, WeightCase::Rescaled, "Σw > 1 也只能按和归一");
    }

    #[test]
    fn posed_vertices_skin_and_identity_cases() {
        // 两根骨：根骨 trunk（无 bind → 世界恒等）+ arm（bind 平移到 x=1）
        let h = hierarchy(vec![
            ("trunk", None, None),
            ("arm", Some(0), Some(translation(1.0, 0.0, 0.0))),
        ]);
        let bind = vec![mat_identity(), translation(1.0, 0.0, 0.0)];
        // 姿态 = bind 平移再 +1：palette = T(1)⁻¹·T(2) = T(1)
        let world = vec![mat_identity(), translation(2.0, 0.0, 0.0)];
        let palette = skin_palette(&h, &bind, &world).expect("调色板");
        let nodes = vec![Node {
            name: "arm".into(),
            bind: bind[1],
            skin: Some(crate::preview::SkinInfluence {
                vertices: vec![0, 1],
                weights: vec![1.0, 0.5],
            }),
        }];
        let positions = vec![[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [9.0, 9.0, 9.0]];
        let out = posed_vertices(&h, &palette, &nodes, &positions).expect("蒙皮");
        assert_eq!(out[0], [2.0, 0.0, 0.0], "权重 1：跟骨平移");
        assert_eq!(
            out[1],
            [1.5, 0.0, 0.0],
            "Σw=0.5：已知那份跟骨 (2,0,0)，缺的 0.5 挂根骨（恒等）= 原地 (1,0,0)，合起来 1.5"
        );
        assert_eq!(out[2], [9.0, 9.0, 9.0], "没被表覆盖的顶点跟根骨走，根骨恒等即原地");
        // world == bind：恒等式对每一种顶点都成立
        let p0 = skin_palette(&h, &bind, &bind).expect("调色板");
        let out0 = posed_vertices(&h, &p0, &nodes, &positions).expect("蒙皮");
        assert_eq!(out0, positions, "bind 姿态下整份网格应回到存储位置");
        // 骨名对不上：None
        let stray = vec![Node { name: "ghost".into(), bind: bind[1], skin: nodes[0].skin.clone() }];
        assert_eq!(posed_vertices(&h, &p0, &stray, &positions), None);
        // 长度不符：None
        assert_eq!(skin_palette(&h, &bind[..0], &world), None);
    }
}
