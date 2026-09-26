use std::sync::Arc;

use serde::Serialize;
use tauri::State;
use tlbb_core::preview::MeshGeometry;

use crate::data::AppData;
use crate::inspector::b64;/// 一个网格的二进制顶点缓冲：base64(小端) = 位置 vc×3×f32 → 法线(可选) → UV(可选) → 索引 ic×u16。
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

impl MeshData {
    /// 俯视缩略图的瘦身形态：只留包围盒与规模，几何不打包（`buffer` 为空串）。
    /// 字段名与完整形态一字不差，前端不必学第二套契约——只是画不了 3D。
    pub fn outline(path: String, g: &MeshGeometry) -> Self {
        Self {
            path,
            vertex_count: g.positions.len(),
            face_count: g.indices.len() / 3,
            index_count: g.indices.len(),
            submesh_count: g.submesh_count as usize,
            has_normals: g.normals.len() == g.positions.len() && !g.positions.is_empty(),
            has_uvs: g.uvs.len() == g.positions.len() && !g.positions.is_empty(),
            bbox_min: g.bbox_min,
            bbox_max: g.bbox_max,
            middle_bytes: g.middle_bytes,
            trailing_bytes: g.trailing_bytes,
            buffer: String::new(),
        }
    }
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

/// 列表行几何缩略图：把一个网格的全部顶点投影到一个面、量化进 48×48 的格子。
/// 回包只有「哪些格子有顶点」，没有顶点流——列表 300 行若逐个拉 `mesh_data`，
/// 光 base64 就把首屏拖死（这就是地图侧另开 `map_footprint` 的同一个理由）。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MeshOutline {
    /// 用的哪个网格（客户端原文路径）。
    pub path: String,
    /// 参与投影的顶点数（抽样前）。0 顶点的网格回 `None`，不在这里凑数。
    pub vertex_count: usize,
    /// 投影到了哪个面：三个包围盒两两乘积里最大的那个——直立模型是 `xy`，
    /// 平铺贴片是 `xz`。这是几何事实，不是对内容物的猜测。
    pub face: &'static str,
    /// 命中的格子 `[x, y]`（各 0..=47），已去重并按坐标排序。
    pub cells: Vec<[u8; 2]>,
}

/// 缩略图的边长格数。前后端各写一份会分家，回包里就带着格子坐标，
/// 前端只管把格子画满画布。
pub const OUTLINE_CELLS: usize = 48;

fn quantize(positions: &[[f32; 3]], bbox_min: [f32; 3], bbox_max: [f32; 3]) -> MeshOutline {
    let size = [
        bbox_max[0] - bbox_min[0],
        bbox_max[1] - bbox_min[1],
        bbox_max[2] - bbox_min[2],
    ];
    // 三面投影取面积最大的一面：模型大多是直立的（xy 面积大），
    // 地面贴片是平的（xz 面积大）。退化尺寸记 0，乘积自然落选。
    let faces = [
        ("xz", size[0] * size[2], 0usize, 2usize),
        ("xy", size[0] * size[1], 0, 1),
        ("yz", size[1] * size[2], 1, 2),
    ];
    let (_, _, ua, va) = faces
        .into_iter()
        .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap_or(std::cmp::Ordering::Equal))
        .unwrap_or(("xz", 0.0, 0, 2));
    let face = match (ua, va) {
        (0, 1) => "xy",
        (0, 2) => "xz",
        _ => "yz",
    };
    // 投影面内等比缩放：长边铺满 0..=47，短边按比例留白居中——
    // 不等比直接铺满会把细长模型压成正方形块，那就是在骗人。
    let (su, sv) = (size[ua].abs(), size[va].abs());
    let span = su.max(sv).max(f32::EPSILON);
    let half = OUTLINE_CELLS as f32 / 2.0 - 0.5;
    let scale_u = if su > f32::EPSILON { half * (su / span) } else { 0.0 };
    let scale_v = if sv > f32::EPSILON { half * (sv / span) } else { 0.0 };
    let mut cells: Vec<[u8; 2]> = Vec::new();
    for p in positions {
        // t 是包围盒内的归一化位置 0..=1；居中映射到 [half-scale, half+scale]。
        let tu = if su > f32::EPSILON { (p[ua] - bbox_min[ua]) / su } else { 0.5 };
        let tv = if sv > f32::EPSILON { (p[va] - bbox_min[va]) / sv } else { 0.5 };
        let cu = (half + (tu - 0.5) * 2.0 * scale_u).round().clamp(0.0, 47.0) as u8;
        let cv = (half + (tv - 0.5) * 2.0 * scale_v).round().clamp(0.0, 47.0) as u8;
        if let Err(i) = cells.binary_search(&[cu, cv]) {
            cells.insert(i, [cu, cv]);
        }
    }
    MeshOutline {
        path: String::new(),
        vertex_count: positions.len(),
        face,
        cells,
    }
}

