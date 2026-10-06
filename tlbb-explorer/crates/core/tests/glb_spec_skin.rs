//! 规范侧对账闸门：**不用导出器的任何数学**，只按 glTF 2.0 规范自己的约定
//! （MAT4 列主序、列向量在左、`world = parent_world · local`、
//! `skinning = G_mesh⁻¹ · G_joint · IBM`）把导出的 `.glb` 读回来，逐项和
//! 引擎侧 `preview::pose` 的输出对表。
//!
//! 与 `glb_skin_export.rs` 的分工：那条验**结构**（joints 数、IBM 可逆、
//! sampler 长度、GLB 布局），本条验**语义**。行向量→列向量的换算对不对，
//! 结构一致性根本验不出来——只有「规范侧独立实现 vs 我们的实现」能回答：
//! 换算错一次（该转置没转置、四元数取了共轭、父子乘序反了），查看器摆出来
//! 的姿势就是废的，而所有结构闸门照样全绿。
//!
//! 四条：
//! 1. **bind 姿态骨世界**：GLB node 树按规范复合出的每根骨世界矩阵
//!    == 引擎存储 bind 世界矩阵（[`bind_worlds`]）**逐元素相等**（「转置抵消」
//!    的正确含义：约定翻转与存储翻转对消，数组层面本就相等）。同一条里反向
//!    钉住：比对转置版必须差得远（>0.5）——证明这条对账真有分辨力。
//! 2. **逐帧动画骨世界**：idle01 全 41 帧扫，通道覆盖后按规范复合的世界矩阵
//!    == [`pose_frame`] 逐元素相等。
//! 3. **蒙皮顶点**：规范蒙皮公式打出的位置 == [`posed_vertices`] 打出的位置。
//!    参与比对的顶点：原始 Σw 严格为 1 且影响 ≤4 根（避开导出侧归一/引擎侧
//!    不归一那条已知口径差），外加未覆盖顶点（两侧都该原地不动）。同一条里
//!    反向钉住：把 joint↔IBM 的配对整体错开一位，误差必须显著变大。
//! 4. **原样性**：translation/scale 通道数据与 `.ani` 轨道**逐元素完全相等**；
//!    rotation 允许整条取反（glTF 的 LINEAR 是归一化线性插值，相邻帧必须同半球，
//!    而 q 与 −q 是同一个旋转），且**相邻帧点积不得为负**——除了定向，导出不许改数据。
//!
//! 真数据缺席 → 打印说明跳过，不算失败（照 `bone_hierarchy.rs` 的做法）。

use std::path::PathBuf;

use serde_json::Value;
use tlbb_core::export::gltf::{to_glb_rigged, RigExport};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::pose::{bind_worlds, posed_vertices, pose_frame, skin_palette};
use tlbb_core::preview::{
    parse_ani, parse_hierarchy, parse_mesh, parse_nodes, Anim, Node, SkeletonHierarchy,
};

/// w1351_monster_xiyuqiezei_yifu_001.mesh：46 骨主样本
const MESH: u64 = 0xbcd65050a62986b7;
/// w1351_monster_xiyuqiezei_idle01.ani（41 帧）
const ANI_IDLE01: u64 = 0x4ec2478a169d5e73;

fn bytes_of(hash: u64) -> Option<Vec<u8>> {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let p = Pak::open(root.join("data.pak")).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

// ---------------------------------------------------------------- 规范侧数学
// 这里每一行都按规范写，不调 tlbb_core 里的任何矩阵工具：本闸门的价值
// 全在「两套实现互相看不见」。

/// 规范 MAT4 是列主序：`m[c * 4 + r]` 是元素 (行 r, 列 c)。
fn e(m: &[f32; 16], r: usize, c: usize) -> f32 {
    m[c * 4 + r]
}

fn mul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
    let mut o = [0f32; 16];
    for c in 0..4 {
        for r in 0..4 {
            let mut s = 0.0f32;
            for k in 0..4 {
                s += e(a, r, k) * e(b, k, c);
            }
            o[c * 4 + r] = s;
        }
    }
    o
}

