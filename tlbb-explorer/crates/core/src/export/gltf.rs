//! `.mesh` 几何 → glTF 2.0 (`.glb`) 二进制。
//!
//! 为什么要这一层：浏览器和市面上所有 3D 查看器都不认识私有 `.mesh`，
//! 但都认识 glTF。把几何导成 glb 之后，"在浏览器里转着看"就不再依赖
//! 自研查看器——glb 是**产物**，不是中间格式，导错了要能看出来。
//!
//! 只导**已证实**的东西：
//! - `POSITION`（必需，带 min/max）、`NORMAL`、`TEXCOORD_0` 只在解析器给出时才写；
//! - 每个子网格一个 primitive，各带自己的材质槽（引擎侧一槽 = 一次 draw call）；
//! - 索引 `u16`（`5123`），子网格索引在文件里本来就连续排列，切 accessor 即可；
//! - `doubleSided = true`：绕序还没核实，剔背面会整块黑；
//! - **骨架 / 蒙皮 / 动画**（[`to_glb_rigged`]，2026-10-05 起）：蒙皮权重在
//!   `.mesh` 里按骨组织（`preview::SkinInfluence`，2026-09-30 解出）、父骨链
//!   也在 `.mesh` 尾部孩子名单的并（`preview::parse_hierarchy`，2026-10-05 解出）、
//!   动作是 `.ani` 的逐骨逐帧局部 TRS（`preview::parse_ani`）。node 树与 skin
//!   （JOINTS_0/WEIGHTS_0/inverseBindMatrices）原样带出；**动画轨道自 2026-10-07
//!   起重定基（rebase）到 bind rest**——不再原样抄 `.ani` 局部轨道（见下）。
//!   骨架/几何/权重数据本身仍是存储值，没有任何编造。
//!
//! # 口径与未证项（导出前必读）
//!
//! * **存储的 96B 绑定矩阵是「骨→世界」绑定矩阵的逆**（`B = S⁻¹`，即 glTF 的
//!   `inverseBindMatrix`、D3DX 的 bone offset）。判据是物理的：骨位应贴着它蒙皮
//!   顶点的加权重心——现口径 mean 0.149，把存储值直接当骨位是 1.439（骨架会躺在
//!   地上）。证据链与翻案经过见 `preview::pose::bind_worlds`。bind 世界矩阵与
//!   4×4 工具**直接 use pose 那一份**，本文件不再抄第二份（抄过一次，翻案当天
//!   就分叉，被规范侧对账闸门抓住）。glTF node 的变换必须是**局部**的，所以
//!   有矩阵的骨取 `local = B子 · B父⁻¹`；没矩阵的骨 node 仍在（joints 引用必须
//!   完整）、局部恒等并按 README 口径写明缺失。
//! * **动画必须重定基（rebase）到 bind rest（2026-10-07 播放锚裁决）**。`.ani`
//!   的第 0 帧骨架与 `.mesh` 的 bind 骨架**不同源**（frame0≠bind，中位 |Δt| 1.92、
//!   角差 115.9°），而播放的正确锚是**每条动作自己的 frame0**（证据：四种锚 ×
//!   15 条动作全量比对，frame0 锚 15/15 全胜裸 bind 锚，档案
//!   `.scratch/ani_axis/锚点判定_20261007.md`）。如果把 `.ani` 原始局部轨道直接
//!   写进 glTF，查看器的蒙皮是 `B⁻¹·W_t`（B = bind 世界），而 app 内播放是
//!   `A⁻¹·W_t`（A = frame0 世界，`pose::reanchored_palette`）——锚不同源，播起来
//!   撕成尖刺。所以导出时把动画**搬进 bind 的历史**：
//!
//!   ```text
//!   W'_j(t) = B_j · A_j⁻¹ · W_j(t)        （行向量约定，全部走 pose 层现成函数）
//!   导出局部轨道 L'_j(t) = W'_j(t) · W'_parent(t)⁻¹
//!   ```
//!
//!   这样查看器按标准 glTF 蒙皮（IBM·N）播出来的每一帧 `B⁻¹·W' = A⁻¹·W` 与
//!   app 内 frame0 锚蒙皮**逐顶点一致**；且 t=0 时 W' = B 恰好落在 node rest 上
//!   ——第 0 帧不撕。代价与回退：GLB 里的动画轨道不再是 `.ani` 的存储值（原始
//!   轨道仍在 `.ani` 文件里，`skel_dump` 照旧出原始数据）；**没有动画的导出
//!   （静态 `to_glb`、rigged 但 `anims` 为空）完全不受影响**，node rest 与 IBM
//!   依旧来自 `.mesh` 存储矩阵。app 内的绝对朝向/相位等未证项随锚继承，见
//!   `pose::reanchored_palette` 的如实标注。
//! * **权重和必须为 1.0**（glTF 硬要求，官方校验器实测会把不对的报成
//!   `ACCESSOR_WEIGHTS_NON_NORMALIZED`）。`.mesh` 的影响表按骨组织，一部分顶点
//!   只读到一部分骨（缺的那些骨没有 96B 记录，主样本实测 114 个顶点 Σw = 0.815
//!   这类）。这里**不给缺失骨编比例**：把差额 `1 − Σw` 挂到根骨——根骨没有轨道、
//!   导出世界是恒等阵，权重落在它身上就等于那一份顶点**不跟随变形**，与「未覆盖
//!   顶点原地不动」是同一条既有口径。引擎侧 `preview::pose::posed_vertices`
//!   按同一规则算，两边蒙皮结果逐元素相等（闸门 `tests/glb_spec_skin.rs`）。
//! * **四元数分量序按 D3DX 惯例取 (x,y,z,w)**（glTF 恰好同序）。重定基后导出的
//!   rotation 轨道是 W' 分解出的四元数（decompose_trs → mat3_to_quat），与引擎侧
//!   `pose::quat_to_mat` 走同一套约定——就算 `.ani` 原始四个 f32 的分量序另有
//!   真相（未从字节钉死，anim.rs 只证了「单位长」），锚与复合两侧同约定，对齐
//!   不受影响；原始轨道仍可用 `skel_dump` 取出。
//! * **帧率刻度**（`.ani` 0xC6，样本恒 40.0）含义未证；animation 的关键帧时间
//!   按「每秒 tick 数」解读写成 `帧号/tick`，这是**已标注的解读**不是实测结论。
//! * **四元数按帧定半球后才写**（[`same_hemisphere`]）：q 与 −q 是同一个旋转，
//!   但 glTF 里 rotation 通道的 `LINEAR` 是**归一化线性插值**，相邻帧反号会在中点
//!   算出零四元数 → NaN/翻面。主样本实测 675 条轨道、24,300 对相邻帧里 86 对反号
//!   （最小点积 −1.0000001）；本仓 three.js 走 slerpFlat 自带符号纠正才侥幸免疫，
//!   不能当通用结论。引擎侧 `pose::quat_to_mat` 对 q 与 −q 给出同一张矩阵，
//!   所以这只影响导出写法，不影响播放口径。
//! * **accessor 按规范 3.6.2 的对齐表补零**：VEC3→12、VEC4(f32)→16、VEC4(u16)→8、
//!   MAT4→64。官方校验器只按 4 字节查（所以这一条它不报），但把 buffer 直接映射成
//!   `float4x4`/`vec4` 的导入器会读歪。
//!
//! 坐标：客户端是 Y-up（实测立绘模型 y 跨度 = 身高），glTF 也是 Y-up 右手系，
//! 单位按米，不做任何轴向变换。
//!
//! # 行向量 → 列向量的矩阵推导（算错一次整个姿势就废，写死在这里）
//!
//! 引擎是 D3DX **行向量**、行主序：`v' = v · M`，前三行是基向量，第 4 行
//! `(tx,ty,tz,1)` 是平移。glTF 是**列向量**、列主序：`v' = M_gltf · v`。
//! 同一物理变换要求 `M_gltf = Mᵀ`（行向量放左边 = 转置后放右边）。
//! glTF 的 JSON 数组按**列主序**存 `M_gltf`：第 k 段 4 个数是 M_gltf 的第 k 列，
//! 而 `M_gltf` 的第 k 列 = `Mᵀ` 的第 k 列 = `M` 的第 k 行 —— 恰好是引擎行主序
//! 数组的第 k 段。**所以 16 个 f32 按原顺序照抄即可**：约定翻转（转置）与存储
//! 翻转（列主序）正好抵消。四元数同理：D3DX 行向量下 (x,y,z,w) 生成的旋转矩阵
//! 是列向量标准公式的转置，转置抵消后 glTF 用同一组分量得到同一物理旋转，
//! 不取共轭（推导：pose 层 `quat_to_mat` 的 m[1]=2(xy+wz) 是列向量公式 R[1][0]
//! 的位置，即行向量矩阵 = 列向量矩阵的转置）。

