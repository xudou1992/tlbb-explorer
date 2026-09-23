//! `.mesh` 几何段解析（M2-1）：顶点 / 法线 / UV / 索引 / 包围盒。
//!
//! 布局（2026-09-23 用 7 个样本交叉验证，424B 平面片手工解码闭环，
//! 2.3MB 减震器大模型坐标合理性核对通过）：
//!
//! ```text
//! 0x00  64B   版权串（信封，见 summary::parse_envelope）
//! 0x40   8B   类型标签 "mesh"
//! 0x48   4B   版本
//! 0x4C  64B   备注
//! 0x8C   4B   u32 顶点数
//! 0x90   4B   u32 三角面数
//! 0x94   4B   u32 子网格 / 材质槽数
//! 0x98…0x117  头部剩余区（本批样本全零，语义未定——不解读，只跳过）
//! 0x118       顶点位置  vc × 3 × f32（连续流）
//!             法线      vc × 3 × f32
//!             UV        vc × 2 × f32
//!             [u32 面数] + 面数 × 3 × u16 索引
//!             …其后可能有蒙皮 / 子网格表（本解析器不计入，只报告剩余字节数）
//! ```
//!
//! 纪律：计数与流长度对不上就报错，**绝不猜**。索引越界是数据问题，
//! 如实报错而不是夹断。

/// 解出的几何体。大模型约 1.8 MB 纯数据（55k 顶点），调用方按需取。
#[derive(Debug, Clone, PartialEq)]
pub struct MeshGeometry {
    pub vertex_count: u32,
    pub face_count: u32,
    /// 子网格 / 材质槽数（0x94；语义按「fwzhongxing 7 槽模型此处=7」推断，
    /// 没有第二来源前只如实转述数值）。
    pub submesh_count: u32,
    pub positions: Vec<[f32; 3]>,
    /// 法线（vc × 3）。**仅静态布局模型可得**；蒙皮类模型顶点流与索引之间
    /// 有未解的中间数据段，此时为空——缺就是缺，不用位置流凑数。
    pub normals: Vec<[f32; 3]>,
    /// UV（vc × 2）。可得条件同 [`MeshGeometry::normals`]。
    pub uvs: Vec<[f32; 2]>,
    /// 三角形索引（u16，长度 = 面数 × 3）。
    pub indices: Vec<u16>,
    pub bbox_min: [f32; 3],
    pub bbox_max: [f32; 3],
    /// 位置流结束到索引块之间的字节数。静态布局=64（法线+UV），
    /// 蒙皮类大得多且布局未解——只报告，不解读。
    pub middle_bytes: usize,
    /// 索引块之后剩余未解读的字节数（蒙皮/子网格表等，如实报告）。
    pub trailing_bytes: usize,
}

fn u32_at(raw: &[u8], off: usize) -> Result<u32, String> {
    let b = raw
        .get(off..off + 4)
        .ok_or_else(|| format!("文件在 {off:#x} 处截断，读不到 u32"))?;
    Ok(u32::from_le_bytes(b.try_into().unwrap()))
}

fn f32_stream(raw: &[u8], off: usize, n: usize) -> Result<Vec<f32>, String> {
    let need = n * 4;
    let b = raw
        .get(off..off + need)
        .ok_or_else(|| format!("几何数据在 {off:#x} 处截断：需要 {need} 字节，只剩 {}", raw.len() - off))?;
    Ok(b.chunks_exact(4)
        .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
        .collect())
}

/// 在 `[lo, hi)` 里按 4 字节步进找一个位置：`u32 == face_count` 且随后
/// `face_count × 3` 个 u16 全部 < vertex_count。验证式扫描——布局猜不中时
/// 用数据自己证明自己在哪（与 jbcf 串表定位同一思路）。
fn locate_indices(
    raw: &[u8],
    lo: usize,
    face_count: u32,
    vertex_count: u32,
) -> Option<usize> {
    let fc = face_count as usize;
    let need = 4 + fc * 3 * 2;
    if face_count == 0 || raw.len() < need {
        return None;
    }
    let hi = raw.len().saturating_sub(need);
    let want = (face_count as u32).to_le_bytes();
    let mut at = lo;
    while at <= hi {
        if raw.get(at..at + 4) == Some(&want[..]) {
            let Some(idx) = raw.get(at + 4..at + need) else {
                at += 4;
                continue;
            };
            let ok = idx
                .chunks_exact(2)
                .all(|c| (u16::from_le_bytes(c.try_into().unwrap()) as u32) < vertex_count);
            if ok {
                return Some(at);
            }
        }
        at += 4;
    }
    None
}