fn apply(m: &[f32; 16], p: [f32; 3]) -> [f32; 3] {
    let [x, y, z] = p;
    [
        e(m, 0, 0) * x + e(m, 0, 1) * y + e(m, 0, 2) * z + e(m, 0, 3),
        e(m, 1, 0) * x + e(m, 1, 1) * y + e(m, 1, 2) * z + e(m, 1, 3),
        e(m, 2, 0) * x + e(m, 2, 1) * y + e(m, 2, 2) * z + e(m, 2, 3),
    ]
}

fn identity() -> [f32; 16] {
    let mut m = [0f32; 16];
    m[0] = 1.0;
    m[5] = 1.0;
    m[10] = 1.0;
    m[15] = 1.0;
    m
}

/// 规范：node 局部 `M = T·R·S`（列向量，平移落在第 4 列）。
fn trs(t: &[f32; 3], q: &[f32; 4], s: &[f32; 3]) -> [f32; 16] {
    let [x, y, z, w] = *q;
    let (xx, yy, zz) = (x * x, y * y, z * z);
    let (xy, xz, yz) = (x * y, x * z, y * z);
    let (wx, wy, wz) = (w * x, w * y, w * z);
    let r = [
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)],
        [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)],
        [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)],
    ];
    let mut m = [0f32; 16];
    for c in 0..3 {
        for row in 0..3 {
            m[c * 4 + row] = r[row][c] * s[c];
        }
    }
    m[12] = t[0];
    m[13] = t[1];
    m[14] = t[2];
    m[15] = 1.0;
    m
}

/// 引擎行主序（行向量）↔ 规范列主序（列向量）：互为转置。
fn transposed(m: &[f32; 16]) -> [f32; 16] {
    let mut o = [0f32; 16];
    for r in 0..4 {
        for c in 0..4 {
            o[c * 4 + r] = m[r * 4 + c];
        }
    }
    o
}

fn max_diff(a: &[f32; 16], b: &[f32; 16]) -> f32 {
    a.iter().zip(b.iter()).map(|(x, y)| (x - y).abs()).fold(0.0f32, f32::max)
}

fn v3(v: &Value) -> [f32; 3] {
    let a = v.as_array().unwrap();
    [a[0].as_f64().unwrap() as f32, a[1].as_f64().unwrap() as f32, a[2].as_f64().unwrap() as f32]
}

fn v4(v: &Value) -> [f32; 4] {
    let a = v.as_array().unwrap();
    [
        a[0].as_f64().unwrap() as f32,
        a[1].as_f64().unwrap() as f32,
        a[2].as_f64().unwrap() as f32,
        a[3].as_f64().unwrap() as f32,
    ]
}

// ------------------------------------------------------------------ 最小 GLB

struct Ctx {
    doc: Value,
    bin: Vec<u8>,
    h: SkeletonHierarchy,
    nodes: Vec<Node>,
    a: Anim,
    positions: Vec<[f32; 3]>,
    bones: usize,
}

/// 一条动画的通道，按 target node 归组（规范：通道覆盖 node 的属性）。
struct Channel {
    path: String,
    comps: usize,
    times: Vec<f32>,
    values: Vec<f32>,
}

impl Ctx {
    fn f32s(&self, acc_idx: usize) -> Vec<f32> {
        let acc = &self.doc["accessors"][acc_idx];
        let view = &self.doc["bufferViews"][acc["bufferView"].as_u64().unwrap() as usize];
        let off = view["byteOffset"].as_u64().unwrap() as usize
            + acc.get("byteOffset").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
        let comps = match acc["type"].as_str().unwrap() {
            "SCALAR" => 1,
            "VEC2" => 2,
            "VEC3" => 3,
            "VEC4" => 4,
            "MAT4" => 16,
            t => panic!("未知类型 {t}"),
        };
        let n = acc["count"].as_u64().unwrap() as usize * comps;
        assert_eq!(acc["componentType"].as_u64().unwrap(), 5126, "本闸门只按 f32 读");
        (0..n)
            .map(|k| f32::from_le_bytes(self.bin[off + k * 4..off + k * 4 + 4].try_into().unwrap()))
            .collect()
    }