use serde_json::{json, Value};

use crate::preview::anim::Anim;
use crate::preview::geometry::{MeshLayout, Node, SkeletonHierarchy};
// 权重整形与槽位数与播放层共用一份（见 `pose::unify_weights`）；矩阵小工具
// 仍然是本文件自己实现——那是标准仿射代数，口径证据链在 preview::pose 的注释里。
use crate::preview::pose::{self, mat_inverse_affine, mat_mul};

/// 一个材质槽的展示信息。名字来自 `.mdl` / `.mtl`，没有就给槽号。
#[derive(Debug, Clone, Default)]
pub struct SlotStyle {
    pub name: Option<String>,
    /// 线性 RGBA，glTF 的 `baseColorFactor` 语义（不是 0-255）。
    pub base_color: Option<[f32; 4]>,
    }

const DEFAULT_GRAY: [f32; 4] = [0.62, 0.65, 0.69, 1.0];
const CHUNK_JSON: u32 = 0x4E4F_534A;
const CHUNK_BIN: u32 = 0x004E_4942;
const GLB_MAGIC: u32 = 0x4654_6C67;

/// 蒙皮导出的输入：骨架树 + 按骨组织的权重表。
///
/// * `hierarchy` 是 `preview::parse_hierarchy` 的输出——joint 顺序 = `bones`
///   顺序（深度优先，唯一根在首位），这就是「骨序映射」：骨名 → 下标。
/// * `influences` 是 `preview::parse_nodes` 的输出：每条 96B 节点记录的
///   按骨影响顶点表（骨名 → 顶点号 + 权重）。骨名对不上 `hierarchy` 的
///   （如 `origin`/`top` 前奏）会被跳过并计数，不硬挂。
#[derive(Debug, Clone)]
pub struct RigExport<'a> {
    pub hierarchy: &'a SkeletonHierarchy,
    pub influences: &'a [Node],
}

impl<'a> RigExport<'a> {
    /// 骨序映射：骨名 → `hierarchy.bones` 下标（= glTF joints 下标）。
    pub fn bone_index(&self) -> std::collections::HashMap<&'a str, usize> {
        self.hierarchy
            .bones
            .iter()
            .enumerate()
            .map(|(i, b)| (b.name.as_str(), i))
            .collect()
    }
}

/// 一条动画在导出时的对账数字：轨道多少条、按骨名对上骨架的多少条。
#[derive(Debug, Clone, Default)]
pub struct AnimStats {
    pub name: String,
    pub frames: usize,
    /// `.ani` 自己的轨道数（存储事实）。
    pub tracks: usize,
    /// `.ani` 轨道里按骨名对上骨架的条数（pose_frame 复合时真正吃到的）。
    pub matched_tracks: usize,
    /// rebase 后实际写出轨道的关节数。rebase 对**全部关节**统一做（不止 `.ani`
    /// 有轨道的那些）：W' 对无轨道的骨一般也在动（父骨在动），只写有轨道的
    /// 会让无轨道骨在查看器里钉死在 rest 上，与 app 内播放对不上。
    pub exported_tracks: usize,
    /// TRS 分解往返（decompose→recompose）残差超过 1e-5 的 (关节, 帧) 数。
    /// 理论上 0（W' 是刚体复合，TRS 无损）；出现非 0 说明有 TRS 表达不了的成分
    /// （如切变），导出的动画在那个骨那帧会变形失真——如实计数，不静默。
    pub trs_mismatch_frames: usize,
    /// 对不上骨架骨名的轨道名（未命名轨道记作 "(unnamed)"），照实报告不编。
    pub unmatched_tracks: Vec<String>,
}

/// 蒙皮/动画导出的对账数字（写进 glTF `asset.extras`，也打到 stderr）。
/// 「对不上」的东西在这里逐项报数，不在导出里圆。
#[derive(Debug, Clone, Default)]
pub struct RigStats {
    pub joints: usize,
    /// 没有 96B 绑定记录的骨：node 挂恒等局部，IBM 用沿父链补出的世界矩阵
    /// 求逆（与既有口径一致），README 口径「没矩阵的骨写明缺失」。
    pub bones_without_bind: Vec<String>,
    /// 带权重表但骨名不在骨架里的节点（如前奏记录），整表跳过。
    pub influence_nodes_not_in_hierarchy: Vec<String>,
    pub covered_vertices: usize,
    /// 没被任何影响表覆盖的顶点。glTF 的 skin 对整份网格生效，没有「不蒙皮」
    /// 的顶点；这些顶点挂到根骨、权重 1（根骨的导出世界是恒等阵时它们保持
    /// 存储位置不动，等价于引擎里「静态件跟模型走」），个数如实报。
    pub uncovered_vertices: usize,
    /// Σw 落在 1.0 容差窗口内、按和归一的顶点数（含本来就是 1.0 的）。
    pub normalized_vertices: usize,
    /// Σw 明显不足 1.0、把差额 `1 − Σw` 挂到根骨的顶点数（主样本实测 114）。
    /// 挂根骨 = 那一份不跟随变形：不给没带 96B 记录的骨编影响比例。
    pub root_fill_vertices: usize,
    /// 既不能挂根骨补差额、也不在容差窗口内（Σw > 1，或 4 个槽位占满），
    /// 只能按和归一的顶点数。
    pub weight_sum_off_vertices: usize,
    /// 影响超过 4 根、被截到权重最大的前 4 根的顶点数（实测样本 0）。
    pub over_influenced_vertices: usize,
    /// TRS 分解后回乘与原矩阵差超过 1e-4 的骨数（理论上 0；出现说明 bind
    /// 里有 TRS 表达不了的成分，如切变）。
    pub trs_mismatch_nodes: usize,
    pub animations: Vec<AnimStats>,
}

/// 拼一个静态 `.glb`。几何与子网格切分全部来自 [`MeshLayout`]。
pub fn to_glb(name: &str, l: &MeshLayout, slots: &[SlotStyle]) -> Result<Vec<u8>, String> {
    to_glb_rigged(name, l, slots, None, &[])
}

