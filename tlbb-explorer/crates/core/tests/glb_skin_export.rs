//! rigged glb 导出闸门：`export::gltf::to_glb_rigged` 用真数据（yifu_001 + idle01）
//! 导出后**自己吃回来**逐项验。本文件自带一份最小 GLB 解析（bin chunk +
//! serde_json，均已有依赖），不引新依赖：
//!
//! 1. GLB 二进制布局逐项验：magic / version / 总长 / 两个 chunk 的长度 4 对齐与类型；
//! 2. JSON 可解析、scene/node 数一致、node 树的父子关系与 `parse_hierarchy` 逐骨一致；
//! 3. skin.joints 数 == 骨架骨数（46）；inverseBindMatrices 的 accessor 数 == 骨数
//!    且每条 3×3 行列式非零（可逆）；
//! 4. JOINTS_0 索引全部 < joints 数；WEIGHTS_0 逐槽位与 `pose::unify_weights`
//!    （导出侧调的同一份函数）对表，并钉住**每顶点权重和正好 1.0**（glTF 硬要求）；
//! 5. animation 通道的 sampler 输出长度 == 帧数、target node 都在 joints 里、
//!    rotation 输出全是单位四元数（或全零静止骨）、通道数 = 3 × 对上名的轨道数；
//! 6. 对不上骨名的轨道（idle01 里那条未命名轨道）在 `asset.extras` 里计数报告。
//!
//! 真数据缺席（没有客户端 / 资源不在库里）→ 打印说明跳过，不算失败——照
//! `bone_hierarchy.rs` 的做法。

use std::path::PathBuf;

use serde_json::{json, Value};
use tlbb_core::export::gltf::{to_glb_rigged, RigExport};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::pose::WeightCase;
use tlbb_core::preview::{parse_ani, parse_hierarchy, parse_mesh, parse_nodes};

/// w1351_monster_xiyuqiezei_yifu_001.mesh：46 骨主样本（与 bone_hierarchy/pose_compose 同源）
const MESH: u64 = 0xbcd65050a62986b7;
/// w1351_monster_xiyuqiezei_idle01.ani（41 帧）
const ANI_IDLE01: u64 = 0x4ec2478a169d5e73;

fn raw_of(root: &PathBuf, pak: &str, hash: u64) -> Option<Vec<u8>> {
    let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(&p, &rec).ok().map(|d| d.bytes)
}

fn bytes_of(hash: u64) -> Option<Vec<u8>> {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    raw_of(&root, "data", hash)
}

// ------------------------------------------------------------------ 最小 GLB 解析

struct Glb {
    doc: Value,
    bin: Vec<u8>,
}

const CHUNK_JSON: u32 = 0x4E4F_534A;
const CHUNK_BIN: u32 = 0x004E_4942;

/// 布局逐项验在这一步完成：magic、version、总长、chunk 长度 4 对齐、chunk 类型、
/// buffer byteLength 与 BIN chunk 实际长度一致。
fn parse_glb(bytes: &[u8]) -> Glb {
    assert!(bytes.len() >= 12, "GLB 头 12 字节都不够");
    assert_eq!(&bytes[0..4], b"glTF", "magic 必须是 glTF");
    assert_eq!(u32::from_le_bytes(bytes[4..8].try_into().unwrap()), 2, "version 必须 2");
    let total = u32::from_le_bytes(bytes[8..12].try_into().unwrap()) as usize;
    assert_eq!(total, bytes.len(), "头里的总长必须等于实际字节数");

    let jlen = u32::from_le_bytes(bytes[12..16].try_into().unwrap()) as usize;
    assert_eq!(jlen % 4, 0, "JSON chunk 长度必须 4 对齐");
    assert_eq!(
        u32::from_le_bytes(bytes[16..20].try_into().unwrap()),
        CHUNK_JSON,
        "第一个 chunk 必须是 JSON"
    );
    assert!(20 + jlen + 8 <= bytes.len(), "JSON chunk 之后放不下 BIN chunk 头");
    let doc: Value =
        serde_json::from_slice(&bytes[20..20 + jlen]).expect("JSON chunk 必须是合法 JSON");

    let bhead = 20 + jlen;
    let blen = u32::from_le_bytes(bytes[bhead..bhead + 4].try_into().unwrap()) as usize;
    assert_eq!(blen % 4, 0, "BIN chunk 长度必须 4 对齐");
    assert_eq!(
        u32::from_le_bytes(bytes[bhead + 4..bhead + 8].try_into().unwrap()),
        CHUNK_BIN,
        "第二个 chunk 必须是 BIN"
    );
    assert_eq!(
        bytes.len(),
        12 + 8 + jlen + 8 + blen,
        "总长 = 12B 头 + JSON chunk + BIN chunk，分毫不差"
    );
    assert_eq!(
        doc["buffers"][0]["byteLength"].as_u64().unwrap() as usize,
        blen,
        "buffers[0].byteLength 必须等于 BIN chunk 长度"
    );
    Glb { doc, bin: bytes[bhead + 8..bhead + 8 + blen].to_vec() }
}