    fn u16s(&self, acc_idx: usize) -> Vec<u16> {
        let acc = &self.doc["accessors"][acc_idx];
        let view = &self.doc["bufferViews"][acc["bufferView"].as_u64().unwrap() as usize];
        let off = view["byteOffset"].as_u64().unwrap() as usize
            + acc.get("byteOffset").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
        let comps = match acc["type"].as_str().unwrap() {
            "SCALAR" => 1,
            "VEC4" => 4,
            t => panic!("未知类型 {t}"),
        };
        let n = acc["count"].as_u64().unwrap() as usize * comps;
        assert_eq!(acc["componentType"].as_u64().unwrap(), 5123, "本闸门只按 u16 读");
        (0..n)
            .map(|k| u16::from_le_bytes(self.bin[off + k * 2..off + k * 2 + 2].try_into().unwrap()))
            .collect()
    }

    fn mat(&self, acc_idx: usize, i: usize) -> [f32; 16] {
        let f = self.f32s(acc_idx);
        let mut m = [0f32; 16];
        m.copy_from_slice(&f[i * 16..(i + 1) * 16]);
        m
    }

    /// node 的静态局部变换（网格节点没有 TRS → 恒等）。
    fn base_local(&self, node: usize) -> [f32; 16] {
        let n = &self.doc["nodes"][node];
        if n["translation"].is_array() {
            trs(&v3(&n["translation"]), &v4(&n["rotation"]), &v3(&n["scale"]))
        } else {
            identity()
        }
    }

    fn channels(&self, anim: &Value) -> Vec<(usize, Channel)> {
        let samplers = anim["samplers"].as_array().unwrap();
        let mut out = Vec::new();
        for ch in anim["channels"].as_array().unwrap() {
            let node = ch["target"]["node"].as_u64().unwrap() as usize;
            let path = ch["target"]["path"].as_str().unwrap().to_string();
            let s = &samplers[ch["sampler"].as_u64().unwrap() as usize];
            let comps = if path == "rotation" { 4 } else { 3 };
            out.push((
                node,
                Channel {
                    comps,
                    times: self.f32s(s["input"].as_u64().unwrap() as usize),
                    values: self.f32s(s["output"].as_u64().unwrap() as usize),
                    path,
                },
            ));
        }
        out
    }

    /// 规范世界矩阵：从 scene 根往下 `G = G_parent · L`。`override_at` 给出
    /// 该 node 在这一帧被动画覆盖后的局部变换（`None` 用静态值）。
    fn globals_with(&self, ov: &dyn Fn(usize) -> Option<[f32; 16]>) -> Vec<[f32; 16]> {
        let nodes = self.doc["nodes"].as_array().unwrap();
        let mut out = vec![identity(); nodes.len()];
        let scene = &self.doc["scenes"][self.doc["scene"].as_u64().unwrap() as usize];
        let mut stack: Vec<(usize, [f32; 16])> = scene["nodes"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| (v.as_u64().unwrap() as usize, identity()))
            .collect();
        while let Some((i, parent)) = stack.pop() {
            let local = ov(i).unwrap_or_else(|| self.base_local(i));
            let g = mul(&parent, &local);
            out[i] = g;
            if let Some(kids) = nodes[i]["children"].as_array() {
                for k in kids {
                    stack.push((k.as_u64().unwrap() as usize, g));
                }
            }
        }
        out
    }

