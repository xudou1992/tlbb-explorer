//! 无 96B 记录骨的 bind 位置重建（v0.5.0 骨架显示补全）。
//!
//! 主样本 46 根骨里有 16 根（spine1/neck/head/l_clavicle/手臂/手指/thigh/bone10 系
//! 与根 `000`）在 `.mesh` 里**没有 96B 记录**——它们在 3D 骨头连线里是断点，
//! 骨架页表格里 `pos = None`。研究班 2026-10-07 解穿（`.scratch/ani_axis/
//! 锚点判定_20261007.md` §二/§三）：**`.ani` 的骨架静态区就是缺失的 rest 数据源**，
//! 配合「有记录子孙反解」能把无记录骨的 bind 位置补出来。本模块把这套重建搬进
//! core，**只服务显示层**（骨线 + 骨架表格），证据链与边界如下。
//!
//! # 静态区两个字段在「有记录骨」上的语义（研究班钉死，本层只复用）
//!
//! * `+12` 四元数 `qrest`：**= bind 局部旋转的逆**（被动约定的存法）。行向量口径下
//!   bind 局部旋转 = [`quat_to_mat_passive`]`(qrest)`。干净记录骨（自有记录且父有记录）
//!   实测命中：主样本 15/20（≤0.1°），heihou 13/16、duchanchu 14/16；miss 的 5 根全是
//!   根运动骨（pelvis）与武器/挂件链（bone01/bone08/bone09/bone10_mirror02_mirror01）。
//! * 轨道常量平移（每骨轨道 positions 的中位数，44/46 根跨帧 std<1e-4）：**= bind
//!   局部平移**，干净记录骨上向量级相等（差=0，15/20，miss 同上）。
//!
//! # 重建（行向量约定，`world = local · parent_world`）
//!
//! * 有 96B 记录的骨：世界 = 存储矩阵求逆（[`super::pose::bind_worlds`] 同口径，
//!   **一概不覆盖**——存储值是权威，静态区只在缺记录的地方补）。
//! * 无记录骨，**优先「有记录孩子反解」**（研究班 k4_solve.py 的落码形态）：
//!   `W_parent = L_rec(child)⁻¹ · W_child`，其中 `L_rec(c)` = 静态区旋转 + 该骨轨道
//!   常量平移。多个有记录孩子时逐个解、互相对账（差超容差 = 数据不自洽，这根骨
//!   不给值）。
//! * 无记录骨且没有有记录孩子：**沿父链顺推** `W_j = L_rec(j) · W_parent`。它的平移
//!   只吃「自身轨道常量平移」（研究班 §三：无记录骨的缺失平移就在轨道里）——但
//!   **只对平移通道恒定的骨**做：通道会动的骨（root motion，如 footsteps）的
//!   中位数不是 bind 偏移，拿来当位置就是编造，保持 `None`。
//!
//! # 为什么不把顺推用在有记录孩子的骨上（落码时验过的取舍）
//!
//! 顺推的位置 = 父骨世界旋转 ∘ 自身常量平移；父骨自身无记录时它的旋转来自静态区
//! qrest——而无记录骨的 qrest **不**遵循「=blocal⁻¹」模式（档案 §二：spine1 的
//! qrest≈0.05°，真旋转差得远），顺推方向会错。反解只吃**有记录孩子**的 L_rec 与
//! 存储世界，主样本上被两条独立证据复核：l_clavicle/l_forearm 反解位与对侧**存储**
//! 骨镜像吻合到 0.0000（dy=dz=0）；反解链整体给出 spine1 y≈1.475、neck y≈1.795、
//! head y≈2.092 的站立解剖高度（网格 bbox 顶 2.240），而纯顺推链会把 head 放在
//! 挂点 clavicle 同一高度（1.784）——解剖上不成立。取舍与数字如实写进闸门。
//!
//! # 运行时自检闸门（消费路径上必跑；这是「不硬凑」红线的落码形态）
//!
//! 1. **对齐**：静态区与轨道同序（[`super::anim::rest_poses`] 保证）、每条**有名字**
//!    的轨道都必须能对上这副骨架的骨名——对不上说明这份静态区不是这副骨架的，
//!    整体 `None`。
//! 2. **语义命中率**：对干净记录骨逐骨对账「qrest 反旋转 vs 存储局部旋转」（≤0.1°）
//!    与「轨道常量 vs 存储局部平移」（≤1e-3）。命中率 < 2/3（旋转、平移分别算）→
//!    静态区语义在这副骨架上不成立，整体 `None`，消费方维持原状 + 人话注记。
//! 3. **镜像对账**（逐骨）：重建位与**有存储记录**的对侧同名骨（`_l_`↔`_r_`）比：
//!    y/z 差 ≤0.05、x 反号和 ≤0.05。不过 → 这根骨回 `None`（不把可疑推导值当数据）。
//! 4. **解剖对账**（逐骨）：重建位到父骨位的距离 ≤ [`MAX_PARENT_DISTANCE`]（全库已知
//!    最大骨距 3.18 + 余量）、全分量有限。不过 → 这根骨回 `None`。
//!
//! 输出[`RestRebuild::positions`]覆盖全部骨：记录骨 = 存储求逆（与
//! [`super::pose::bind_worlds`] 一致），无记录骨 = 上述反解/顺推（或 `None`）。
//! **这些是推导值不是存储值**：surface 出去的地方必须如实标注「静态区反解」。