/// `group_mesh_outline` 的实现：组里第一个真能解出几何的网格成员。
/// 普通函数（不挂在命令上）是为了 `--probe` 能无窗口跑同一条路落盘夹具。
pub fn outline_of(g: &MeshGeometry, path: String) -> MeshOutline {
    let mut o = quantize(&g.positions, g.bbox_min, g.bbox_max);
    o.path = path;
    o
}

#[tauri::command]
pub async fn group_mesh_outline(
    app: State<'_, Arc<AppData>>,
    gid: i64,
) -> Result<Option<MeshOutline>, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || app.group_outline(gid).map(|o| o.map(|a| (*a).clone())))
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

    #[test]
    fn 投影面取面积最大的一面() {
        // 平铺贴片：xz 10×8 远大于 y 方向的 0.1。
        let flat = vec![[0.0, 0.0, 0.0], [10.0, 0.1, 8.0]];
        assert_eq!(quantize(&flat, [0.0; 3], [10.0, 0.1, 8.0]).face, "xz");
        // 直立模型：xy 1×10 远大于 z 方向的 0.5。
        let tall = vec![[0.0, 0.0, 0.0], [1.0, 10.0, 0.5]];
        assert_eq!(quantize(&tall, [0.0; 3], [1.0, 10.0, 0.5]).face, "xy");
    }

    #[test]
    fn 长边铺满短边等比居中且重复顶点只占一格() {
        // 直立模型（xy 面）：x 只占 1、y 占 10。长边 y 必须铺满 0..=47，
        // 短边 x 按比例缩在中间——两边都铺满就是把细长模型压成方块，那是骗人。
        let ps = vec![
            [0.0, 0.0, 0.0],
            [1.0, 10.0, 0.0],
            [0.5, 5.0, 0.0],
            [0.5, 5.0, 0.0], // 与上一条重复，只能占一个格子
        ];
        let o = quantize(&ps, [0.0; 3], [1.0, 10.0, 0.0]);
        assert_eq!(o.face, "xy");
        assert_eq!(o.vertex_count, 4);
        assert_eq!(o.cells.len(), 3);
        let mut ys = o.cells.iter().map(|c| c[1]).collect::<Vec<_>>();
        ys.sort_unstable();
        assert_eq!(ys.first(), Some(&0), "长边要铺满到 0");
        assert_eq!(ys.last(), Some(&47), "长边要铺满到 47");
        let mut xs = o.cells.iter().map(|c| c[0]).collect::<Vec<_>>();
        xs.sort_unstable();
        // 短边 x 跨度 ≈ 47/10 < 6 格，且整体居中。
        assert!(xs.last().unwrap() - xs.first().unwrap() <= 6);
        assert!(*xs.first().unwrap() >= 18 && *xs.last().unwrap() <= 30);
    }

    #[test]
    fn 退化包围盒全部落进中心格不越界() {
        // 三个尺寸全 0（单点/共点网格）：不该除零 panic，也不该出 48 以外的格子。
        let o = quantize(&[[0.0, 0.0, 0.0]], [0.0; 3], [0.0; 3]);
        assert_eq!(o.cells, vec![[24, 24]]);
    }
}