    /// 第 `frame` 帧：按通道覆盖 node 属性后重新复合。
    fn frame_globals(&self, chs: &[(usize, Channel)], frame: usize) -> Vec<[f32; 16]> {
        // 每根被动画命中的 node：TRS 三通道合成一张局部矩阵
        let mut locals: Vec<(usize, [f32; 16])> = Vec::new();
        let mut by_node: std::collections::HashMap<usize, ([f32; 3], [f32; 4], [f32; 3])> =
            std::collections::HashMap::new();
        for (node, c) in chs {
            let t = c.times[frame];
            let k = c.times.iter().position(|x| (x - t).abs() < 1e-7).expect("关键帧时间存在");
            assert_eq!(k, frame, "导出的关键帧时间必须正好是第 {frame} 帧");
            let slot = by_node.entry(*node).or_insert(([0f32; 3], [0f32; 4], [1f32; 3]));
            let v = &c.values[k * c.comps..(k + 1) * c.comps];
            match c.path.as_str() {
                "rotation" => slot.1 = [v[0], v[1], v[2], v[3]],
                "translation" => slot.0 = [v[0], v[1], v[2]],
                "scale" => slot.2 = [v[0], v[1], v[2]],
                p => panic!("未知通道路径 {p}"),
            }
        }
        for (node, (t, q, s)) in by_node {
            locals.push((node, trs(&t, &q, &s)));
        }
        self.globals_with(&|i| locals.iter().find(|(n, _)| *n == i).map(|(_, m)| *m))
    }

    fn idle01(&self) -> Value {
        self.doc["animations"].as_array().unwrap()[0].clone()
    }
}

fn setup() -> Option<Ctx> {
    let (Some(mesh), Some(ani)) = (bytes_of(MESH), bytes_of(ANI_IDLE01)) else {
        eprintln!("跳过：本机没有 data.pak 或这两份资源不在里面（夹具不入库）");
        return None;
    };
    let l = parse_mesh(&mesh).expect("yifu_001 应能解析");
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let nodes = parse_nodes(&mesh);
    let a = parse_ani(&ani).expect("idle01 应能解出");
    let rig = RigExport { hierarchy: &h, influences: &nodes };
    let bytes =
        to_glb_rigged("yifu_001", &l, &[], Some(&rig), &[("idle01", &a)]).expect("导出");
    // GLB 布局（这条闸门只按规范读，布局细节由 glb_skin_export.rs 钉）
    assert_eq!(&bytes[0..4], b"glTF");
    let jlen = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
    let bhead = 20 + jlen;
    let blen = u32::from_le_bytes(bytes[bhead..bhead + 4].try_into().unwrap()) as usize;
    Some(Ctx {
        doc: serde_json::from_slice(&bytes[20..20 + jlen]).expect("JSON 合法"),
        bin: bytes[bhead + 8..bhead + 8 + blen].to_vec(),
        bones: h.bones.len(),
        h,
        nodes,
        a,
        positions: l.geometry.positions.clone(),
    })
}

/// 闸门 1：bind 姿态——规范复合出来的骨世界 == 存储 bind 世界**逐元素相等**。
/// 「转置抵消」的正确含义：引擎行主序（行向量）数组按原顺序落进 glTF 的列主序
/// （列向量）槽位，约定翻转与存储翻转互相抵消，所以数组层面**就该逐元素相等**；
/// 谁多转一次立刻差出去（反向钉：比对转置版必须差得远）。
#[test]
fn glb_bind_globals_match_engine_binds_elementwise() {
    let Some(c) = setup() else { return };
    assert_eq!(c.bones, 46);
    let bind = bind_worlds(&c.h);
    let g = c.globals_with(&|_| None);
    let mut worst = (0usize, 0f32, String::new());
    let mut flipped = 0f32; // 反向钉：多转一次置落在这条上
    for (i, b) in c.h.bones.iter().enumerate() {
        let node = 1 + i;
        let d = max_diff(&g[node], &bind[i]);
        if d > worst.1 {
            worst = (node, d, b.name.clone());
        }
        flipped = flipped.max(max_diff(&g[node], &transposed(&bind[i])));
    }
    eprintln!(
        "bind 对账：{} 根骨 · 逐元素比对最大差 {:e}（骨 {}）· 转置版比对最大差 {:.4}",
        c.bones, worst.1, worst.2, flipped
    );
    assert!(worst.1 < 1e-5, "规范复合的骨世界应与存储 bind 逐元素相等，骨 {} 差 {}", worst.2, worst.1);
    assert!(flipped > 0.5, "反向验红：多转一次置必须被这条对账抓出来，实测只差 {flipped}");
    // 网格节点自身必须是恒等（蒙皮公式里的 G_mesh⁻¹ 因子）
    assert!(max_diff(&g[0], &identity()) < 1e-7, "挂 skin 的网格节点世界应为恒等");
}

