use std::sync::Arc;

use serde::Serialize;
use tauri::State;
use tlbb_core::preview::MeshGeometry;

use crate::data::AppData;
use crate::inspector::b64;

/// 一个网格的二进制顶点缓冲：base64(小端) = 位置 vc×3×f32 → 法线(可选) → UV(可选) → 索引 ic×u16。
/// 逐元素 JSON 在 5.5 万顶点上会写成几 MB 文本，前端光 JSON.parse 就吃掉验收预算，
/// 所以这里打包成一段字节，前端 atob 之后直接套 Float32Array / Uint16Array 视图。
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MeshData {
    /// 客户端原文路径，界面标题用它。
    pub path: String,
    pub vertex_count: usize,
    pub face_count: usize,
    pub index_count: usize,
    /// 0x94 处的子网格计数；多子网格的索引分块尚未解出（M2-3）。
    pub submesh_count: usize,
    pub has_normals: bool,
    pub has_uvs: bool,
    pub bbox_min: [f32; 3],
    pub bbox_max: [f32; 3],
    /// 位置流与索引块之间没读懂的字节数（蒙皮类模型的主要未知段，M2-4）。
    pub middle_bytes: usize,
    pub trailing_bytes: usize,
    pub buffer: String,
}

fn pack(g: &MeshGeometry) -> Vec<u8> {
    let mut buf = Vec::with_capacity(g.positions.len() * 32 + g.indices.len() * 2);
    for p in &g.positions {
        for v in p {
            buf.extend_from_slice(&v.to_le_bytes());
        }
    }
    for n in &g.normals {
        for v in n {
            buf.extend_from_slice(&v.to_le_bytes());
        }
    }
    for u in &g.uvs {
        for v in u {
            buf.extend_from_slice(&v.to_le_bytes());
        }
    }
    for i in &g.indices {
        buf.extend_from_slice(&i.to_le_bytes());
    }
    buf
}

impl From<(String, MeshGeometry)> for MeshData {
    fn from((path, g): (String, MeshGeometry)) -> Self {
        let has_normals = g.normals.len() == g.positions.len() && !g.positions.is_empty();
        let has_uvs = g.uvs.len() == g.positions.len() && !g.positions.is_empty();
        let buffer = b64(&pack(&g));
        Self {
            path,
            vertex_count: g.positions.len(),
            face_count: g.indices.len() / 3,
            index_count: g.indices.len(),
            submesh_count: g.submesh_count as usize,
            has_normals,
            has_uvs,
            bbox_min: g.bbox_min,
            bbox_max: g.bbox_max,
            middle_bytes: g.middle_bytes,
            trailing_bytes: g.trailing_bytes,
            buffer,
        }
    }
}

#[tauri::command]
pub async fn mesh_data(
    app: State<'_, Arc<AppData>>,
    name: String,
    hash: Option<String>,
) -> Result<MeshData, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || {
        app.mesh_geometry(&name, hash.as_deref()).map(Into::into)
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;

    // 前端按 hasNormals / hasUvs 决定读取偏移，所以缓冲布局是跨语言的契约。
    // 真实数据这一路已由 `tlbb-shell --probe` 的 M2-2 验收段核过，这里只钉住打包格式。
    fn geom(vc: usize, normals: usize, uvs: usize) -> MeshGeometry {
        MeshGeometry {
            vertex_count: vc as u32,
            face_count: 1,
            submesh_count: 0,
            positions: (0..vc).map(|i| [i as f32, 0.5, -0.25]).collect(),
            normals: (0..normals).map(|i| [0.0, i as f32, 1.0]).collect(),
            uvs: (0..uvs).map(|i| [i as f32 * 0.1, 1.0]).collect(),
            indices: vec![0, 1, 2],
            bbox_min: [0.0, 0.0, 0.0],
            bbox_max: [1.0, 1.0, 1.0],
            middle_bytes: 0,
            trailing_bytes: 0,
        }
    }

    fn f32s(b: &[u8], at: usize) -> [f32; 3] {
        [0, 1, 2].map(|k| f32::from_le_bytes(b[at + k * 4..at + k * 4 + 4].try_into().unwrap()))
    }

    #[test]
    fn 静态布局按位置法线uv索引顺序打包() {
        let out = pack(&geom(3, 3, 3));
        assert_eq!(out.len(), 3 * 12 + 3 * 12 + 3 * 8 + 3 * 2);
        assert_eq!(f32s(&out, 0), [0.0, 0.5, -0.25]);
        assert_eq!(f32s(&out, 2 * 12), [2.0, 0.5, -0.25]);
        // 法线段紧跟位置段
        assert_eq!(f32s(&out, 3 * 12 + 12), [0.0, 1.0, 1.0]);
        let m = MeshData::from(("x/y.mesh".into(), geom(3, 3, 3)));
        assert!(m.has_normals && m.has_uvs);
        assert_eq!((m.vertex_count, m.face_count, m.index_count), (3, 1, 3));
        assert_eq!(m.buffer.len(), out.len().div_ceil(3) * 4);
    }

    #[test]
    fn 蒙皮类模型没有法线与uv时缓冲直接接索引() {
        let out = pack(&geom(3, 0, 0));
        assert_eq!(out.len(), 3 * 12 + 3 * 2);
        assert_eq!(f32s(&out, 12), [1.0, 0.5, -0.25]);
        let idx = &out[3 * 12..];
        assert_eq!(idx, &[0, 0, 1, 0, 2, 0]);
        let m = MeshData::from(("x/y.mesh".into(), geom(3, 0, 0)));
        assert!(!m.has_normals && !m.has_uvs);
        // 长度对不上顶点数就不能谎报有法线，否则前端按错误偏移读出一堆垃圾坐标。
        assert!(!MeshData::from(("x".into(), geom(3, 2, 2))).has_normals);
    }
}