/// 拼一个带骨架/蒙皮/动画的 `.glb`。
///
/// * `rig = None` 且 `anims` 为空 → 与 [`to_glb`] 完全同产物；
/// * `rig = Some` → 建 node 层级 + skin（bind 世界矩阵求逆 + 逐顶点权重打包）；
/// * `anims` 非空 → 每条一个 glTF animation。**轨道是重定基（rebase）后的局部
///   TRS，不是 `.ani` 存储值的原样转抄**：导出局部 = W' = B·A⁻¹·W 沿父链差分
///   （推导与依据见模块注释「动画必须重定基」），使外部查看器按标准 glTF 蒙皮
///   播放的结果与 app 内逐动作 frame0 锚蒙皮（`pose::reanchored_palette`）逐顶点
///   一致。**全部关节**统一写轨道（rotation/translation/scale 三个通道），不止
///   `.ani` 有轨道的那些——无轨道的骨随父骨一起动，漏写就在查看器里钉死在 rest。
///   `.ani` 里对不上骨名的轨道照旧计数报告（见 `asset.extras`），不按位置硬配。
pub fn to_glb_rigged(
    name: &str,
    l: &MeshLayout,
    slots: &[SlotStyle],
    rig: Option<&RigExport>,
    anims: &[(&str, &Anim)],
) -> Result<Vec<u8>, String> {
    let g = &l.geometry;
    if g.vertex_count == 0 || g.indices.is_empty() {
        return Err("没有顶点或没有三角面，glb 里放不了空网格".to_string());
    }
    let vc = g.vertex_count as usize;
    // POSITION 的 min/max 是规范要求必给的：坐标里混进 NaN/Inf 时 f32::min/max
    // 会把它静默吞掉，产物边界就成了假的——这种数据不导出，报出来。
    if !g.positions.iter().take(vc).all(|p| p.iter().all(|v| v.is_finite())) {
        return Err("顶点坐标里有 NaN/Inf：边界值不可信，拒绝导出".to_string());
    }
    if !anims.is_empty() && rig.is_none() {
        return Err("有动作但没有骨架：轨道没有可挂的节点，拒绝导出".to_string());
    }

    let mut bin: Vec<u8> = Vec::new();
    let mut views: Vec<Value> = Vec::new();
    let mut accs: Vec<Value> = Vec::new();

    // POSITION（必需，且规范要求给 min/max）
    let (mut mn, mut mx) = ([f32::MAX; 3], [f32::MIN; 3]);
    for p in &g.positions {
        for k in 0..3 {
            mn[k] = mn[k].min(p[k]);
            mx[k] = mx[k].max(p[k]);
        }
    }
    let pos_view = push_attr(&mut bin, &mut views, 12, |o| {
        for p in g.positions.iter().take(vc) {
            o.extend_from_slice(&p[0].to_le_bytes());
            o.extend_from_slice(&p[1].to_le_bytes());
            o.extend_from_slice(&p[2].to_le_bytes());
        }
    });
    let pos_acc = accs.len();
    accs.push(json!({
        "bufferView": pos_view, "componentType": 5126, "count": vc, "type": "VEC3",
        "min": mn, "max": mx,
    }));

    let mut normal_acc = None;
    if g.normals.len() == vc {
        let v = push_attr(&mut bin, &mut views, 12, |o| {
            for n in g.normals.iter().take(vc) {
                o.extend_from_slice(&n[0].to_le_bytes());
                o.extend_from_slice(&n[1].to_le_bytes());
                o.extend_from_slice(&n[2].to_le_bytes());
            }
        });
        normal_acc = Some(accs.len());
        accs.push(json!({"bufferView": v, "componentType": 5126, "count": vc, "type": "VEC3"}));
    }
    let mut uv_acc = None;
    if l.uv_sets > 0 && g.uvs.len() == vc {
        let v = push_attr(&mut bin, &mut views, 8, |o| {
            for t in g.uvs.iter().take(vc) {
                o.extend_from_slice(&t[0].to_le_bytes());
                o.extend_from_slice(&t[1].to_le_bytes());
            }
        });
        uv_acc = Some(accs.len());
        accs.push(json!({"bufferView": v, "componentType": 5126, "count": vc, "type": "VEC2"}));
    }

    // 索引：每个子网格一个 accessor，指向同一段连续 u16 里的自己那一截。
    let idx_view = {
        push(&mut bin, &mut views, 4, Some(34963), |o| {
            for &x in &g.indices {
                o.extend_from_slice(&x.to_le_bytes());
            }
        })
    };
    let mut primitives = Vec::new();
    let mut material_names: Vec<SlotStyle> = Vec::new();
    let mut start = 0usize;
    for (k, &faces) in l.face_counts.iter().enumerate() {
        let count = faces as usize * 3;
        if count == 0 {
            continue;
        }
        let (amin, amax) = index_range(&g.indices[start..start + count]);
        let acc = accs.len();
        accs.push(json!({
            "bufferView": idx_view, "byteOffset": (start * 2) as u64,
            "componentType": 5123, "count": count, "type": "SCALAR",
            "min": [amin], "max": [amax],
        }));
        let mut attrs = json!({"POSITION": pos_acc});
        if let Some(n) = normal_acc {
            attrs["NORMAL"] = json!(n);
        }
        if let Some(t) = uv_acc {
            attrs["TEXCOORD_0"] = json!(t);
        }
        primitives.push(json!({
            "attributes": attrs,
            "indices": acc,
            "material": material_names.len() as u64,
            "mode": 4,
        }));
        let style = slots.get(k).cloned().unwrap_or_default();
        material_names.push(style);
        start += count;
    }
    if primitives.is_empty() {
        return Err("子网格面数求和为 0，没有可画的三角形".to_string());
    }

    let materials: Vec<Value> = material_names
        .iter()
        .enumerate()
        .map(|(k, style)| {
            let color = style.base_color.unwrap_or(DEFAULT_GRAY);
            json!({
                "name": style.name.clone().unwrap_or_else(|| format!("材质槽 {}", k + 1)),
                "doubleSided": true,
                "pbrMetallicRoughness": {
                    "baseColorFactor": color,
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.85,
                },
            })
        })
        .collect();

    // ------------------------------------------------------------------ 骨架
    // node 布局：nodes[0] = 网格节点（挂 skin），nodes[1+i] = 第 i 根骨。
    // joint 顺序 = hierarchy.bones 顺序（深度优先，唯一根在首位）。
    let mut stats = RigStats::default();
    let mut skin_json: Option<Value> = None;
    let mut joint_nodes: Vec<Value> = Vec::new();
    let mut joints: Vec<usize> = Vec::new();
    let mut root_joint_node = 1usize;

    if let Some(r) = rig {
        let bones = &r.hierarchy.bones;
        let index = r.bone_index();
        let mut root_bone = 0usize;
        for nd in r.influences {
            if nd.skin.is_some() && !index.contains_key(nd.name.as_str()) {
                stats.influence_nodes_not_in_hierarchy.push(nd.name.clone());
            }
        }

        let n = bones.len();
        stats.joints = n;
        // bind 世界矩阵直接取播放层那一份实现（`pose::bind_worlds`：存储的 96B
        // 矩阵是世界绑定的逆，无记录的骨沿父链补）。以前这里独立抄了一份填充
        // 循环，2026-10-06 口径翻案（S 是逆矩阵）时两份立刻分叉，被规范侧对账
        // 闸门当场抓住——同一个口径只许有一份代码。
        let worlds = pose::bind_worlds(r.hierarchy);
        for b in bones {
            if b.bind.is_none() {
                stats.bones_without_bind.push(b.name.clone());
            }
        }

        // node 局部变换：glTF 的父子复合是 world = parent_world · local（列向量）。
        // 行向量口径下引擎是 world = local · parent_world，解出
        // local = world_child · world_parent⁻¹。对有存储矩阵且父链上全是存储
        // 矩阵的骨，这正好等于 bind子 · bind父⁻¹；无矩阵的骨 world 与父相同，
        // local 恒等。根骨 local = 自身世界。这样任何按 glTF 规则复合的查看器，
        // 算出的骨世界矩阵都是存储值（或沿链补出的占位值）本身。
        let mut trs_nodes: Vec<Value> = Vec::with_capacity(n);
        for (i, b) in bones.iter().enumerate() {
            let local = match b.parent {
                None => worlds[i],
                Some(p) => {
                    let pinv = mat_inverse_affine(&worlds[p]).ok_or_else(|| {
                        format!("骨 {} 的父骨 {} 绑定矩阵不可逆，蒙皮立不住", b.name, bones[p].name)
                    })?;
                    mat_mul(&worlds[i], &pinv)
                }
            };
            let (t, q, s) = decompose_trs(&local);
            // 回乘验证：TRS 重建不出原矩阵（如带切变）就计数，不静默。
            let rebuilt = compose_trs(&t, &q, &s);
            let diff = local
                .iter()
                .zip(rebuilt.iter())
                .map(|(a, b)| (a - b).abs())
                .fold(0.0f32, f32::max);
            if diff > 1e-4 {
                stats.trs_mismatch_nodes += 1;
            }
            trs_nodes.push(json!({
                "name": b.name,
                "translation": t,
                "rotation": q,
                "scale": s,
            }));
            joints.push(1 + i);
        }
        // node 层级：按 SkeletonHierarchy 的 children 建父子——查看器靠 node 树
        // 复合出骨世界矩阵，光有平铺的 joints 列表摆不出姿势。
        for (i, b) in bones.iter().enumerate() {
            if !b.children.is_empty() {
                let kids: Vec<usize> = b.children.iter().map(|&c| 1 + c).collect();
                trs_nodes[i]["children"] = json!(kids);
            }
        }
        root_bone = bones
            .iter()
            .position(|b| b.parent.is_none())
            .ok_or_else(|| "骨架没有根骨（parse_hierarchy 保证单根，这里不该发生）".to_string())?;
        root_joint_node = 1 + root_bone;

        // inverseBindMatrices：每个 joint 的 bind 世界矩阵求逆。按模块注释的
        // 推导，引擎行主序数组按原顺序写就是 glTF 列主序的转置阵。
        // 求不出逆说明数据不自洽：Err 掉，不拿单位阵糊弄。
        let mut ibms: Vec<[f32; 16]> = Vec::with_capacity(worlds.len());
        for (i, m) in worlds.iter().enumerate() {
            let inv = mat_inverse_affine(m).ok_or_else(|| {
                format!("第 {i} 根骨的绑定矩阵不可逆（det≈0），蒙皮矩阵立不住")
            })?;
            ibms.push(inv);
        }
        let ibm_view = push_data(&mut bin, &mut views, 64, |o| {
            for m in &ibms {
                for v in m {
                    o.extend_from_slice(&v.to_le_bytes());
                }
            }
        });
        let ibm_acc = accs.len();
        accs.push(json!({
            "bufferView": ibm_view, "componentType": 5126, "count": n, "type": "MAT4",
        }));

        // 逐顶点权重打包：按骨表 → 按顶点。整形规则**直接取 preview::pose 那份**
        // （[`pose::unify_weights`]）：导出与播放各写一套的话，查看器里的姿势和
        // 界面里的姿势迟早对不上（2026-10-05 对账闸门撞的就是这个）。
        // 0 权重项剔除——它们白占 4 个槽位之一，官方校验器还会报
        // `ACCESSOR_JOINTS_USED_ZERO_WEIGHT`。
        let mut per_vertex: Vec<Vec<(usize, f32)>> = vec![Vec::new(); vc];
        for nd in r.influences {
            let Some(skin) = &nd.skin else { continue };
            let Some(&bi) = index.get(nd.name.as_str()) else {
                continue; // 骨名不在骨架里：整表跳过（已计数）
            };
            for (&v, &w) in skin.vertices.iter().zip(skin.weights.iter()) {
                let vi = v as usize;
                if vi >= vc || !w.is_finite() || w == 0.0 {
                    continue; // 上游已保证前两条，第三条是剔零权重
                }
                per_vertex[vi].push((bi, w));
            }
        }
        let mut joint_data = Vec::with_capacity(vc * 8);
        let mut weight_data = Vec::with_capacity(vc * 16);
        for infl in per_vertex.iter_mut() {
            if infl.len() > pose::MAX_INFLUENCES {
                stats.over_influenced_vertices += 1;
                infl.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
                infl.truncate(pose::MAX_INFLUENCES);
            }
            let (packed, case) = pose::unify_weights(infl, root_bone);
            match case {
                pose::WeightCase::Uncovered => stats.uncovered_vertices += 1,
                pose::WeightCase::Normalized => stats.normalized_vertices += 1,
                pose::WeightCase::RootFilled => stats.root_fill_vertices += 1,
                pose::WeightCase::Rescaled => stats.weight_sum_off_vertices += 1,
            }
            let mut ji = [0u16; pose::MAX_INFLUENCES];
            let mut wj = [0f32; pose::MAX_INFLUENCES];
            for (k, (j, w)) in packed.iter().enumerate() {
                ji[k] = *j as u16;
                wj[k] = *w;
            }
            for j in ji {
                joint_data.extend_from_slice(&j.to_le_bytes());
            }
            for w in wj {
                weight_data.extend_from_slice(&w.to_le_bytes());
            }
        }
        stats.covered_vertices = vc - stats.uncovered_vertices;
        let joints_view = push_attr(&mut bin, &mut views, 8, |o| {
            o.extend_from_slice(&joint_data);
        });
        let joints_acc = accs.len();
        accs.push(json!({
            "bufferView": joints_view, "componentType": 5123, "count": vc, "type": "VEC4",
        }));
        let weights_view = push_attr(&mut bin, &mut views, 16, |o| {
            o.extend_from_slice(&weight_data);
        });
        let weights_acc = accs.len();
        accs.push(json!({
            "bufferView": weights_view, "componentType": 5126, "count": vc, "type": "VEC4",
        }));

        for prim in primitives.iter_mut() {
            prim["attributes"]["JOINTS_0"] = json!(joints_acc);
            prim["attributes"]["WEIGHTS_0"] = json!(weights_acc);
        }

        skin_json = Some(json!({
            "inverseBindMatrices": ibm_acc,
            "joints": joints,
            "skeleton": root_joint_node,
        }));
        joint_nodes = trs_nodes;
    }

    // ------------------------------------------------------------------ 动画
    // 2026-10-07 播放锚裁决（`.scratch/ani_axis/锚点判定_20261007.md`）之后，
    // 导出的动画**重定基（rebase）到 bind rest**，不再原样抄 `.ani` 局部轨道：
    // 原样转抄会让查看器蒙皮（B⁻¹·W_t）与 app 内播放蒙皮（A⁻¹·W_t，逐动作
    // frame0 锚）锚不同源，播起来撕成尖刺。重定基后的世界 W'_j(t) = B_j·A_j⁻¹·W_j(t)
    // 使 B⁻¹·W' = A⁻¹·W 逐项相等，且 t=0 时 W' = B 正好是 node rest（不撕）。
    // 导出局部轨道 = W' 沿父链差分后分解 TRS；全部关节统一写轨道（无轨道的骨
    // 随父骨动，漏写就在查看器里钉死在 rest）。scale 分解出来恒 1（W' 是刚体
    // 复合），照样写 sampler。`.ani` 里对不上骨名的轨道计数报告，不按位置硬配。
    let mut animations: Vec<Value> = Vec::new();
    let anim_bind = rig.map(|r| pose::bind_worlds(r.hierarchy));
    for (anim_name, a) in anims {
        let (Some(r), Some(bind)) = (rig, anim_bind.as_ref()) else {
            break;
        };
        let index = r.bone_index();
        let bones = &r.hierarchy.bones;
        let n = bones.len();
        let mut astats = AnimStats {
            name: anim_name.to_string(),
            frames: a.frames,
            tracks: a.tracks.len(),
            ..Default::default()
        };
        // `.ani` 轨道与骨架的名对账照旧报数（pose_frame 复合时吃的就是对上的那些）。
        for t in &a.tracks {
            if !t.bone.is_empty() && index.contains_key(t.bone.as_str()) {
                astats.matched_tracks += 1;
            } else {
                astats
                    .unmatched_tracks
                    .push(if t.bone.is_empty() { "(unnamed)".to_string() } else { t.bone.clone() });
            }
        }

        // 关键帧时间：帧号 / tick（0xC6 那个 f32 按「每秒 tick 数」解读——
        // 样本恒 40.0，含义未证；这是已标注的解读，不是实测结论）。
        let tick = if a.tick.is_finite() && a.tick > 0.0 { a.tick } else { 1.0 };
        let times: Vec<f32> = (0..a.frames).map(|i| i as f32 / tick).collect();
        let time_view = push_data(&mut bin, &mut views, 4, |o| {
            for t in &times {
                o.extend_from_slice(&t.to_le_bytes());
            }
        });
        let time_acc = accs.len();
        // 规范：animation sampler 的 input accessor **必须**给 min/max，而且
        // min/max 一律是**数组**（写成标量会被官方校验器判 TYPE_MISMATCH，
        // 顺带把这条 accessor 报成「没有边界」——实测每个引用它的 sampler 报一个）。
        accs.push(json!({
            "bufferView": time_view, "componentType": 5126, "count": a.frames,
            "type": "SCALAR",
            "min": [times.first().copied().unwrap_or(0.0)],
            "max": [times.last().copied().unwrap_or(0.0)],
        }));

        // ---- 重定基：W' = B·A⁻¹·W 沿父链差分出逐骨局部轨道
        let locals = rebased_local_tracks(r.hierarchy, a, bind)?;
        let mut quats: Vec<Vec<[f32; 4]>> = Vec::with_capacity(n);
        let mut trans: Vec<Vec<[f32; 3]>> = Vec::with_capacity(n);
        let mut scales: Vec<Vec<[f32; 3]>> = Vec::with_capacity(n);
        for lmats in &locals {
            let mut qs = Vec::with_capacity(lmats.len());
            let mut ts = Vec::with_capacity(lmats.len());
            let mut ss = Vec::with_capacity(lmats.len());
            for m in lmats {
                let (t, q, s) = decompose_trs(m);
                // 分解往返验证（闸门要求 ≤1e-5，不许拍脑袋假定 W' 可无损分解）：
                // 回乘对不上原矩阵就计数（出现切变之类的成分），导出继续但
                // extras 里如实报数——那份动画在那个骨那帧会变形失真。
                let rebuilt = compose_trs(&t, &q, &s);
                let diff = m
                    .iter()
                    .zip(rebuilt.iter())
                    .map(|(x, y)| (x - y).abs())
                    .fold(0.0f32, f32::max);
                if diff > 1e-5 {
                    astats.trs_mismatch_frames += 1;
                }
                qs.push(q);
                ts.push(t);
                ss.push(s);
            }
            quats.push(qs);
            trans.push(ts);
            scales.push(ss);
        }
        astats.exported_tracks = n;

        // ---- 逐骨写通道：rotation/translation/scale 三个 sampler + channel
        let mut samplers: Vec<Value> = Vec::new();
        let mut channels: Vec<Value> = Vec::new();
        for (j, _b) in bones.iter().enumerate() {
            let target_node = 1 + j;
            let frames = a.frames;

            // rotation：分解出的四元数按帧定半球（q 与 −q 同一旋转；glTF 的
            // LINEAR 是归一化线性插值，相邻帧反号会在中点算出零四元数）。
            let rots = same_hemisphere(&quats[j], frames);
            let rot_view = push_data(&mut bin, &mut views, 16, |o| {
                for q in &rots {
                    for k in 0..4 {
                        o.extend_from_slice(&q[k].to_le_bytes());
                    }
                }
            });
            let rot_acc = accs.len();
            accs.push(json!({
                "bufferView": rot_view, "componentType": 5126, "count": frames, "type": "VEC4",
            }));
            // translation：重定基后的局部平移。
            let tr_view = push_data(&mut bin, &mut views, 12, |o| {
                for t in &trans[j] {
                    for k in 0..3 {
                        o.extend_from_slice(&t[k].to_le_bytes());
                    }
                }
            });
            let tr_acc = accs.len();
            accs.push(json!({
                "bufferView": tr_view, "componentType": 5126, "count": frames, "type": "VEC3",
            }));
            // scale：刚体复合分解出来恒 1，照样写 sampler（通道输出按 glTF 规定是 VEC3）。
            let sc_view = push_data(&mut bin, &mut views, 12, |o| {
                for s in &scales[j] {
                    for k in 0..3 {
                        o.extend_from_slice(&s[k].to_le_bytes());
                    }
                }
            });
            let sc_acc = accs.len();
            accs.push(json!({
                "bufferView": sc_view, "componentType": 5126, "count": frames, "type": "VEC3",
            }));

            let (rot_s, tr_s, sc_s) = (samplers.len(), samplers.len() + 1, samplers.len() + 2);
            samplers.push(json!({"input": time_acc, "interpolation": "LINEAR", "output": rot_acc}));
            samplers.push(json!({"input": time_acc, "interpolation": "LINEAR", "output": tr_acc}));
            samplers.push(json!({"input": time_acc, "interpolation": "LINEAR", "output": sc_acc}));
            channels.push(json!({"sampler": rot_s, "target": {"node": target_node, "path": "rotation"}}));
            channels.push(json!({"sampler": tr_s, "target": {"node": target_node, "path": "translation"}}));
            channels.push(json!({"sampler": sc_s, "target": {"node": target_node, "path": "scale"}}));
        }
        stats.animations.push(astats);
        animations.push(json!({
            "name": anim_name,
            "channels": channels,
            "samplers": samplers,
        }));
    }

    // ------------------------------------------------------------------ 组装
    let mut mesh_node = json!({"name": name, "mesh": 0});
    if skin_json.is_some() {
        mesh_node["skin"] = json!(0);
    }
    let mut nodes = vec![mesh_node];
    nodes.extend(joint_nodes);

    let mut doc = json!({
        "asset": {"version": "2.0", "generator": "tlbb-core mesh→glb（私有 .mesh 几何转换）"},
        "scene": 0,
        "scenes": [{"nodes": if skin_json.is_some() { vec![json!(0), json!(root_joint_node)] } else { vec![json!(0)] }}],
        "nodes": nodes,
        "meshes": [{
            "name": name,
            "primitives": primitives,
        }],
        "materials": materials,
        "accessors": accs,
        "bufferViews": views,
        "buffers": [{"byteLength": bin.len()}],
    });
    if let Some(sk) = skin_json {
        doc["skins"] = json!([sk]);
        doc["asset"]["generator"] = json!("tlbb-core mesh→glb（私有 .mesh 几何转换 + 骨架/蒙皮/动画）");
    }
    if !animations.is_empty() {
        doc["animations"] = json!(animations);
    }
    if rig.is_some() {
        doc["asset"]["extras"] = rig_stats_json(name, &stats);
    }

    let mut json_bytes = serde_json::to_vec(&doc).map_err(|e| format!("glb JSON 序列化失败：{e}"))?;
    while json_bytes.len() % 4 != 0 {
        json_bytes.push(0x20);
    }
    while bin.len() % 4 != 0 {
        bin.push(0);
    }

    let total = 12 + 8 + json_bytes.len() + 8 + bin.len();
    let mut out = Vec::with_capacity(total);
    out.extend_from_slice(&GLB_MAGIC.to_le_bytes());
    out.extend_from_slice(&2u32.to_le_bytes());
    out.extend_from_slice(&(total as u32).to_le_bytes());
    out.extend_from_slice(&(json_bytes.len() as u32).to_le_bytes());
    out.extend_from_slice(&CHUNK_JSON.to_le_bytes());
    out.extend_from_slice(&json_bytes);
    out.extend_from_slice(&(bin.len() as u32).to_le_bytes());
    out.extend_from_slice(&CHUNK_BIN.to_le_bytes());
    out.extend_from_slice(&bin);
    report_stats(name, &stats);
    Ok(out)
}