/// 闸门 2：逐帧动画——规范复合的骨世界 == pose_frame（逐元素相等，全 41 帧）。
#[test]
fn glb_animated_globals_match_pose_frame_every_frame() {
    let Some(c) = setup() else { return };
    assert_eq!(c.a.frames, 41);
    let chs = c.channels(&c.idle01());
    let bind = bind_worlds(&c.h);
    let mut worst = (0usize, 0usize, 0f32, String::new());
    for f in 0..c.a.frames {
        let g = c.frame_globals(&chs, f);
        let w = pose_frame(&c.h, &c.a, f);
        for (i, b) in c.h.bones.iter().enumerate() {
            // pose_frame 的口径：无轨道的骨把**世界** bind 当局部用（近似，函数
            // 注释已如实标注）；规范侧那条路是「静态 node 值」。两条路只在
            // 「无轨道且有 bind」的骨上分叉——本样本 46 条轨道里 45 条有名，
            // 唯一没轨道的是框架根 000，它也没有 bind，两侧都是恒等。
            let has_track = c
                .a
                .tracks
                .iter()
                .any(|t| !t.bone.is_empty() && t.bone == b.name && !t.rotations.is_empty());
            if !has_track && b.bind.is_some() {
                continue;
            }
            let d = max_diff(&g[1 + i], &w[i]);
            if d > worst.2 {
                worst = (f, 1 + i, d, b.name.clone());
            }
            let _ = &bind;
        }
    }
    eprintln!(
        "动画对账：41 帧 × {} 骨 · 规范复合 vs pose_frame 最大差 {:e}（第 {} 帧 骨 {}）",
        c.bones, worst.2, worst.0, worst.3
    );
    assert!(worst.2 < 1e-5, "逐帧骨世界应与 pose_frame 一致（转置口径），差 {}", worst.2);
}