impl Glb {
    /// accessor 指向的字节段（buffer 0；导出侧每个 accessor 都有独立 view，
    /// 索引 accessor 共享 view 时按 view 长 − accessor byteOffset 取）。
    fn slice(&self, acc_idx: usize) -> &[u8] {
        let acc = &self.doc["accessors"][acc_idx];
        let bv = acc["bufferView"].as_u64().unwrap() as usize;
        let view = &self.doc["bufferViews"][bv];
        let voff = view["byteOffset"].as_u64().unwrap() as usize;
        let vlen = view["byteLength"].as_u64().unwrap() as usize;
        let aoff = acc.get("byteOffset").and_then(|b| b.as_u64()).unwrap_or(0) as usize;
        &self.bin[voff + aoff..voff + vlen]
    }

    fn f32s(&self, acc_idx: usize) -> Vec<f32> {
        self.slice(acc_idx)
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
            .collect()
    }

    fn u16s(&self, acc_idx: usize) -> Vec<u16> {
        self.slice(acc_idx)
            .chunks_exact(2)
            .map(|c| u16::from_le_bytes(c.try_into().unwrap()))
            .collect()
    }
}

// ------------------------------------------------------------------ 主闸门

#[test]
fn rigged_glb_eats_back_through_every_gate() {
    let (Some(mesh), Some(ani)) = (bytes_of(MESH), bytes_of(ANI_IDLE01)) else {
        eprintln!("跳过：本机没有 data.pak 或这两份资源不在里面（夹具不入库）");
        return;
    };
    let l = parse_mesh(&mesh).expect("yifu_001 应能解析");
    let h = parse_hierarchy(&mesh).expect("父骨链应能解出");
    let nodes = parse_nodes(&mesh);
    let a = parse_ani(&ani).expect("idle01 应能解出");
    let bones = h.bones.len();
    let vc = l.geometry.vertex_count as usize;
    assert_eq!(bones, 46, "主样本声明 46 根骨");
    assert_eq!(vc, 781, "yifu_001 实测 781 顶点");
    assert_eq!(a.frames, 41, "idle01 实测 41 帧");

    let rig = RigExport { hierarchy: &h, influences: &nodes };
    let bytes = to_glb_rigged(
        "w1351_monster_xiyuqiezei_yifu_001",
        &l,
        &[],
        Some(&rig),
        &[("idle01", &a)],
    )
    .expect("rigged 导出应成功");

    let glb = parse_glb(&bytes); // 闸门 1：GLB 布局逐项验
    let doc = &glb.doc;

    // ---- scene / node 数一致，node 树与骨架逐骨一致
    let node_arr = doc["nodes"].as_array().expect("nodes 数组");
    assert_eq!(node_arr.len(), 1 + bones, "网格节点 + 每根骨一个节点");
    assert_eq!(doc["scene"], json!(0));
    assert_eq!(doc["scenes"][0]["nodes"], json!([0, 1]), "网格节点 + 根骨节点（根骨是 bones[0]）");
    assert_eq!(node_arr[0]["mesh"], json!(0));
    assert_eq!(node_arr[0]["skin"], json!(0), "网格节点挂 skin");
    for (i, b) in h.bones.iter().enumerate() {
        assert_eq!(node_arr[1 + i]["name"].as_str(), Some(b.name.as_str()), "骨 {i} 名字");
        // joint node 都用 TRS（被动画 target 的 node 规范不允许 matrix）
        assert!(node_arr[1 + i]["rotation"].is_array());
        assert!(node_arr[1 + i]["translation"].is_array());
        assert!(node_arr[1 + i]["scale"].is_array());
        if let Some(p) = b.parent {
            let kids = node_arr[1 + p]["children"].as_array().unwrap_or_else(|| {
                panic!("骨 {}（{}）的父 node 该有 children", b.name, i)
            });
            assert!(
                kids.iter().any(|k| k.as_u64() == Some((1 + i) as u64)),
                "骨 {} 必须出现在父 node 的 children 里",
                b.name
            );
        }
    }
    // 每个 joint 都能从 scene 根走到（glTF 要求 joints 与网格同 scene）
    let mut reachable = vec![false; node_arr.len()];
    let mut stack = vec![0usize, 1usize];
    while let Some(x) = stack.pop() {
        if reachable[x] {
            continue;
        }
        reachable[x] = true;
        if let Some(kids) = node_arr[x]["children"].as_array() {
            for k in kids {
                stack.push(k.as_u64().unwrap() as usize);
            }
        }
    }
    for j in 0..bones {
        assert!(reachable[1 + j], "joint {}（{}）不在 scene 树里", j, h.bones[j].name);
    }

    // ---- skin：joints 数 == 骨数，IBM 数 == 骨数且每条可逆
    let skin = &doc["skins"][0];
    let joints: Vec<usize> = skin["joints"]
        .as_array()
        .expect("skin.joints")
        .iter()
        .map(|j| j.as_u64().unwrap() as usize)
        .collect();
    assert_eq!(joints.len(), bones);
    assert!(
        joints.iter().enumerate().all(|(i, &j)| j == 1 + i),
        "joint 顺序 = hierarchy 骨序（node = 骨下标 + 1）"
    );
    assert_eq!(skin["skeleton"], json!(1), "骨架根 = 根骨 node");
    let ibm_acc = skin["inverseBindMatrices"].as_u64().unwrap() as usize;
    let ibm_meta = &doc["accessors"][ibm_acc];
    assert_eq!(ibm_meta["count"], json!(bones), "IBM accessor 数 == 骨数");
    assert_eq!(ibm_meta["type"], json!("MAT4"));
    let ibm = glb.f32s(ibm_acc);
    assert_eq!(ibm.len(), bones * 16);
    for (j, m) in ibm.chunks_exact(16).enumerate() {
        // 引擎行主序口径：前三行是 3×3（导出按原顺序写，推导见 export/gltf.rs）
        let det = m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8])
            + m[2] * (m[4] * m[9] - m[5] * m[8]);
        assert!(det.is_finite() && det.abs() > 1e-6, "joint {j} 的 IBM 不可逆（det={det}）");
    }

    // ---- JOINTS_0 / WEIGHTS_0
    let prim = &doc["meshes"][0]["primitives"][0];
    let ja = prim["attributes"]["JOINTS_0"].as_u64().unwrap() as usize;
    assert_eq!(doc["accessors"][ja]["componentType"], json!(5123), "JOINTS_0 用 u16");
    assert_eq!(doc["accessors"][ja]["type"], json!("VEC4"));
    assert_eq!(doc["accessors"][ja]["count"], json!(vc));
    let joints_v = glb.u16s(ja);
    assert_eq!(joints_v.len(), vc * 4);
    assert!(
        joints_v.iter().all(|&j| (j as usize) < bones),
        "JOINTS_0 索引必须全部 < joints 数（{}）",
        bones
    );
    let wa = prim["attributes"]["WEIGHTS_0"].as_u64().unwrap() as usize;
    assert_eq!(doc["accessors"][wa]["componentType"], json!(5126), "WEIGHTS_0 用 f32");
    assert_eq!(doc["accessors"][wa]["count"], json!(vc));
    let weights_v = glb.f32s(wa);
    assert_eq!(weights_v.len(), vc * 4);

    // 逐顶点权重与 `pose::unify_weights`（导出侧调的就是同一份函数）对表。
    // 两件事分开钉：① 数据侧事实——原始 Σw 严格为 1.0 的顶点 README 实测 441 个；
    // ② 产物侧要求——**每个顶点写出的 4 个权重之和必须正好 1.0**，这是 glTF 的
    // 硬要求（官方校验器对不合的报 ACCESSOR_WEIGHTS_NON_NORMALIZED，实测这份
    // 样本原先欠 114 个）。差额挂根骨、按和归一等分类由 ② 顺带核。
    let root_bone = h.bones.iter().position(|b| b.parent.is_none()).expect("骨架单根");
    let mut per: Vec<Vec<(usize, f32)>> = vec![Vec::new(); vc];
    let mut raw_sum: Vec<f32> = vec![0.0; vc];
    let mut listed = vec![false; vc]; // 出现在任意表里（含 0 权重项）
    for nd in &nodes {
        let Some(s) = &nd.skin else { continue };
        let Some(bi) = h.bones.iter().position(|b| b.name == nd.name) else { continue };
        for (&v, &w) in s.vertices.iter().zip(s.weights.iter()) {
            listed[v as usize] = true;
            if w > 0.0 {
                per[v as usize].push((bi, w));
            }
            raw_sum[v as usize] += w;
        }
    }
    let mut cases = [0usize; 4]; // 未覆盖 / 容差内归一 / 差额挂根骨 / 只能按和归一
    let mut exact_one = 0usize;
    for v in 0..vc {
        if (raw_sum[v] - 1.0).abs() < 1e-6 {
            exact_one += 1;
        }
        let (packed, case) = tlbb_core::preview::pose::unify_weights(&per[v], root_bone);
        cases[match case {
            WeightCase::Uncovered => 0,
            WeightCase::Normalized => 1,
            WeightCase::RootFilled => 2,
            WeightCase::Rescaled => 3,
        }] += 1;
        // 与写进产物的那 4 个槽位逐一对表
        let mut want_j = [0u16; 4];
        let mut want_w = [0f32; 4];
        for (k, (j, w)) in packed.iter().enumerate() {
            want_j[k] = *j as u16;
            want_w[k] = *w;
        }
        let got_j = &joints_v[v * 4..v * 4 + 4];
        let got_w = &weights_v[v * 4..v * 4 + 4];
        assert_eq!(got_j, want_j, "顶点 {v} 的 JOINTS_0 与整形结果不符");
        let sum: f32 = got_w.iter().sum();
        assert!((sum - 1.0).abs() < 2e-6, "顶点 {v} 的权重和必须是 1.0，实测 {sum}");
        for k in 0..4 {
            assert!(
                (got_w[k] - want_w[k]).abs() < 2e-6,
                "顶点 {v} 槽位 {k} 权重 {:>7.4} ≠ 整形 {:>7.4}（{:?}）",
                got_w[k],
                want_w[k],
                packed
            );
            if got_w[k] == 0.0 {
                assert_eq!(got_j[k], 0, "顶点 {v} 槽位 {k} 权重 0 却挂着骨号 {}（校验器会报零权重）", got_j[k]);
            }
        }
    }
    let (uncovered, normalized, root_fill, rescaled) = (cases[0], cases[1], cases[2], cases[3]);
    eprintln!(
        "权重对账：{vc} 顶点 · 原始 Σw 严格 1.0 的 {exact_one} 个 · 未覆盖挂根骨 {uncovered} · \
         容差内归一 {normalized} · 差额挂根骨 {root_fill} · 按和强归 {rescaled}"
    );
    // README 实测锚点：26 根带表、**出现在表里**的顶点 555 个、其中 441 个 Σ 正好 1.0。
    // 555 里刨掉 26 个「表项权重全是 0」的顶点（剔除 0 权重后它们与未覆盖无异），
    // 剩下的才是真正带权重的：441 归一 + 88 差额挂根骨 = 529，未覆盖 226 + 26 = 252。
    // 这三条等式一起钉住「导出口径没偷改覆盖数」，也钉住那 26 个顶点的存在。
    let listed_only_zero = (0..vc).filter(|&v| listed[v] && per[v].is_empty()).count();
    assert_eq!(normalized + root_fill + rescaled + listed_only_zero, 555, "带表顶点数应与 README 实测的 555 一致");
    assert_eq!(listed_only_zero, 26, "全 0 权重表的顶点（实测 26 个）");
    assert_eq!(uncovered, vc - 555 + listed_only_zero, "未覆盖 = 555 之外 + 那 26 个全 0 表项的");
    assert_eq!(normalized + root_fill + rescaled, 529, "真正带权重的顶点数");
    assert!(exact_one >= 441, "原始 Σw 严格 1.0 的顶点不得低于 README 实测的 441");
    // extras 报的分类数必须与这里独立数出来的一致（导出器不许自说自话）
    let extras = &doc["asset"]["extras"]["rig"];
    assert_eq!(extras["uncoveredVertices"], json!(uncovered));
    assert_eq!(extras["normalizedVertices"], json!(normalized));
    assert_eq!(extras["rootFillVertices"], json!(root_fill));
    assert_eq!(extras["weightSumOffVertices"], json!(rescaled));

    // ---- animation：通道长度 == 帧数、target 都在 joints、rotation 单位四元数
    let anims = doc["animations"].as_array().expect("animations 数组");
    assert_eq!(anims.len(), 1);
    let an = &anims[0];
    assert_eq!(an["name"], json!("idle01"));
    let matched: Vec<&str> = a
        .tracks
        .iter()
        .filter(|t| !t.bone.is_empty() && h.bones.iter().any(|b| b.name == t.bone))
        .map(|t| t.bone.as_str())
        .collect();
    let channels = an["channels"].as_array().expect("channels");
    assert_eq!(
        channels.len(),
        3 * matched.len(),
        "每条对上名的轨道 3 个通道（rotation/translation/scale）"
    );
    let samplers = an["samplers"].as_array().expect("samplers");
    assert_eq!(samplers.len(), 3 * matched.len());
    for ch in channels {
        let node = ch["target"]["node"].as_u64().unwrap() as usize;
        assert!(
            joints.contains(&node),
            "target node {node} 必须在 skin.joints 里"
        );
        let s = &samplers[ch["sampler"].as_u64().unwrap() as usize];
        let inp = s["input"].as_u64().unwrap() as usize;
        let out = s["output"].as_u64().unwrap() as usize;
        assert_eq!(doc["accessors"][inp]["count"], json!(a.frames), "sampler 输入长度 == 帧数");
        assert_eq!(doc["accessors"][out]["count"], json!(a.frames), "sampler 输出长度 == 帧数");
        match ch["target"]["path"].as_str().unwrap() {
            "rotation" => {
                assert_eq!(doc["accessors"][out]["type"], json!("VEC4"));
                for q in glb.f32s(out).chunks_exact(4) {
                    let n = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt();
                    assert!(
                        n < 1e-6 || (0.98..=1.02).contains(&n),
                        "rotation 输出必须是单位四元数（全零=静止骨），读到 {q:?}"
                    );
                }
            }
            "translation" => assert_eq!(doc["accessors"][out]["type"], json!("VEC3")),
            "scale" => {
                assert_eq!(doc["accessors"][out]["type"], json!("VEC3"));
                assert!(glb.f32s(out).iter().all(|v| (v - 1.0).abs() < 1e-6), "scale 数据恒 1");
            }
            p => panic!("未知通道路径 {p}"),
        }
    }
    // 时间轴：帧号 / tick（0xC6 按「每秒 tick 数」解读，未证——口径见导出注释）
    let t0 = ch_time(&glb, an);
    assert_eq!(t0.len(), a.frames);
    assert!((t0[0] - 0.0).abs() < 1e-6);
    assert!((t0[a.frames - 1] - (a.frames - 1) as f32 / a.tick).abs() < 1e-5);

    // ---- 对账数字在 extras：对不上的轨道如实计数
    let extras = &doc["asset"]["extras"]["rig"];
    assert_eq!(extras["joints"], json!(bones));
    assert_eq!(extras["bonesWithoutBind"].as_array().unwrap().len(), 16, "46−30 根无 96B 记录的骨");
    let anim_stats = &extras["animations"][0];
    assert_eq!(anim_stats["tracks"], json!(a.tracks.len()));
    assert_eq!(anim_stats["matchedTracks"], json!(matched.len()));
    let unmatched = anim_stats["unmatchedTracks"].as_array().unwrap();
    assert_eq!(
        unmatched.len(),
        a.tracks.len() - matched.len(),
        "对不上骨名的轨道（含未命名）必须计数报告"
    );
    eprintln!(
        "动画 idle01：{} 轨道 · 对上 {} · 对不上 {:?} · 通道 {}",
        a.tracks.len(),
        matched.len(),
        unmatched,
        channels.len()
    );
}

fn ch_time(glb: &Glb, an: &Value) -> Vec<f32> {
    let s = &an["samplers"][0];
    let inp = s["input"].as_u64().unwrap() as usize;
    glb.f32s(inp)
}

/// 静态出口不回归：`to_glb`（= rigged 空跑）不产 skins/animations——
/// 这条钉住「没解出的东西不写」，与 export/gltf.rs 的既有单测互为犄角。
#[test]
fn static_export_still_has_no_skin() {
    let Some(mesh) = bytes_of(MESH) else {
        eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
        return;
    };
    let l = parse_mesh(&mesh).expect("yifu_001 应能解析");
    let bytes = to_glb_rigged("yifu_001", &l, &[], None, &[]).expect("导出");
    let glb = parse_glb(&bytes);
    assert!(glb.doc.get("skins").is_none());
    assert!(glb.doc.get("animations").is_none());
    assert_eq!(glb.doc["nodes"].as_array().unwrap().len(), 1);
    assert_eq!(glb.doc["scenes"][0]["nodes"], json!([0]));
}
