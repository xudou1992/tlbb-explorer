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
//! - **不写 skin / animation**：`.mesh` 里没有骨骼权重（已穷举证实），
//!   `.ske` 里也没有骨骼矩阵，写进去就是造假。
//!
//! 坐标：客户端是 Y-up（实测立绘模型 y 跨度 = 身高），glTF 也是 Y-up 右手系，
//! 单位按米，不做任何轴向变换。

use serde_json::{json, Value};

use crate::preview::geometry::MeshLayout;

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

/// 拼一个 `.glb`。几何与子网格切分全部来自 [`MeshLayout`]。
pub fn to_glb(name: &str, l: &MeshLayout, slots: &[SlotStyle]) -> Result<Vec<u8>, String> {
    let g = &l.geometry;
    if g.vertex_count == 0 || g.indices.is_empty() {
        return Err("没有顶点或没有三角面，glb 里放不了空网格".to_string());
    }
    let vc = g.vertex_count as usize;

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
    let pos_view = push_f32(&mut bin, &mut views, |o| {
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
        let v = push_f32(&mut bin, &mut views, |o| {
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
        let v = push_f32(&mut bin, &mut views, |o| {
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
        let v = push(&mut bin, &mut views, |o| {
            for &x in &g.indices {
                o.extend_from_slice(&x.to_le_bytes());
            }
        });
        views[v]["target"] = json!(34963); // ELEMENT_ARRAY_BUFFER
        v
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

    let doc = json!({
        "asset": {"version": "2.0", "generator": "tlbb-core mesh→glb（私有 .mesh 几何转换）"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{
            "name": name,
            "primitives": primitives,
        }],
        "materials": materials,
        "accessors": accs,
        "bufferViews": views,
        "buffers": [{"byteLength": bin.len()}],
    });

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
    Ok(out)
}

fn push(bin: &mut Vec<u8>, views: &mut Vec<Value>, write: impl FnOnce(&mut Vec<u8>)) -> usize {
    while bin.len() % 4 != 0 {
        bin.push(0);
    }
    let off = bin.len();
    write(bin);
    views.push(json!({"buffer": 0, "byteOffset": off, "byteLength": bin.len() - off}));
    views.len() - 1
}

/// f32 数据流要 4 字节对齐；写进去就是原样，view 不带 byteStride（单属性打包）。
fn push_f32(
    bin: &mut Vec<u8>,
    views: &mut Vec<Value>,
    write: impl FnOnce(&mut Vec<u8>),
) -> usize {
    let i = push(bin, views, write);
    if let Some(v) = views.get_mut(i) {
        v["target"] = json!(34962); // ARRAY_BUFFER
    }
    i
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
}