/// 把一条动作**重定基（rebase）到 bind rest**：返回逐骨逐帧的导出局部矩阵
/// （`out[骨下标][帧]`，行主序、引擎行向量约定）。
///
/// # 数学（2026-10-07 播放锚裁决，证据档案 `.scratch/ani_axis/锚点判定_20261007.md`）
///
/// 行向量约定 `world = local · parent_world` 下：
///
/// * 引擎（app 内）播放要的蒙皮：`M_j(t) = A_j⁻¹ · W_j(t)`，A = 该动画 frame0
///   的世界矩阵（逐动作锚），W = 第 t 帧世界矩阵；
/// * 当前导出的查看器蒙皮：`B_j⁻¹ · W_j`（IBM = B⁻¹），B = bind 世界矩阵——
///   与上式锚不同源（frame0≠bind），直接抄 `.ani` 轨道播起来就撕；
/// * 令导出动画产生的节点世界 `W'_j(t) = B_j · M_j(t) = B_j · A_j⁻¹ · W_j(t)`，
///   则查看器蒙皮 `B⁻¹·W' = A⁻¹·W` **逐项相等**；t=0 时 W' = B（正好是 node
///   rest，第 0 帧不撕）；
/// * 导出局部轨道由世界位姿逐骨差分：`L'_j(t) = W'_j(t) · W'_parent(t)⁻¹`
///   （根骨 parent = 场景根恒等阵，L' = W' 自身）。
///
/// # 实现纪律：复合数学只许有一份
///
/// W 与 A 直接调 [`pose::pose_frame`]（无轨道骨的回退口径也在它里面，rebase 对
/// 全部骨统一跟随），M 用现成的 [`pose::skin_palette`]——它的第一参数本来就是
/// 通用的「锚」，传 frame0 世界就是 `pose::reanchored_palette` 的口径。**导出侧
/// 不手写第二套复合**；这里自己做的只有「B·M」与父链差分两步标准乘法
/// （[`pose::mat_mul`] / [`pose::mat_inverse_affine`]）。
///
/// 锚/位姿调不出、父位姿不可逆 → `Err`（数据不自洽，不硬导）。
fn rebased_local_tracks(
    h: &SkeletonHierarchy,
    a: &Anim,
    bind: &[[f32; 16]],
) -> Result<Vec<Vec<[f32; 16]>>, String> {
    if bind.len() != h.bones.len() {
        return Err("bind 世界矩阵数与骨数不符，重定基无从谈起".to_string());
    }
    let n = h.bones.len();
    // A = 该动画自己的 frame0 世界矩阵（逐动作锚，2026-10-07 裁决）。
    let anchor = pose::pose_frame(h, a, 0);
    let mut out: Vec<Vec<[f32; 16]>> = (0..n).map(|_| Vec::with_capacity(a.frames)).collect();
    for f in 0..a.frames {
        let world = pose::pose_frame(h, a, f);
        // M = 锚⁻¹·world：skin_palette 第一参数是通用的「锚参数」，传 frame0
        // 世界就是逐动作 frame0 锚（`reanchored_palette` 的口径，不另写）。
        let pal = pose::skin_palette(h, &anchor, &world)
            .ok_or_else(|| format!("第 {f} 帧：骨架与位姿长度不符，重锚调色板调不出来"))?;
        // W'_j = B_j · M_j：把引擎要的蒙皮搬进 bind 的历史里。
        let wp: Vec<[f32; 16]> =
            bind.iter().zip(pal.iter()).map(|(b, m)| mat_mul(b, m)).collect();
        let mut inverses = Vec::with_capacity(n);
        for (j, w) in wp.iter().enumerate() {
            let inv = mat_inverse_affine(w).ok_or_else(|| {
                format!("第 {f} 帧：骨 {}（#{j}）的重锚世界位姿不可逆，局部轨道差分立不住", h.bones[j].name)
            })?;
            inverses.push(inv);
        }
        for (j, w) in wp.iter().enumerate() {
            let local = match h.bones[j].parent {
                None => *w,
                Some(p) => mat_mul(w, &inverses[p]),
            };
            out[j].push(local);
        }
    }
    Ok(out)
}