use std::collections::HashMap;

use super::anim::{Anim, Rest};
use super::geometry::SkeletonHierarchy;
use super::pose::{mat_identity, mat_inverse_affine, mat_mul, quat_to_mat};

/// 语义自检的旋转容差（度）。命中骨实测 <0.01°，miss 骨 ≥7.9°——0.1° 在两者之间，
/// 有 80 倍以上分辨力。
pub const ROTATION_TOLERANCE_DEG: f32 = 0.1;
/// 语义自检的平移容差。命中骨实测差=0，miss 骨 ≥0.046（骨长量级 0.1~1.7）。
pub const TRANSLATION_TOLERANCE: f32 = 1e-3;
/// 轨道平移「恒定」判据：逐帧与中位数的最大偏差。实测常量骨 <1e-4，
/// root motion 骨（pelvis/footsteps）≥0.02——1e-3 在两者之间。
const TRACK_CONST_MAX_DEV: f32 = 1e-3;
/// 镜像对账容差：主样本反解位与对侧存储位差 0.0000，顺推位差 0.21——0.05 居中。
const MIRROR_TOLERANCE: f32 = 0.05;
/// 解剖对账：重建骨到父骨位距离的上界。全库已知最大骨距 3.18（挂件链
/// bone05→bone06），取 4.5 留余量；超出即视为重建失败。
pub const MAX_PARENT_DISTANCE: f32 = 4.5;
/// 语义命中率闸门：命中 * 3 ≥ 干净骨数 * 2（即 ≥2/3）。
const HIT_RATE_NUM: usize = 2;
const HIT_RATE_DEN: usize = 3;

/// 一根骨的重建位从哪来（人话注记与测试用）。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RestSource {
    /// `.mesh` 96B 存储记录求逆（权威值，非本模块推导）。
    Stored,
    /// 由有记录孩子的存储世界反解（`W_parent = L_rec(child)⁻¹ · W_child`）。
    ChildSolve,
    /// 沿父骨世界顺推（`W_j = L_rec(j) · W_parent`，平移吃自身轨道常量）。
    RestFallback,
    /// 重建不出来或自检不过：保持 `None`，不编坐标。
    Unresolved,
}

/// 自检与重建的逐项计数——如实报数，命中率低的怪不许藏。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct RestStats {
    /// 干净记录骨数（自有 96B 记录且父骨也有）：语义自检的样本集。
    pub clean_bones: usize,
    /// qrest 反旋转 vs 存储局部旋转 ≤[`ROTATION_TOLERANCE_DEG`] 的根数。
    pub rotation_hits: usize,
    /// 轨道常量 vs 存储局部平移 ≤[`TRANSLATION_TOLERANCE`] 的根数。
    pub translation_hits: usize,
    /// 反解补上的骨数。
    pub solved: usize,
    /// 顺推补上的骨数。
    pub fallback: usize,
    /// 没补上（保持 `None`）的骨数。
    pub unresolved: usize,
    /// 镜像对账查了几对 / 几对吻合。
    pub mirror_checked: usize,
    pub mirror_matched: usize,
    /// 「反解位到父骨距 ≠ 自身轨道常量模长」的骨数。反解位与自身轨道常量本来就可能
    /// 不一致（主样本 spine1/neck 实测不一致）——如实计数，不当闸门。
    pub const_mismatches: usize,
}