/// 闸门 3：蒙皮顶点——规范蒙皮公式打出的位置 == pose::posed_vertices。
#[test]
fn glb_skinned_vertices_match_engine_skinning() {
    let Some(c) = setup() else { return };
    let vc = c.positions.len();
    assert_eq!(vc, 781);
    let skin = &c.doc["skins"][0];
    let joints: Vec<usize> =
        skin["joints"].as_array().unwrap().iter().map(|j| j.as_u64().unwrap() as usize).collect();
    assert_eq!(joints.len(), c.bones);
    let ibm_acc = skin["inverseBindMatrices"].as_u64().unwrap() as usize;
    let prim = &c.doc["meshes"][0]["primitives"][0];
    let ja = prim["attributes"]["JOINTS_0"].as_u64().unwrap() as usize;
    let wa = prim["attributes"]["WEIGHTS_0"].as_u64().unwrap() as usize;
    let jv = c.u16s(ja);
    let wv = c.f32s(wa);

    // 引擎侧原始权重和：只比「Σw 严格 1 且影响 ≤4 根」的顶点（导出侧对 Σw≈1
    // 归一、引擎侧不归一，这是记档的口径差，不该混进矩阵对账），
    // 未覆盖顶点单独比（两侧都该原地不动）。
    let mut raw: Vec<Vec<f32>> = vec![Vec::new(); vc];
    let names: std::collections::HashSet<&str> = c.h.bones.iter().map(|b| b.name.as_str()).collect();
    for nd in &c.nodes {
        let Some(s) = &nd.skin else { continue };
        if !names.contains(nd.name.as_str()) {
            continue; // 与导出侧同一过滤：骨名不在骨架里整表跳过
        }
        for (&v, &w) in s.vertices.iter().zip(s.weights.iter()) {
            raw[v as usize].push(w);
        }
    }
    // 两侧现在共用同一份权重整形（`pose::unify_weights`），所以**全部顶点**都能比：
    // 规范侧读产物里的 4 个槽位，引擎侧走同一份 unify 后加权。
    let cmp: Vec<usize> = (0..vc).collect();
    let uncovered: usize = (0..vc).filter(|&v| raw[v].is_empty()).count();
    let off_one: usize =
        (0..vc).filter(|&v| !raw[v].is_empty() && (raw[v].iter().sum::<f32>() - 1.0).abs() > 1e-6).count();
    eprintln!("参与比对：全部 {vc} 顶点（其中原始 Σw≠1 的 {off_one} 个、未覆盖 {uncovered} 个）");
    assert_eq!(cmp.len(), vc, "口径统一后没有任何理由跳过顶点");

    let bind = bind_worlds(&c.h);
    let chs = c.channels(&c.idle01());
    let nodes_f: Vec<Node> =
        c.nodes.iter().filter(|n| names.contains(n.name.as_str())).cloned().collect();
    let mut worst = 0f32;
    let mut worst_at = (0usize, 0usize, String::new());
    for f in 0..c.a.frames {
        let g = c.frame_globals(&chs, f);
        // 规范：skinning_j = G_mesh⁻¹ · G_joint_j · IBM_j（G_mesh = 恒等，闸门 1 已验）
        let pal: Vec<[f32; 16]> = (0..c.bones)
            .map(|j| {
                let ibm = c.mat(ibm_acc, j);
                mul(&g[joints[j]], &ibm)
            })
            .collect();
        let mut glb_pos = vec![[0f32; 3]; vc];
        for v in 0..vc {
            let mut acc = [0f32; 3];
            for k in 0..4 {
                let w = wv[v * 4 + k];
                if w == 0.0 {
                    continue;
                }
                let j = jv[v * 4 + k] as usize;
                let p = apply(&pal[j], c.positions[v]);
                for x in 0..3 {
                    acc[x] += w * p[x];
                }
            }
            glb_pos[v] = acc;
        }
        let eng = posed_vertices(&c.h, &skin_palette(&c.h, &bind, &pose_frame(&c.h, &c.a, f)).unwrap(), &nodes_f, &c.positions)
            .expect("引擎侧蒙皮");
        for &v in &cmp {
            for x in 0..3 {
                let d = (glb_pos[v][x] - eng[v][x]).abs();
                if d > worst {
                    worst = d;
                    worst_at = (f, v, format!("轴{x}"));
                }
            }
        }
        // 未覆盖顶点：两侧都该保持存储位置
        for v in 0..vc {
            if raw[v].is_empty() {
                for x in 0..3 {
                    let d = (glb_pos[v][x] - c.positions[v][x]).abs();
                    assert!(d < 1e-6, "未覆盖顶点 {v} 在查看器侧应原地不动，读到 {d}");
                }
            }
        }
    }
    eprintln!(
        "蒙皮对账：{} 帧 × {} 顶点 · 规范公式 vs pose.rs 最大差 {:e}（第 {} 帧 顶点 {} {}）",
        c.a.frames,
        cmp.len(),
        worst,
        worst_at.0,
        worst_at.1,
        worst_at.2
    );
    assert!(worst < 5e-5, "规范蒙皮结果应与引擎蒙皮一致，差 {worst}");

    // 反向验红：joint↔IBM 配对整体错开一位，误差必须显著变大。
    let g = c.frame_globals(&chs, 20);
    let pal_shift: Vec<[f32; 16]> = (0..c.bones)
        .map(|j| {
            let ibm = c.mat(ibm_acc, (j + 1) % c.bones);
            mul(&g[joints[j]], &ibm)
        })
        .collect();
    let mut shift_worst = 0f32;
    let eng = posed_vertices(
        &c.h,
        &skin_palette(&c.h, &bind, &pose_frame(&c.h, &c.a, 20)).unwrap(),
        &nodes_f,
        &c.positions,
    )
    .unwrap();
    for &v in &cmp {
        let mut acc = [0f32; 3];
        for k in 0..4 {
            let w = wv[v * 4 + k];
            if w == 0.0 {
                continue;
            }
            let j = jv[v * 4 + k] as usize;
            let p = apply(&pal_shift[j], c.positions[v]);
            for x in 0..3 {
                acc[x] += w * p[x];
            }
        }
        for x in 0..3 {
            shift_worst = shift_worst.max((acc[x] - eng[v][x]).abs());
        }
    }
    eprintln!("反向验红：joint↔IBM 错位配对的误差 {shift_worst:.4}（正确配对 {worst:e}）");
    assert!(shift_worst > 1e-3, "配对错位必须被这条对账抓出来，实测只差 {shift_worst}");
}