/// 对账数字 → `asset.extras`。人先看到它，才不必猜导出里哪些是数据、哪些是口径。
fn rig_stats_json(name: &str, s: &RigStats) -> Value {
    json!({
        "mesh": name,
        "rig": {
            "joints": s.joints,
            "bonesWithoutBind": s.bones_without_bind,
            "bonesWithoutBindNote": "这些骨在 .mesh 里没有 96B 绑定记录：node 局部恒等、IBM 用沿父链补出的世界矩阵求逆，README 口径「没矩阵的骨写明缺失」",
            "influenceNodesNotInHierarchy": s.influence_nodes_not_in_hierarchy,
            "coveredVertices": s.covered_vertices,
            "uncoveredVertices": s.uncovered_vertices,
            "uncoveredVerticesNote": "没被任何影响表覆盖的顶点挂根骨权重 1（glTF 的 skin 对整份网格生效）；根骨导出世界为恒等阵时保持存储位置",
            "normalizedVertices": s.normalized_vertices,
            "rootFillVertices": s.root_fill_vertices,
            "rootFillNote": "Σw 不足 1.0 的顶点把差额挂根骨（glTF 硬要求每顶点权重和为 1.0，官方校验器会对不合的报 ACCESSOR_WEIGHTS_NON_NORMALIZED）；不给没带 96B 记录的骨编影响比例，那一份就是「不跟随变形」",
            "weightSumOffVertices": s.weight_sum_off_vertices,
            "weightSumOffNote": "只能按和归一的顶点（Σw > 1，或 4 个槽位占满装不下差额）",
            "overInfluencedVertices": s.over_influenced_vertices,
            "trsMismatchNodes": s.trs_mismatch_nodes,
            // 动画口径（2026-10-07 播放锚裁决，证据 .scratch/ani_axis/锚点判定_20261007.md）：
            // 轨道已重定基到 bind rest，查看器蒙皮 == app 内逐动作 frame0 锚蒙皮。
            "animationRebase": "动画轨道重定基（rebase）到 bind rest：W'=B·A⁻¹·W（行向量）。外部查看器按标准 glTF 蒙皮（IBM·N）播放与 app 内 pose::reanchored_palette 蒙皮逐顶点一致；第 0 帧世界 = node rest（bind），不撕。轨道不再是 .ani 存储值的原样转抄，原始轨道仍在 .ani 文件里",
            "frameTickNote": "时间轴按 帧/tick（0xC6，含义未证）解读",
            "animations": s.animations.iter().map(|a| json!({
                "name": a.name, "frames": a.frames, "tracks": a.tracks,
                "matchedTracks": a.matched_tracks, "unmatchedTracks": a.unmatched_tracks,
                "exportedTracks": a.exported_tracks,
                "trsMismatchFrames": a.trs_mismatch_frames,
            })).collect::<Vec<_>>(),
        },
    })
}