/// 解析 `.mesh` 的几何段。`raw` 是已解密解压的完整文件字节。
pub fn parse_geometry(raw: &[u8]) -> Result<MeshGeometry, String> {
    if raw.len() < 0x118 {
        return Err(format!("文件只有 {} 字节，连几何头（0x118）都不够", raw.len()));
    }
    let vertex_count = u32_at(raw, 0x8C)?;
    let face_count = u32_at(raw, 0x90)?;
    let submesh_count = u32_at(raw, 0x94)?;

    // 合理性闸门：计数离谱说明这不是 mesh 或布局假设错了——宁可报错不可乱解。
    const MAX_VERTS: u32 = 8_000_000;
    const MAX_FACES: u32 = 8_000_000;
    if vertex_count > MAX_VERTS || face_count > MAX_FACES {
        return Err(format!(
            "头部计数不合理（顶点 {vertex_count} / 面 {face_count}），拒绝解析"
        ));
    }
    let vc = vertex_count as usize;
    let fc = face_count as usize;

    let mut at = 0x118;
    let pos_flat = f32_stream(raw, at, vc * 3)?;
    at += vc * 12;
    let pos_end = at;

    // 索引块：静态布局是 法线(vc×12) + UV(vc×8) 后紧跟 [u32 面数]；
    // 蒙皮类模型中间还有未解数据段，猜不中就验证式扫描定位。
    let static_idx = pos_end + vc * 20;
    let idx_at = match u32_at(raw, static_idx) {
        Ok(n) if n == face_count => Some(static_idx),
        _ => locate_indices(raw, pos_end, face_count, vertex_count),
    }
    .ok_or_else(|| format!("找不到与头部面数 {face_count} 自洽的索引块——拒绝解析"))?;
    let middle_bytes = idx_at - pos_end;

    // 法线与 UV 只有在静态布局（中间恰好是 vc×20 字节）时才解；其余情况保持空。
    let (normals, uvs) = if middle_bytes == vc * 20 {
        let nrm_flat = f32_stream(raw, pos_end, vc * 3)?;
        let uv_flat = f32_stream(raw, pos_end + vc * 12, vc * 2)?;
        let normals: Vec<[f32; 3]> =
            nrm_flat.chunks_exact(3).map(|c| [c[0], c[1], c[2]]).collect();
        let uvs: Vec<[f32; 2]> = uv_flat.chunks_exact(2).map(|c| [c[0], c[1]]).collect();
        (normals, uvs)
    } else {
        (Vec::new(), Vec::new())
    };

    // 索引块：[u32 面数][面数 × 3 × u16]。
    let idx_face_count = u32_at(raw, idx_at)?;
    if idx_face_count != face_count {
        return Err(format!(
            "索引块面数 {idx_face_count} 与头部面数 {face_count} 不一致——布局假设不成立，拒绝解析"
        ));
    }
    let ip = idx_at + 4;
    let need = fc * 3 * 2;
    let idx_bytes = raw
        .get(ip..ip + need)
        .ok_or_else(|| format!("索引数据在 {ip:#x} 处截断：需要 {need} 字节"))?;
    let indices: Vec<u16> = idx_bytes
        .chunks_exact(2)
        .map(|c| u16::from_le_bytes(c.try_into().unwrap()))
        .collect();
    let trailing_bytes = raw.len().saturating_sub(ip + need);

    // 索引越界检查：越界就是数据问题，报错不夹断。
    if let Some(&m) = indices.iter().max() {
        if m as u32 >= vertex_count && fc > 0 {
            return Err(format!(
                "索引引用了 {m} 号顶点，但顶点只有 {vertex_count} 个——数据不自洽"
            ));
        }
    }

    let mut bbox_min = [f32::INFINITY; 3];
    let mut bbox_max = [f32::NEG_INFINITY; 3];
    for p in pos_flat.chunks_exact(3) {
        for k in 0..3 {
            bbox_min[k] = bbox_min[k].min(p[k]);
            bbox_max[k] = bbox_max[k].max(p[k]);
        }
    }
    if vertex_count == 0 {
        bbox_min = [0.0; 3];
        bbox_max = [0.0; 3];
    }

    let positions: Vec<[f32; 3]> =
        pos_flat.chunks_exact(3).map(|c| [c[0], c[1], c[2]]).collect();

    Ok(MeshGeometry {
        vertex_count,
        face_count,
        submesh_count,
        positions,
        normals,
        uvs,
        indices,
        bbox_min,
        bbox_max,
        middle_bytes,
        trailing_bytes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 按已验证布局拼一个最小 mesh：4 顶点 / 2 面 / 1 子网格的双三角形平面。
    /// 0x118 头 + 位置 48B + 法线 48B + UV 32B + 索引块 16B = 424B。
    fn synth_plane() -> Vec<u8> {
        let mut v = vec![0u8; 0x118 + 144];
        v[0x40..0x44].copy_from_slice(b"mesh");
        v[0x8C..0x90].copy_from_slice(&4u32.to_le_bytes());
        v[0x90..0x94].copy_from_slice(&2u32.to_le_bytes());
        v[0x94..0x98].copy_from_slice(&1u32.to_le_bytes());
        // 位置：XZ 平面四角
        for (i, p) in [
            [-0.5f32, 0.0, 0.5],
            [0.5, 0.0, 0.5],
            [0.5, 0.0, -0.5],
            [-0.5, 0.0, -0.5],
        ]
        .iter()
        .enumerate()
        {
            let off = 0x118 + i * 12;
            for k in 0..3 {
                v[off + k * 4..off + k * 4 + 4].copy_from_slice(&p[k].to_le_bytes());
            }
        }
        // 法线：四个 (0,1,0)
        for i in 0..4 {
            let off = 0x118 + 48 + i * 12;
            v[off + 4..off + 8].copy_from_slice(&1.0f32.to_le_bytes());
        }
        // UV：(0,0) (1,0) (1,1) (0,1)
        for (i, uv) in [[0.0f32, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
            .iter()
            .enumerate()
        {
            let off = 0x118 + 96 + i * 8;
            v[off..off + 4].copy_from_slice(&uv[0].to_le_bytes());
            v[off + 4..off + 8].copy_from_slice(&uv[1].to_le_bytes());
        }
        // 索引块：[u32 面数][6 × u16]，定点写入 0x118+128 处（缓冲区已含它）。
        let at = 0x118 + 128;
        v[at..at + 4].copy_from_slice(&2u32.to_le_bytes());
        for (i, idx) in [0u16, 1, 2, 2, 3, 0].iter().enumerate() {
            v[at + 4 + i * 2..at + 6 + i * 2].copy_from_slice(&idx.to_le_bytes());
        }
        v
    }

    #[test]
    fn plane_roundtrips() {
        let g = parse_geometry(&synth_plane()).expect("解析成功");
        assert_eq!(g.vertex_count, 4);
        assert_eq!(g.face_count, 2);
        assert_eq!(g.submesh_count, 1);
        assert_eq!(g.positions.len(), 4);
        assert_eq!(g.normals.len(), 4);
        assert_eq!(g.uvs.len(), 4);
        assert_eq!(g.indices, vec![0, 1, 2, 2, 3, 0]);
        assert_eq!(g.trailing_bytes, 0);
        assert_eq!(g.middle_bytes, 80); // 法线 48 + UV 32 = vc×20
        assert_eq!(g.bbox_min, [-0.5, 0.0, -0.5]);
        assert_eq!(g.bbox_max, [0.5, 0.0, 0.5]);
        // 法线全部朝上
        assert!(g.normals.iter().all(|n| (n[1] - 1.0).abs() < 1e-6));
        // UV 覆盖整张 [0,1]² 
        assert_eq!(g.uvs[3], [0.0, 1.0]);
    }

    #[test]
    fn skinned_layout_locates_indices_by_scan() {
        let mut v = synth_plane();
        // 模拟蒙皮布局：UV 流和索引块之间夹一段未解数据。
        // 解析器应验证式扫描找到索引块，法线/UV 如实报缺。
        let junk = vec![0x7fu8; 300];
        let at = 0x118 + 128;
        v.splice(at..at, junk);
        let g = parse_geometry(&v).expect("扫描定位成功");
        assert_eq!(g.indices, vec![0, 1, 2, 2, 3, 0]);
        assert_eq!(g.middle_bytes, 300 + 80);
        assert!(g.normals.is_empty());
        assert!(g.uvs.is_empty());
        assert_eq!(g.bbox_max, [0.5, 0.0, 0.5]);
    }

    #[test]
    fn inconsistent_index_count_is_rejected() {
        let mut v = synth_plane();
        // 把索引块里的面数改成 3，与头部 2 不一致——必须报错，不许硬解。
        // （扫描式定位下，污染后的块不再自洽，报"找不到"或"不一致"都算拒绝。）
        let at = v.len() - 2 * 6 - 4;
        v[at..at + 4].copy_from_slice(&3u32.to_le_bytes());
        let err = parse_geometry(&v).unwrap_err();
        assert!(
            err.contains("不一致") || err.contains("找不到"),
            "实际报错：{err}"
        );
    }

    #[test]
    fn out_of_range_index_is_rejected() {
        let mut v = synth_plane();
        let at = v.len() - 2 * 6;
        // 把第一个索引改成 99，顶点只有 4 个——数据不自洽必须报错。
        v[at..at + 2].copy_from_slice(&99u16.to_le_bytes());
        let err = parse_geometry(&v).unwrap_err();
        assert!(err.contains("不自洽"), "实际报错：{err}");
    }

    #[test]
    fn truncated_file_is_rejected() {
        // 截到位置流中途——必须报错而不是给出半份数据。
        let v = &synth_plane()[..0x120];
        assert!(parse_geometry(v).is_err());
    }
}