/// 重建结果。`positions`/`sources` 与 `h.bones` 同序。
#[derive(Debug, Clone, PartialEq)]
pub struct RestRebuild {
    /// 逐骨 bind 世界位置（行向量口径第 4 行）。记录骨 = 存储求逆；无记录骨 =
    /// 反解/顺推（自检不过的为 `None`）。
    pub positions: Vec<Option<[f32; 3]>>,
    /// 逐骨来源。
    pub sources: Vec<RestSource>,
    pub stats: RestStats,
}

/// 四元数 → 旋转矩阵的**被动（行向量存储）读法**：= [`quat_to_mat`]`(q)` 的转置。
///
/// 静态区 `qrest` 存的是 bind 局部旋转的逆（被动约定），所以 bind 局部旋转
/// （行向量口径）= 本函数(qrest)。研究班 hit-rate 15/20、13/16、14/16 的对账
/// 就是用这个读法算的（k2_final.txt 分量序 battery 最优 (0,1,2,3) inv=0）。
pub fn quat_to_mat_passive(q: &[f32; 4]) -> [f32; 16] {
    let m = quat_to_mat(q);
    let mut o = [0f32; 16];
    for r in 0..4 {
        for c in 0..4 {
            o[r * 4 + c] = m[c * 4 + r];
        }
    }
    o
}

/// 两个行向量旋转矩阵（取 3×3 块）的夹角（度）。正交阵下相对旋转的迹
/// = 两块 3×3 的 Frobenius 内积，不用真的乘出来。
fn rotation_angle_deg(a: &[f32; 16], b: &[f32; 16]) -> f32 {
    let dot: f32 = (0..3)
        .flat_map(|r| (0..3).map(move |c| a[r * 4 + c] * b[r * 4 + c]))
        .sum();
    let cos = ((dot - 1.0) / 2.0).clamp(-1.0, 1.0);
    cos.acos().to_degrees()
}

fn dist(a: [f32; 3], b: [f32; 3]) -> f32 {
    ((a[0] - b[0]).powi(2) + (a[1] - b[1]).powi(2) + (a[2] - b[2]).powi(2)).sqrt()
}

fn valid_pos(p: [f32; 3]) -> bool {
    p.iter().copied().all(f32::is_finite)
}

/// 中位数（偶数个取中间两数的平均，与研究班 np.median 同口径）。
fn median(mut v: Vec<f32>) -> Option<f32> {
    if v.is_empty() {
        return None;
    }
    v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
    Some(match v.len() % 2 {
        0 => (v[v.len() / 2 - 1] + v[v.len() / 2]) / 2.0,
        _ => v[v.len() / 2],
    })
}

/// `_l_` ↔ `_r_` 互转；不含该模式的骨名（框架骨、bone 系）返回 `None`。
fn mirror_name(name: &str) -> Option<String> {
    if let Some(rest) = name.split_once("_l_") {
        return Some(format!("{}_r_{}", rest.0, rest.1));
    }
    if let Some(rest) = name.split_once("_r_") {
        return Some(format!("{}_l_{}", rest.0, rest.1));
    }
    None
}

/// 一根骨从 `.ani` 里能拿到的静态数据。
#[derive(Debug, Clone, Default)]
struct RestTrack {
    qrest: Option<[f32; 4]>,
    /// 轨道平移中位数（有轨道才有）。
    t_const: Option<[f32; 3]>,
    /// 平移通道是否恒定（非常量 = root motion，不能当 bind 偏移用）。
    t_is_const: bool,
}

impl RestTrack {
    /// rest 局部矩阵 L_rec（行向量口径）：旋转 = qrest 的被动读法，平移 = 轨道常量。
    fn local_matrix(&self) -> Option<[f32; 16]> {
        let mut m = match self.qrest {
            Some(q) => quat_to_mat_passive(&q),
            None => mat_identity(),
        };
        let t = self.t_const?;
        m[12] = t[0];
        m[13] = t[1];
        m[14] = t[2];
        m[15] = 1.0;
        Some(m)
    }
}