fn report_stats(name: &str, s: &RigStats) {
    if s.joints == 0 && s.animations.is_empty() {
        return;
    }
    eprintln!(
        "[glb] {name}: joints={} 无bind骨={} 覆盖顶点={} 归一={} 差额挂根骨={} 按和强归={} 未覆盖={} 超4影响={} trs不符={}",
        s.joints,
        s.bones_without_bind.len(),
        s.covered_vertices,
        s.normalized_vertices,
        s.root_fill_vertices,
        s.weight_sum_off_vertices,
        s.uncovered_vertices,
        s.over_influenced_vertices,
        s.trs_mismatch_nodes,
    );
    for a in &s.animations {
        eprintln!(
            "[glb]   动画 {}: {} 帧 · .ani 轨道 {} 条 · 对上 {} · 对不上 {} 个 {:?} · 重定基后写出 {} 关节 × 3 通道 · TRS 往返超差 {}",
            a.name,
            a.frames,
            a.tracks,
            a.matched_tracks,
            a.unmatched_tracks.len(),
            a.unmatched_tracks,
            a.exported_tracks,
            a.trs_mismatch_frames,
        );
    }
}

// ---------------------------------------------------------------- 矩阵小工具
// 4×4 的单位阵/乘法/仿射求逆**直接用 preview::pose 那一份**（连同 bind 世界
// 矩阵的填充口径）——同一个口径抄两份迟早分叉，2026-10-06 就分叉过一次。
// 下面只留导出侧特有的三件：TRS 分解、TRS 回乘、旋转矩阵→四元数。




/// 引擎局部矩阵 → glTF TRS。返回 (translation, rotation(x,y,z,w), scale)。
///
/// 推导（沿用模块注释的转置抵消）：glTF 的 `M = T·R·S` 作用在列向量上是
/// 先缩放再旋转再平移；引擎行向量下是 `v ↦ (v ∘ s)·R_rows + t`。两边对齐
/// 要求 R_col = R_rowsᵀ、s_j = R_rows 第 j 行的长度。所以：
/// * 平移 = 引擎第 4 行 (m12,m13,m14)；
/// * 缩放 = 前三行的行长度（逐轴，bind 允许 ≤5% 的不等比）；
/// * 旋转 = 归一化后的行向量矩阵取转置，即「转置矩阵的列 = 原矩阵的归一化行」，
///   再按列向量标准公式提出四元数 (x,y,z,w)。
fn decompose_trs(m: &[f32; 16]) -> ([f32; 3], [f32; 4], [f32; 3]) {
    let t = [m[12], m[13], m[14]];
    let rows = [&m[0..3], &m[4..7], &m[8..11]];
    let s: [f32; 3] = [0, 1, 2].map(|k| rows[k].iter().map(|v| v * v).sum::<f32>().sqrt());
    // R_col[i][j] = rows[j][i] / s_j（转置 + 去缩放）。
    let mut r = [[0f32; 3]; 3];
    for i in 0..3 {
        for j in 0..3 {
            r[i][j] = if s[j] > 1e-9 { rows[j][i] / s[j] } else { 0.0 };
        }
    }
    let q = mat3_to_quat(&r);
    (t, q, s)
}