#[test]
fn glb_animation_channels_carry_stored_ani_values() {
    let Some(c) = setup() else { return };
    let chs = c.channels(&c.idle01());
    let mut rot_checked = 0usize;
    let mut tr_checked = 0usize;
    for (node, ch) in &chs {
        let bone = &c.h.bones[node - 1];
        let t = c.a.tracks.iter().find(|t| t.bone == bone.name).expect("轨道存在");
        let frames = c.a.frames;
        assert_eq!(ch.times.len(), frames);
        assert_eq!(ch.values.len(), frames * ch.comps);
        for f in 0..frames {
            let v = &ch.values[f * ch.comps..(f + 1) * ch.comps];
            match ch.path.as_str() {
                "rotation" => {
                    let stored = &t.rotations[f];
                    let neg: Vec<f32> = stored.iter().map(|x| -x).collect();
                    assert!(
                        v == stored.as_slice() || v == neg.as_slice(),
                        "骨 {} 第 {f} 帧四元数只能整条取反（定半球），不能改分量：{:?} vs {:?}",
                        bone.name,
                        v,
                        stored
                    );
                    if f > 0 {
                        let p = &ch.values[(f - 1) * 4..f * 4];
                        let dot: f32 = p.iter().zip(v.iter()).map(|(a, b)| a * b).sum();
                        assert!(dot >= -1e-6, "相邻帧必须同半球（LINEAR = 归一化线性插值），第 {f} 帧点积 {dot}");
                    }
                    rot_checked += 1;
                }
                "translation" => {
                    assert_eq!(v, &t.positions[f][..], "骨 {} 第 {f} 帧位移应原样写出", bone.name);
                    tr_checked += 1;
                }
                "scale" => {
                    let s = t.scales[f];
                    assert_eq!(v, &[s, s, s], "骨 {} 第 {f} 帧缩放应原样写出", bone.name);
                }
                p => panic!("未知通道路径 {p}"),
            }
        }
        // 关键帧时间 = 帧号 / tick（口径已在导出注释标注为「未证的解读」）
        for (f, tt) in ch.times.iter().enumerate() {
            assert!((tt - f as f32 / c.a.tick).abs() < 1e-6, "时间轴按 帧/tick 写");
        }
    }
    eprintln!(
        "原样性：rotation {rot_checked} 条（同半球定向后相等）· translation {tr_checked} 条 · 逐元素核对"
    );
    assert!(rot_checked >= 40 * 40, "对上名的轨道应覆盖 45 骨 × 41 帧");
}