/// 重建无 96B 记录骨的 bind 位置。
///
/// 输入：骨架（[`super::geometry::parse_hierarchy`] 的产物）+ 同一副骨架任一条
/// `.ani` 的解析结果 + 静态区（[`super::anim::rest_poses`] 的产物，与 `anim.tracks`
/// 同序）。任何前置条件不满足（对不上名、自检不过）→ `None`，调用方维持原状。
pub fn rebuild_bind_positions(
    h: &SkeletonHierarchy,
    anim: &Anim,
    rests: &[Rest],
) -> Option<RestRebuild> {
    let n = h.bones.len();
    if n == 0 || rests.len() != anim.tracks.len() || anim.tracks.is_empty() {
        return None;
    }
    // 骨名 → 下标。轨道名必须都能对上骨架：静态区是「属于这副骨架」的前提证据，
    // 对不上就说明拿错了怪的数据，整体不采用。
    let mut index: HashMap<&str, usize> = HashMap::with_capacity(n);
    for (i, b) in h.bones.iter().enumerate() {
        index.insert(b.name.as_str(), i);
    }
    let mut per: Vec<RestTrack> = vec![RestTrack::default(); n];
    for (i, track) in anim.tracks.iter().enumerate() {
        if track.bone.is_empty() {
            continue; // 未命名轨道对不上骨名，不按位置硬配
        }
        let Some(&j) = index.get(track.bone.as_str()) else {
            return None; // 有名字的轨道对不上这副骨架：静态区不是这副骨架的
        };
        let Some(rest) = rests.get(i) else { return None };
        per[j].qrest = Some(rest.rotation);
        let mut xs = Vec::with_capacity(track.positions.len());
        let mut ys = Vec::with_capacity(track.positions.len());
        let mut zs = Vec::with_capacity(track.positions.len());
        for p in &track.positions {
            xs.push(p[0]);
            ys.push(p[1]);
            zs.push(p[2]);
        }
        let (mx, my, mz) = (median(xs)?, median(ys)?, median(zs)?);
        let med = [mx, my, mz];
        let max_dev = track
            .positions
            .iter()
            .map(|p| {
                p.iter()
                    .zip(med.iter())
                    .map(|(a, b)| (a - b).abs())
                    .fold(0f32, f32::max)
            })
            .fold(0f32, f32::max);
        per[j].t_const = Some(med);
        per[j].t_is_const = max_dev <= TRACK_CONST_MAX_DEV;
    }

    // 存储世界：记录骨 = 存储矩阵求逆。有一根求不出（数据坏）就整体不干——
    // 重建的全部对账都以存储口径为基准，基准缺一块就没法自检。
    let mut worlds: Vec<Option<[f32; 16]>> = vec![None; n];
    for (i, b) in h.bones.iter().enumerate() {
        if let Some(s) = b.bind {
            let inv = mat_inverse_affine(&s)?;
            worlds[i] = Some(inv);
        }
    }
    let stored_world = worlds.clone();

    // ---- 自检闸门：干净记录骨上的静态区语义命中率 ----
    let missing: Vec<usize> = (0..n).filter(|&i| h.bones[i].bind.is_none()).collect();
    let mut stats = RestStats::default();
    if !missing.is_empty() {
        for j in 0..n {
            let Some(parent) = h.bones[j].parent else { continue };
            // 干净骨 = 自有记录且父骨有记录（两边的世界都来自存储，局部可独立复算）
            if h.bones[j].bind.is_none() || h.bones[parent].bind.is_none() {
                continue;
            }
            let (Some(wj), Some(wp)) = (worlds[j], worlds[parent]) else { continue };
            let Some(local) = mat_inverse_affine(&wp).map(|wp_inv| mat_mul(&wj, &wp_inv)) else {
                continue;
            };
            stats.clean_bones += 1;
            if let Some(q) = per[j].qrest {
                if rotation_angle_deg(&local, &quat_to_mat_passive(&q)) <= ROTATION_TOLERANCE_DEG {
                    stats.rotation_hits += 1;
                }
            }
            if let (true, Some(t)) = (per[j].t_is_const, per[j].t_const) {
                let d = dist([local[12], local[13], local[14]], t);
                if d <= TRANSLATION_TOLERANCE {
                    stats.translation_hits += 1;
                }
            }
        }
        // 命中率 < 2/3（旋转、平移分别算）或干净骨为 0（没有对账样本）：
        // 静态区语义在这副骨架上立不住（比如布局不同的另一只怪），整体回退。
        let rot_ok = stats.rotation_hits * HIT_RATE_DEN >= stats.clean_bones * HIT_RATE_NUM;
        let tr_ok = stats.translation_hits * HIT_RATE_DEN >= stats.clean_bones * HIT_RATE_NUM;
        if stats.clean_bones == 0 || !rot_ok || !tr_ok {
            return None;
        }
    }

    // ---- 重建（定点迭代：反解不依赖别的无记录骨，顺推依赖父骨世界）----
    let mut sources: Vec<RestSource> = (0..n)
        .map(|i| if h.bones[i].bind.is_some() { RestSource::Stored } else { RestSource::Unresolved })
        .collect();
    if missing.is_empty() {
        // 没有要补的骨：原样返回存储口径（调用方当作 no-op）。
        return Some(RestRebuild {
            positions: stored_world
                .iter()
                .map(|w| w.map(|m| [m[12], m[13], m[14]]))
                .collect(),
            sources,
            stats,
        });
    }
    let children: Vec<Vec<usize>> = {
        let mut c: Vec<Vec<usize>> = vec![Vec::new(); n];
        for (i, b) in h.bones.iter().enumerate() {
            if let Some(p) = b.parent {
                c[p].push(i);
            }
        }
        c
    };
    for _ in 0..=n {
        let mut progress = false;
        for &j in &missing {
            if worlds[j].is_some() {
                continue;
            }
            // 优先：有记录孩子反解。多个孩子逐个解、互相对账，对不上就不用。
            let rec_kids: Vec<usize> = children[j]
                .iter()
                .copied()
                .filter(|&c| worlds[c].is_some())
                .collect();
            let mut cands: Vec<[f32; 16]> = Vec::new();
            for c in &rec_kids {
                let Some(l) = per[*c].local_matrix() else { continue };
                let Some(l_inv) = mat_inverse_affine(&l) else { continue };
                cands.push(mat_mul(&l_inv, &worlds[*c].unwrap()));
            }
            let agree = |a: &[f32; 16], b: &[f32; 16]| {
                rotation_angle_deg(a, b) <= ROTATION_TOLERANCE_DEG
                    && dist([a[12], a[13], a[14]], [b[12], b[13], b[14]]) <= TRANSLATION_TOLERANCE
            };
            let solved = match cands.len() {
                0 => None,
                1 => Some(cands[0]),
                _ => {
                    let first = cands[0];
                    if cands[1..].iter().all(|c| agree(&first, c)) {
                        Some(first)
                    } else {
                        None // 孩子之间对不上：数据不自洽，不硬选一个
                    }
                }
            };
            if let Some(w) = solved {
                worlds[j] = Some(w);
                sources[j] = RestSource::ChildSolve;
                stats.solved += 1;
                progress = true;
                continue;
            }
            // 其次：沿父骨世界顺推。只给平移通道恒定的骨——非常量 = root motion，
            // 中位数不是 bind 偏移，拿来当位置就是编造。
            let parent = h.bones[j].parent;
            if let (Some(p), true, Some(l)) = (parent, per[j].t_is_const, per[j].local_matrix()) {
                if let Some(wp) = worlds[p] {
                    worlds[j] = Some(mat_mul(&l, &wp));
                    sources[j] = RestSource::RestFallback;
                    stats.fallback += 1;
                    progress = true;
                }
            }
        }
        if !progress {
            break;
        }
    }

    // ---- 逐骨出值 + 镜像/解剖对账 ----
    let mut positions: Vec<Option<[f32; 3]>> = vec![None; n];
    for i in 0..n {
        if let Some(w) = stored_world[i] {
            positions[i] = Some([w[12], w[13], w[14]]);
        }
    }
    for &j in &missing {
        let Some(w) = worlds[j] else { continue };
        let pos = [w[12], w[13], w[14]];
        // 镜像对账：与有存储记录的对侧同名骨比（l↔r，绕 x=0 矢状面）。
        let mut mirror_broken = false;
        if let Some(mn) = mirror_name(&h.bones[j].name) {
            if let Some(&k) = index.get(mn.as_str()) {
                if h.bones[k].bind.is_some() {
                    if let Some(mp) = positions[k] {
                        stats.mirror_checked += 1;
                        let ok = (pos[1] - mp[1]).abs() <= MIRROR_TOLERANCE
                            && (pos[2] - mp[2]).abs() <= MIRROR_TOLERANCE
                            && (pos[0] + mp[0]).abs() <= MIRROR_TOLERANCE;
                        if ok {
                            stats.mirror_matched += 1;
                        } else {
                            mirror_broken = true;
                        }
                    }
                }
            }
        }
        // 解剖对账：到父骨位的距离落在骨长量级（全库已知最大 3.18）。
        let anatomy_ok = match h.bones[j].parent {
            None => true,
            Some(p) => match positions[p] {
                Some(pp) => dist(pos, pp) <= MAX_PARENT_DISTANCE,
                None => true, // 父骨自己都没有位置可参照：树是连通的，这只在父骨也被拦下时发生
            },
        };
        // 如实计数：反解位与自身轨道常量父距是否一致（不当闸门，只报数）。
        if sources[j] == RestSource::ChildSolve {
            if let (Some(p), true, Some(t)) =
                (h.bones[j].parent, per[j].t_is_const, per[j].t_const)
            {
                if let Some(pp) = positions[p] {
                    let len = (t[0] * t[0] + t[1] * t[1] + t[2] * t[2]).sqrt();
                    if (dist(pos, pp) - len).abs() > TRANSLATION_TOLERANCE {
                        stats.const_mismatches += 1;
                    }
                }
            }
        }
        if valid_pos(pos) && !mirror_broken && anatomy_ok {
            positions[j] = Some(pos);
        } else {
            // 可疑的推导值不发出去：回 None，来源一并标记，计数扣回
            //（solved/fallback 最终只数真正补上的）。
            if sources[j] == RestSource::ChildSolve {
                stats.solved -= 1;
            } else if sources[j] == RestSource::RestFallback {
                stats.fallback -= 1;
            }
            sources[j] = RestSource::Unresolved;
        }
    }
    stats.unresolved = missing.iter().filter(|&&j| positions[j].is_none()).count();
    Some(RestRebuild { positions, sources, stats })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::preview::geometry::{BoneNode, SkeletonHierarchy};

    fn hierarchy(bones: Vec<(&str, Option<usize>, Option<[f32; 16]>)>) -> SkeletonHierarchy {
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

    fn stored_of(world: &[f32; 16]) -> [f32; 16] {
        // 存储值 = 世界绑定矩阵的逆（pose::bind_worlds 口径）
        mat_inverse_affine(world).expect("世界矩阵可逆")
    }

    fn translation(x: f32, y: f32, z: f32) -> [f32; 16] {
        let mut m = mat_identity();
        m[12] = x;
        m[13] = y;
        m[14] = z;
        m
    }

    fn anim_of(names: &[(&str, [f32; 3])]) -> Anim {
        Anim {
            envelope: crate::preview::Envelope {
                banner: "t".into(),
                tag: "ani".into(),
                version: 2,
                note: String::new(),
            },
            bones: names.len(),
            frames: 2,
            tick: 40.0,
            tracks: names
                .iter()
                .map(|(name, t)| crate::preview::Track {
                    bone: name.to_string(),
                    rotations: vec![[0.0, 0.0, 0.0, 1.0]; 2],
                    positions: vec![*t; 2],
                    scales: vec![1.0; 2],
                })
                .collect(),
        }
    }

    fn rest_of(names: &[&str], qrests: &[[f32; 4]], offsets: &[[f32; 3]]) -> Vec<Rest> {
        names
            .iter()
            .enumerate()
            .map(|(i, name)| Rest {
                bone: name.to_string(),
                unit: [0.00992; 3],
                rotation: qrests[i],
                offset: offsets[i],
            })
            .collect()
    }

    /// 合成正样本：r(记录) → s(记录, 干净骨) / m(缺失) → t(记录)。
    /// 真实 bind：r 在原点、m 在 (1,2,3)、t 在 m 的 (0.5,0,0)、s 在 r 的 (0.2,0,0)。
    /// 静态区数据按「qrest = bind 局部旋转的逆、轨道常量 = bind 局部平移」喂进去，
    /// 重建应当精确还原（这副合成骨架的真实 bind 是测试自己定的，不依赖任何口径）。
    #[test]
    fn 合成骨架上反解精确且自检全中() {
        let q_identity = [0.0f32, 0.0, 0.0, 1.0];
        let w_r = mat_identity();
        let w_m = translation(1.0, 2.0, 3.0);
        let w_t = mat_mul(&translation(0.5, 0.0, 0.0), &w_m);
        let w_s = translation(0.2, 0.0, 0.0);
        let h = hierarchy(vec![
            ("r", None, Some(stored_of(&w_r))),
            ("s", Some(0), Some(stored_of(&w_s))),
            ("m", Some(0), None),
            ("t", Some(2), Some(stored_of(&w_t))),
        ]);
        let anim = anim_of(&[
            ("r", [0.0, 0.0, 0.0]),
            ("s", [0.2, 0.0, 0.0]),
            ("m", [1.0, 2.0, 3.0]),
            ("t", [0.5, 0.0, 0.0]),
        ]);
        let rests = rest_of(
            &["r", "s", "m", "t"],
            &[q_identity, q_identity, q_identity, q_identity],
            &[[0.0; 3]; 4],
        );
        let rb = rebuild_bind_positions(&h, &anim, &rests).expect("自检应通过");
        assert_eq!(rb.stats.clean_bones, 1, "干净骨 = s（r 记录 + s 记录）");
        assert_eq!(rb.stats.rotation_hits, 1);
        assert_eq!(rb.stats.translation_hits, 1);
        // m 由有记录孩子 t 反解：W_m = L_t⁻¹ · W_t = (1,2,3)（t 无旋转、平移 0.5）
        assert_eq!(rb.positions[2], Some([1.0, 2.0, 3.0]), "反解应精确还原 m");
        assert_eq!(rb.sources[2], RestSource::ChildSolve);
        // r/s/t 用存储口径
        assert_eq!(rb.positions[0], Some([0.0, 0.0, 0.0]));
        assert_eq!(rb.positions[1], Some([0.2, 0.0, 0.0]));
        assert_eq!(rb.positions[3], Some([1.5, 2.0, 3.0]));
    }

    /// 合成顺推：m 没有有记录孩子时沿父骨世界 + 自身轨道常量顺推，位置精确。
    #[test]
    fn 合成骨架上顺推补叶子骨() {
        let w_r = mat_identity();
        let w_s = translation(0.2, 0.0, 0.0);
        let h = hierarchy(vec![
            ("r", None, Some(stored_of(&w_r))),
            ("s", Some(0), Some(stored_of(&w_s))),
            ("m", Some(0), None),
        ]);
        let anim = anim_of(&[("r", [0.0; 3]), ("s", [0.2, 0.0, 0.0]), ("m", [1.0, 2.0, 3.0])]);
        let rests = rest_of(
            &["r", "s", "m"],
            &[[0.0, 0.0, 0.0, 1.0]; 3],
            &[[0.0; 3]; 3],
        );
        let rb = rebuild_bind_positions(&h, &anim, &rests).expect("自检应通过");
        assert_eq!(rb.sources[2], RestSource::RestFallback);
        assert_eq!(rb.positions[2], Some([1.0, 2.0, 3.0]), "顺推 = 父世界 ∘ 常量平移");
    }

    /// 自检闸门（红）：把干净骨的 qrest 换成错的旋转 → 命中率挂零 → 整体 None。
    /// 这就是「另一只怪的静态区/布局不同就不硬给」的落码形态。
    #[test]
    fn 语义命中率不过就整体回退() {
        let w_r = mat_identity();
        let w_s = translation(0.2, 0.0, 0.0);
        let h = hierarchy(vec![
            ("r", None, Some(stored_of(&w_r))),
            ("s", Some(0), Some(stored_of(&w_s))),
            ("m", Some(0), None),
        ]);
        let anim = anim_of(&[("r", [0.0; 3]), ("s", [0.2, 0.0, 0.0]), ("m", [1.0, 2.0, 3.0])]);
        // 绕 z 转 90° 的错误 qrest（被动读法下与存储局部旋转差 90°）
        let q_bad = [0.0f32, 0.0, -std::f32::consts::FRAC_1_SQRT_2, std::f32::consts::FRAC_1_SQRT_2];
        let rests = rest_of(
            &["r", "s", "m"],
            &[q_bad, q_bad, q_bad],
            &[[0.0; 3]; 3],
        );
        assert_eq!(rebuild_bind_positions(&h, &anim, &rests), None, "旋转语义不过 → 整体 None");
        // 平移语义错：干净骨的轨道常量 ≠ 存储局部平移 → 同样整体 None
        let anim_bad_t = anim_of(&[("r", [0.0; 3]), ("s", [9.0, 9.0, 9.0]), ("m", [1.0, 2.0, 3.0])]);
        let rests_ok = rest_of(
            &["r", "s", "m"],
            &[[0.0, 0.0, 0.0, 1.0]; 3],
            &[[0.0; 3]; 3],
        );
        assert_eq!(
            rebuild_bind_positions(&h, &anim_bad_t, &rests_ok),
            None,
            "平移语义不过 → 整体 None"
        );
        // 有名字的轨道对不上骨架（拿错怪的静态区）→ None
        let anim_stray = anim_of(&[("r", [0.0; 3]), ("s", [0.2, 0.0, 0.0]), ("ghost", [1.0, 2.0, 3.0])]);
        assert_eq!(
            rebuild_bind_positions(&h, &anim_stray, &rests_ok),
            None,
            "轨道名对不上骨架 → None"
        );
        // 静态区与轨道数不一致 → None
        assert_eq!(rebuild_bind_positions(&h, &anim, &rests[..2]), None);
    }

    /// 没有要补的骨时是 no-op；干净骨为 0 且有缺失时不给值。
    #[test]
    fn 无缺失时原样返回_无对账样本时不硬给() {
        let w = translation(1.0, 2.0, 3.0);
        let h = hierarchy(vec![("a", None, Some(stored_of(&w))), ("b", Some(0), Some(stored_of(&w)))]);
        let anim = anim_of(&[("a", [0.0; 3]), ("b", [0.0; 3])]);
        let rests = rest_of(&["a", "b"], &[[0.0, 0.0, 0.0, 1.0]; 2], &[[0.0; 3]; 2]);
        let rb = rebuild_bind_positions(&h, &anim, &rests).expect("无缺失应返回存储口径");
        assert_eq!(rb.positions[0], Some([1.0, 2.0, 3.0]));
        assert_eq!(rb.stats.solved + rb.stats.fallback, 0);

        // 单根记录骨 + 一根缺失骨：干净骨 = 0（缺失骨是根的子，但根没记录……
        // 这里构造「父缺失、子记录」的形状：没有对账样本 → 整体 None）
        let h2 = hierarchy(vec![("m", None, None), ("t", Some(0), Some(stored_of(&w)))]);
        let anim2 = anim_of(&[("m", [0.0; 3]), ("t", [0.0; 3])]);
        let rests2 = rest_of(&["m", "t"], &[[0.0, 0.0, 0.0, 1.0]; 2], &[[0.0; 3]; 2]);
        assert_eq!(
            rebuild_bind_positions(&h2, &anim2, &rests2),
            None,
            "没有干净骨可对账就不给推导值"
        );
    }

    /// 镜像对账：重建位与对侧**存储**位不镜像（y 差 4.0）→ 这根骨回 None。
    #[test]
    fn 镜像不过的骨保持_none() {
        let w_r = mat_identity();
        // 对侧 r_a 有存储记录，位置 (0.3, 1.0, 0)；l_a 无记录，靠顺推补——
        // 故意喂一条 y=5 的轨道常量，顺推出的 y=5 与对侧 y=1 差 4.0，镜像闸门应拦下。
        let w_ra = translation(0.3, 1.0, 0.0);
        let h = hierarchy(vec![
            ("r", None, Some(stored_of(&w_r))),
            ("bip01_r_a", Some(0), Some(stored_of(&w_ra))),
            ("bip01_l_a", Some(0), None),
        ]);
        let anim = anim_of(&[
            ("r", [0.0; 3]),
            ("bip01_r_a", [0.3, 1.0, 0.0]),
            ("bip01_l_a", [0.3, 5.0, 0.0]),
        ]);
        let rests = rest_of(
            &["r", "bip01_r_a", "bip01_l_a"],
            &[[0.0, 0.0, 0.0, 1.0]; 3],
            &[[0.0; 3]; 3],
        );
        let rb = rebuild_bind_positions(&h, &anim, &rests).expect("干净骨 r_a 命中，整体不回退");
        assert_eq!(rb.stats.mirror_checked, 1);
        assert_eq!(rb.stats.mirror_matched, 0, "y 差 4.0 远超容差");
        assert_eq!(rb.positions[2], None, "镜像不过的骨不许给值");
        // 正向：l_a 的常量与对侧镜像一致时，镜像对账应放行
        let anim_ok = anim_of(&[
            ("r", [0.0; 3]),
            ("bip01_r_a", [0.3, 1.0, 0.0]),
            ("bip01_l_a", [-0.3, 1.0, 0.0]),
        ]);
        let rb_ok = rebuild_bind_positions(&h, &anim_ok, &rests).expect("自检应通过");
        assert_eq!(rb_ok.stats.mirror_matched, 1);
        assert_eq!(rb_ok.positions[2], Some([-0.3, 1.0, 0.0]));
    }
}