/// TRS → 引擎行主序局部矩阵（decompose_trs 的逆，用于回乘验证）。
fn compose_trs(t: &[f32; 3], q: &[f32; 4], s: &[f32; 3]) -> [f32; 16] {
    let [x, y, z, w] = *q;
    let (xx, yy, zz) = (x * x, y * y, z * z);
    let (xy, xz, yz) = (x * y, x * z, y * z);
    let (wx, wy, wz) = (w * x, w * y, w * z);
    // 列向量旋转矩阵 R（glTF 语义），行向量矩阵 = Rᵀ：A[j][i] = R[i][j]。
    let r = [
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
        [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
        [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
    ];
    let mut m = [0f32; 16];
    for j in 0..3 {
        for i in 0..3 {
            m[j * 4 + i] = r[i][j] * s[j];
        }
    }
    m[12] = t[0];
    m[13] = t[1];
    m[14] = t[2];
    m[15] = 1.0;
    m
}

/// 列向量旋转矩阵 → 单位四元数 (x,y,z,w)。Shepperd 分支法，数值稳。
fn mat3_to_quat(r: &[[f32; 3]; 3]) -> [f32; 4] {
    let tr = r[0][0] + r[1][1] + r[2][2];
    let (x, y, z, w);
    if tr > 0.0 {
        let sq = (tr + 1.0).sqrt() * 2.0;
        w = 0.25 * sq;
        x = (r[2][1] - r[1][2]) / sq;
        y = (r[0][2] - r[2][0]) / sq;
        z = (r[1][0] - r[0][1]) / sq;
    } else if r[0][0] > r[1][1] && r[0][0] > r[2][2] {
        let sq = (1.0 + r[0][0] - r[1][1] - r[2][2]).sqrt() * 2.0;
        w = (r[2][1] - r[1][2]) / sq;
        x = 0.25 * sq;
        y = (r[0][1] + r[1][0]) / sq;
        z = (r[0][2] + r[2][0]) / sq;
    } else if r[1][1] > r[2][2] {
        let sq = (1.0 + r[1][1] - r[0][0] - r[2][2]).sqrt() * 2.0;
        w = (r[0][2] - r[2][0]) / sq;
        x = (r[0][1] + r[1][0]) / sq;
        y = 0.25 * sq;
        z = (r[1][2] + r[2][1]) / sq;
    } else {
        let sq = (1.0 + r[2][2] - r[0][0] - r[1][1]).sqrt() * 2.0;
        w = (r[1][0] - r[0][1]) / sq;
        x = (r[0][2] + r[2][0]) / sq;
        y = (r[1][2] + r[2][1]) / sq;
        z = 0.25 * sq;
    }
    let n = (x * x + y * y + z * z + w * w).sqrt();
    if n > 1e-9 {
        [x / n, y / n, z / n, w / n]
    } else {
        [0.0, 0.0, 0.0, 1.0]
    }
}

/// 把一段数据追加进 BIN chunk。
///
/// `align` = 规范 3.6.2 对齐表里这个 accessor 元素所需的字节边界（SCALAR→4、
/// VEC2→8、VEC3→12、VEC4 的 f32→16、VEC4 的 u16→8、MAT4→64），前面补 0。
/// 官方校验器只按 4 字节查，所以补齐不足它不报，但把 buffer 直接映射成
/// float4x4 / vec4 的导入器会读歪——一次到位。
///
/// `target`：只有**顶点属性**（ARRAY_BUFFER 34962）与**索引**（ELEMENT_ARRAY_BUFFER
/// 34963）能打；IBM 与动画数据的 view 打了会被判 `BUFFER_VIEW_TARGET_OVERRIDE`
/// （实测一份文件 6,076 个 error）——同一份 buffer 不能既是 VertexBuffer 又是别的。
fn push(
    bin: &mut Vec<u8>,
    views: &mut Vec<Value>,
    align: usize,
    target: Option<u32>,
    write: impl FnOnce(&mut Vec<u8>),
) -> usize {
    while bin.len() % align != 0 {
        bin.push(0);
    }
    let off = bin.len();
    write(bin);
    let mut view = json!({"buffer": 0, "byteOffset": off, "byteLength": bin.len() - off});
    if let Some(t) = target {
        view["target"] = json!(t);
    }
    views.push(view);
    views.len() - 1
}

/// 顶点属性用的 view（target = ARRAY_BUFFER）。
fn push_attr(
    bin: &mut Vec<u8>,
    views: &mut Vec<Value>,
    align: usize,
    write: impl FnOnce(&mut Vec<u8>),
) -> usize {
    push(bin, views, align, Some(34962), write)
}

/// 非顶点数据（IBM、动画的时间与输出）：不挂 target。
fn push_data(
    bin: &mut Vec<u8>,
    views: &mut Vec<Value>,
    align: usize,
    write: impl FnOnce(&mut Vec<u8>),
) -> usize {
    push(bin, views, align, None, write)
}

/// 逐帧给四元数轨道定半球：与前一帧点积为负就整条取反。
///
/// q 与 −q 表示同一个旋转（`pose::quat_to_mat` 对两者给出同一张矩阵），所以这
/// 不是改数据，只是选写法。必须做的理由：glTF 里 rotation 通道的 `LINEAR` 是
/// **归一化线性插值**，相邻两帧反号时中点会算出零四元数 → NaN/翻面。主样本
/// 实测 675 条轨道、24,300 对相邻帧里有 **86 对反号**（最小点积 −1.0000001），
/// 本仓 three.js 走 slerpFlat 自带符号纠正才侥幸免疫，不能当通用结论。
fn same_hemisphere(src: &[[f32; 4]], frames: usize) -> Vec<[f32; 4]> {
    let mut out = Vec::with_capacity(frames);
    let mut prev: Option<[f32; 4]> = None;
    for q in src.iter().take(frames) {
        let mut q = *q;
        if let Some(p) = prev {
            let dot: f32 = q.iter().zip(p.iter()).map(|(a, b)| a * b).sum();
            if dot < 0.0 {
                for v in q.iter_mut() {
                    *v = -*v;
                }
            }
        }
        out.push(q);
        prev = Some(q);
    }
    out
}

fn index_range(idx: &[u16]) -> (u32, u32) {
    let mut lo = u32::MAX;
    let mut hi = 0u32;
    for &i in idx {
        lo = lo.min(i as u32);
        hi = hi.max(i as u32);
    }
    if lo == u32::MAX {
        lo = 0;
    }
    (lo, hi)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::preview::geometry::parse_mesh;
    use crate::preview::pose::mat_identity;

    fn synth() -> Vec<u8> {
        let vc = 4usize;
        let mut v = vec![0u8; 0x118 + 4 * 12 + 4 * 12 + 4 * 8 + 2 * 4 + 6 * 2];
        v[0x8C..0x90].copy_from_slice(&(vc as u32).to_le_bytes());
        v[0x90..0x94].copy_from_slice(&2u32.to_le_bytes());
        v[0x94..0x98].copy_from_slice(&2u32.to_le_bytes()); // 两个子网格，各 1 面
        for (i, p) in [[-1.0f32, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 1.0]]
            .iter()
            .enumerate()
        {
            let off = 0x118 + i * 12;
            for k in 0..3 {
                v[off + k * 4..off + k * 4 + 4].copy_from_slice(&p[k].to_le_bytes());
            }
            let noff = 0x118 + 48 + i * 12;
            v[noff + 4..noff + 8].copy_from_slice(&1.0f32.to_le_bytes());
            let uoff = 0x118 + 96 + i * 8;
            v[uoff..uoff + 4].copy_from_slice(&(i as f32 * 0.3).to_le_bytes());
        }
        let at = 0x118 + 128;
        v[at..at + 4].copy_from_slice(&1u32.to_le_bytes());
        v[at + 4..at + 8].copy_from_slice(&1u32.to_le_bytes());
        let idx = [0u16, 1, 2, 1, 2, 3];
        for (i, x) in idx.iter().enumerate() {
            v[at + 8 + i * 2..at + 10 + i * 2].copy_from_slice(&x.to_le_bytes());
        }
        v
    }

    #[test]
    fn glb_container_and_document_shape() {
        let l = parse_mesh(&synth()).expect("解析");
        assert_eq!(l.face_counts, vec![1, 1]);
        let bytes = to_glb("测试网格", &l, &[]).expect("导出");
        assert_eq!(&bytes[0..4], b"glTF");
        assert_eq!(u32::from_le_bytes(bytes[4..8].try_into().unwrap()), 2);
        assert_eq!(
            u32::from_le_bytes(bytes[8..12].try_into().unwrap()) as usize,
            bytes.len(),
            "GLB 头里的总长必须等于实际字节数"
        );
        let jlen = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
        assert_eq!(u32::from_le_bytes(bytes[16..20].try_into().unwrap()), CHUNK_JSON);
        assert_eq!((jlen) % 4, 0);
        let doc: Value =
            serde_json::from_slice(&bytes[20..20 + jlen]).expect("JSON chunk 必须是合法 JSON");
        let bin_len = u32::from_le_bytes(bytes[20 + jlen..24 + jlen].try_into().unwrap()) as usize;
        assert_eq!(
            u32::from_le_bytes(bytes[24 + jlen..28 + jlen].try_into().unwrap()),
            CHUNK_BIN
        );
        assert_eq!(bytes.len(), 28 + jlen + bin_len);
        assert_eq!(doc["buffers"][0]["byteLength"].as_u64().unwrap() as usize, bin_len);
        assert_eq!(doc["meshes"][0]["primitives"].as_array().unwrap().len(), 2);
        assert_eq!(doc["meshes"][0]["primitives"][0]["mode"], json!(4));
        assert_eq!(doc["accessors"][0]["min"].as_array().unwrap().len(), 3);
        assert_eq!(doc["materials"].as_array().unwrap().len(), 2);
        assert_eq!(doc["materials"][0]["name"], json!("材质槽 1"));
        assert_eq!(doc["materials"][0]["doubleSided"], json!(true));
        // 第二个 primitive 的索引 accessor 从第 3 个 u16 之后开始
        assert_eq!(doc["accessors"][4]["byteOffset"], json!(6));
        assert!(doc["meshes"][0]["primitives"][0]["attributes"]["NORMAL"].is_number());
        assert!(doc["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"].is_number());
        // 没有权重就不许出现 skin / animation
        assert!(doc.get("skins").is_none());
        assert!(doc.get("animations").is_none());
    }

    #[test]
    fn slot_names_are_carried_through() {
        let l = parse_mesh(&synth()).expect("解析");
        let slots = vec![
            SlotStyle {
                name: Some("yifu_001".into()),
                ..Default::default()
            },
            SlotStyle {
                name: Some("shoutao".into()),
                ..Default::default()
            },
        ];
        let bytes = to_glb("m", &l, &slots).expect("导出");
        let jlen = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
        let doc: Value = serde_json::from_slice(&bytes[20..20 + jlen]).unwrap();
        assert_eq!(doc["materials"][0]["name"], json!("yifu_001"));
        assert_eq!(doc["materials"][1]["name"], json!("shoutao"));
    }

    #[test]
    fn empty_mesh_is_refused_not_exported() {
        let mut v = synth();
        v[0x8C..0x90].copy_from_slice(&0u32.to_le_bytes());
        let l = parse_mesh(&v);
        assert!(l.is_err(), "顶点 0 的头部不该被当成可画网格");
    }

    /// 无 rig 的 to_glb_rigged 与 to_glb 产物逐字节一致（同一入口的两条路）。
    #[test]
    fn rigged_entry_without_rig_equals_static() {
        let l = parse_mesh(&synth()).expect("解析");
        let a = to_glb("m", &l, &[]).expect("静态导出");
        let b = to_glb_rigged("m", &l, &[], None, &[]).expect("rigged 空跑");
        assert_eq!(a, b);
    }

    /// 有动画没骨架：拒绝，不硬导。
    #[test]
    fn animations_without_rig_are_refused() {
        let l = parse_mesh(&synth()).expect("解析");
        let a = Anim {
            envelope: crate::preview::Envelope {
                banner: "t".into(),
                tag: "ani".into(),
                version: 2,
                note: String::new(),
            },
            bones: 1,
            frames: 2,
            tick: 40.0,
            tracks: vec![crate::preview::Track {
                bone: "b".into(),
                rotations: vec![[0.0, 0.0, 0.0, 1.0]; 2],
                positions: vec![[0.0; 3]; 2],
                scales: vec![1.0; 2],
            }],
        };
        assert!(to_glb_rigged("m", &l, &[], None, &[("idle", &a)]).is_err());
    }

    /// 合成小骨架（2 根骨 + 影响表）走一遍 rigged 出口：
    /// node 树、IBM 恒等性、权重打包、动画通道数量全部自洽。
    #[test]
    fn synthetic_rig_roundtrips() {
        // 两个骨：root(平移 1,0,0) → child(旋转 90° 绕 z + 平移)。
        let mut root = mat_identity();
        root[12] = 1.0;
        // child 局部 = 平移 (0,2,0)（世界 = (1,2,0)）
        let mut child = mat_identity();
        child[13] = 2.0;
        let hierarchy = SkeletonHierarchy {
            bones: vec![
                crate::preview::BoneNode {
                    name: "root".into(),
                    parent: None,
                    bind: Some(root),
                    children: vec![1],
                },
                crate::preview::BoneNode {
                    name: "child".into(),
                    parent: Some(0),
                    bind: Some(child),
                    children: vec![],
                },
            ],
            sockets: vec![],
        };
        let nodes = vec![
            Node {
                name: "root".into(),
                bind: root,
                skin: Some(crate::preview::SkinInfluence {
                    vertices: vec![0, 1],
                    weights: vec![0.25, 1.0],
                }),
            },
            Node {
                name: "child".into(),
                bind: child,
                skin: Some(crate::preview::SkinInfluence {
                    vertices: vec![0, 1, 2],
                    weights: vec![0.75, 0.0, 0.5],
                }),
            },
        ];
        let rig = RigExport { hierarchy: &hierarchy, influences: &nodes };
        let l = parse_mesh(&synth()).expect("解析");
        let anim = Anim {
            envelope: crate::preview::Envelope {
                banner: "t".into(),
                tag: "ani".into(),
                version: 2,
                note: String::new(),
            },
            bones: 2,
            frames: 3,
            tick: 40.0,
            tracks: vec![
                crate::preview::Track {
                    bone: "root".into(),
                    rotations: vec![[0.0, 0.0, 0.0, 1.0]; 3],
                    positions: vec![[0.0; 3]; 3],
                    scales: vec![1.0; 3],
                },
                crate::preview::Track {
                    bone: "ghost".into(), // 对不上骨架：计数不写
                    rotations: vec![[0.0; 4]; 3],
                    positions: vec![[0.0; 3]; 3],
                    scales: vec![1.0; 3],
                },
            ],
        };
        let bytes = to_glb_rigged("m", &l, &[], Some(&rig), &[("idle", &anim)]).expect("导出");
        let jlen = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
        let doc: Value = serde_json::from_slice(&bytes[20..20 + jlen]).unwrap();
        // node 树：网格节点 + 2 根骨；scene 根 = [0, 1]
        assert_eq!(doc["nodes"].as_array().unwrap().len(), 3);
        assert_eq!(doc["scenes"][0]["nodes"], json!([0, 1]));
        assert_eq!(doc["nodes"][0]["skin"], json!(0));
        // skin：joints 与骨序一致，IBM 2 条
        let skin = &doc["skins"][0];
        assert_eq!(skin["joints"], json!([1, 2]));
        assert_eq!(skin["skeleton"], json!(1));
        let ibm_acc = skin["inverseBindMatrices"].as_u64().unwrap() as usize;
        assert_eq!(doc["accessors"][ibm_acc]["count"], json!(2));
        assert_eq!(doc["accessors"][ibm_acc]["type"], json!("MAT4"));
        // 存储的是**世界绑定的逆**（2026-10-06 口径），所以合成骨架存的
        // S_root=(1,0,0)、S_child=(0,2,0) 对应 B_root=(−1,0,0)、B_child=(0,−2,0)。
        // 根骨局部 = 自身世界 = (−1,0,0)。
        assert_eq!(doc["nodes"][1]["translation"], json!([-1.0, 0.0, 0.0]));
        // child 局部 = B_child · B_root⁻¹ = (0,−2,0) − (−1,0,0) = (1,−2,0)、无旋转
        assert_eq!(doc["nodes"][2]["translation"], json!([1.0, -2.0, 0.0]));
        assert_eq!(doc["nodes"][2]["rotation"], json!([0.0, 0.0, 0.0, 1.0]));
        // 动画（重定基后）：**全部关节**（root + child = 2 根）各写 3 通道 = 6，
        // 不止 `.ani` 对上名的那条（root）；ghost 对不上骨名，照旧进 extras 记账。
        // 本例两条轨道都是恒等局姿，重定基出的局部 == node rest 局部（frame0 恒等）。
        let anims = doc["animations"].as_array().unwrap();
        assert_eq!(anims.len(), 1);
        assert_eq!(anims[0]["channels"].as_array().unwrap().len(), 6);
        let extras = &doc["asset"]["extras"]["rig"];
        assert_eq!(extras["animations"][0]["unmatchedTracks"], json!(["ghost"]));
        assert_eq!(extras["animations"][0]["exportedTracks"], json!(2));
        assert_eq!(extras["animations"][0]["trsMismatchFrames"], json!(0));
        assert_eq!(extras["bonesWithoutBind"], json!([]));
        // 权重四情形（`pose::unify_weights`）：
        // 顶点 0 = root 0.25 + child 0.75，Σ=1 → Normalized；
        // 顶点 1 = root 1.0（child 那条是 0 权重，剔除后 Σ 仍 1）→ Normalized；
        // 顶点 2 = child 0.5，Σ=0.5 不足 → 差额 0.5 挂根骨 → RootFilled；
        // 顶点 3 = 没有任何表覆盖 → Uncovered（整份权重挂根骨）。
        // 剔掉 0 权重项是官方校验器的要求（ACCESSOR_JOINTS_USED_ZERO_WEIGHT）。
        assert_eq!(extras["normalizedVertices"], json!(2));
        assert_eq!(extras["rootFillVertices"], json!(1)); // 顶点 2
        assert_eq!(extras["weightSumOffVertices"], json!(0));
        assert_eq!(extras["uncoveredVertices"], json!(1)); // 顶点 3
    }
}
