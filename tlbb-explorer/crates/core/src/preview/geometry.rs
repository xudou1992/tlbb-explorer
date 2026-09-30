//! `.mesh` 几何段解析：顶点 / 法线 / UV / 逐子网格索引 / 包围盒。
//!
//! 布局（2026-09-23 全库 7,996 个 .mesh 交叉验证，见下）：
//!
//! ```text
//! 0x00  64B   版权串（信封，见 summary::parse_envelope；部分文件没有）
//! 0x40   8B   类型标签 "mesh"
//! 0x48   4B   版本
//! 0x4C  64B   备注
//! 0x8C   4B   u32 顶点数 vc
//! 0x90   4B   u32 三角面数 fc
//! 0x94   4B   u32 子网格 / 材质槽数 sm（0 按 1 处理）
//! 0x98…0x117  头部剩余（u16@0x114 与中间段布局强相关，语义未证实——只跳过）
//! 0x118       位置流  vc × 3 × f32
//!             中间段    = 12·vc 法线（实测恒为单位向量）
//!                        [+ 8·vc UV] [+ 8·vc 第二套 UV] [+ 2·fc 面级 u16]
//!             p          u32 面数 × sm   ← 连续数组，步长 4 字节，Σ = fc
//!             p + 4·sm   索引  fc × 3 × u16（各子网格按顺序紧挨着排）
//!             …尾部       命名节点表（parent + 名字，可能带 4×4 矩阵；未解，只报字节数）
//! ```
//!
//! 定位办法（不猜布局，让数据自证）：把文件里可能的位置按 4 字节余数分四类，
//! 每类用滑动窗口找第一组「sm 个 u32 求和 == fc 且逐个 ≤ fc，且紧随其后的
//! fc×3 个 u16 全部 < vc」，取四类里最早的那个 p。全库实测：
//! **7,996/7,996 定位成功**；sm=1 的 6,219 个与原「单索引块」实现**位置完全一致**
//! （0 例冲突），并纠正了原实现的 2 例假阳性
//! （`w1351_denglong01.mesh`、`w1351_monster_qinjiazhaijiefei_shoutao_001.mesh`——
//! 它们的 middle 恰好 = 20·vc，旧扫描在蒙皮表里撞上了一个假的 `[u32 fc]`）。
//! 20 个文件有多处命中，全是 vc ≤ 6 的微模型。
//!
//! 纪律：计数与流长度对不上就报错，**绝不猜**。法线 / UV 只在**逐条通过校验**
//! （法线单位长度、UV 有限且在合理区间）时才给出；通不过就是空，不拿脏数据画。

/// 解出的几何体。大模型约 1.8 MB 纯数据（55k 顶点），调用方按需取。
///
/// 字段集是工作台的跨语言契约（`app/src-tauri/src/mesh_view.rs` 按字面量构造），
/// 不要随手增删；要加信息就加到 [`MeshLayout`]。
#[derive(Debug, Clone, PartialEq)]
pub struct MeshGeometry {
    pub vertex_count: u32,
    pub face_count: u32,
    /// 子网格 / 材质槽数（0x94）。引擎侧一个槽 = 一个 `REMesh` = 一次 draw call。
    pub submesh_count: u32,
    pub positions: Vec<[f32; 3]>,
    /// 法线（vc × 3）。中间段开头恒为 12·vc 单位法线流，逐条校验通过才给。
    pub normals: Vec<[f32; 3]>,
    /// 第一套 UV（vc × 2）。需要 middle ≥ 20·vc 且逐条校验通过。
    pub uvs: Vec<[f32; 2]>,
    /// 三角形索引（u16，长度 = 面数 × 3）。各子网格的索引**连续**排在一起，
    /// 切分位置见 [`MeshLayout::face_counts`]。
    pub indices: Vec<u16>,
    pub bbox_min: [f32; 3],
    pub bbox_max: [f32; 3],
    /// 位置流结束到计数数组之间的字节数（= 中间段）。
    pub middle_bytes: usize,
    /// 索引之后剩余未解读的字节数（尾部节点表等，如实报告）。
    pub trailing_bytes: usize,
}

/// [`MeshGeometry`] 加上需要新读出来的信息。不动 `MeshGeometry` 是为了不破工作台。
#[derive(Debug, Clone, PartialEq)]
pub struct MeshLayout {
    pub geometry: MeshGeometry,
    /// 每个子网格的三角面数，长度 = 实际采用的 sm（计数数组读到的那 sm 个 u32）。
    /// 第 i 块的索引从 `3 × Σface_counts[..i]` 开始，长 `face_counts[i] × 3`。
    pub face_counts: Vec<u32>,
    /// 读到几套 UV。只宣称第一套（第二套与切线等其它顶点属性在字节上分不开）。
    pub uv_sets: usize,
    /// 中间段里是否还有一张 2·fc 的面级 u16 表（语义未证实，只报有没有）。
    pub has_face_table: bool,
    /// 中间段里没被 法线/UV/面级表 解释掉的字节数（不猜它是什么）。
    pub middle_leftover: usize,
}

fn u32_at(raw: &[u8], off: usize) -> Result<u32, String> {
    let b = raw
        .get(off..off + 4)
        .ok_or_else(|| format!("文件在 {off:#x} 处截断，读不到 u32"))?;
    Ok(u32::from_le_bytes(b.try_into().unwrap()))
}

fn f32_at(raw: &[u8], off: usize) -> f32 {
    f32::from_le_bytes(raw[off..off + 4].try_into().unwrap())
}

fn u16_at(raw: &[u8], off: usize) -> u16 {
    u16::from_le_bytes(raw[off..off + 2].try_into().unwrap())
}

/// 从 `raw[off..]` 里按 u32 步长读第 k 条。调用方保证不越界。
fn lane(raw: &[u8], off: usize, k: usize) -> u32 {
    u32::from_le_bytes(raw[off + 4 * k..off + 4 * k + 4].try_into().unwrap())
}

/// 索引区是否自洽：`fc × 3` 个 u16 全部 < vc。
fn indices_in_range(raw: &[u8], at: usize, fc: usize, vc: u32) -> bool {
    if at.checked_add(fc * 6).map_or(true, |e| e > raw.len()) {
        return false;
    }
    (0..fc * 3).all(|i| (u16_at(raw, at + i * 2) as u32) < vc)
}

/// 在余数类 `off`（`off % 4 == r`）里找第一个自洽的计数数组位置。
fn first_hit(raw: &[u8], off: usize, sm: usize, fc: usize, vc: u32) -> Option<usize> {
    // 计数数组 + 索引区必须整体落在文件里。
    let lane_end = raw.len().saturating_sub(fc * 6);
    if off >= lane_end || (lane_end - off) / 4 < sm {
        return None;
    }
    let n_lanes = (lane_end - off) / 4;
    let mut sum: u64 = 0;
    for k in 0..sm {
        sum += lane(raw, off, k) as u64;
    }
    for i in 0..=n_lanes - sm {
        if i > 0 {
            sum = sum - lane(raw, off, i - 1) as u64 + lane(raw, off, i + sm - 1) as u64;
        }
        if sum != fc as u64 {
            continue;
        }
        // 命中很稀有，这里直接重扫 sm 条求最大值，不值得为此上一个单调队列。
        let mx = (0..sm).map(|k| lane(raw, off, i + k)).max().unwrap_or(0);
        if mx > fc as u32 {
            continue;
        }
        let p = off + 4 * i;
        if indices_in_range(raw, p + 4 * sm, fc, vc) {
            return Some(p);
        }
    }
    None
}

/// 定位计数数组：四个 4 字节余数类各取最早命中，整体取最早。
/// 与 Python 参考实现（`.scratch/agent_fmt_lib.py`）同一语义、同一取谁的回答。
fn locate_counts(raw: &[u8], vc: u32, fc: usize, sm: usize, pos_end: usize) -> Option<usize> {
    (0..4)
        .filter_map(|r| {
            let off = pos_end + (r as isize - pos_end as isize).rem_euclid(4) as usize;
            first_hit(raw, off, sm, fc, vc)
        })
        .min()
}

/// 读一段 `n` 个 f32；越界返回 None（不 panic 也不夹断）。
fn f32_slice(raw: &[u8], at: usize, n: usize) -> Option<Vec<f32>> {
    if at.checked_add(n * 4)? > raw.len() {
        return None;
    }
    Some((0..n).map(|i| f32_at(raw, at + i * 4)).collect())
}

/// 法线：`vc × 3` f32，要求每条都是单位长度（容差 1%）。通不过就返回空。
fn read_normals(raw: &[u8], at: usize, vc: usize) -> Vec<[f32; 3]> {
    let Some(f) = f32_slice(raw, at, vc * 3) else {
        return Vec::new();
    };
    let mut out = Vec::with_capacity(vc);
    for n in f.chunks_exact(3) {
        let len = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt();
        if !len.is_finite() || (len - 1.0).abs() > 0.01 {
            return Vec::new();
        }
        out.push([n[0], n[1], n[2]]);
    }
    out
}

/// UV：`vc × 2` f32。要求全部有限且落在合理区间（贴图坐标允许平铺越界，但不许是噪声）。
fn read_uvs(raw: &[u8], at: usize, vc: usize) -> Vec<[f32; 2]> {
    const LIMIT: f32 = 4096.0;
    let Some(f) = f32_slice(raw, at, vc * 2) else {
        return Vec::new();
    };
    if !f.iter().all(|v| v.is_finite() && v.abs() <= LIMIT) {
        return Vec::new();
    }
    f.chunks_exact(2).map(|c| [c[0], c[1]]).collect()
}

/// 解析 `.mesh` 的几何段并给出子网格切分。`raw` 是已解密解压的完整文件字节。
pub fn parse_mesh(raw: &[u8]) -> Result<MeshLayout, String> {
    if raw.len() < 0x118 {
        return Err(format!("文件只有 {} 字节，连几何头（0x118）都不够", raw.len()));
    }
    let vertex_count = u32_at(raw, 0x8C)?;
    let face_count = u32_at(raw, 0x90)?;
    let submesh_field = u32_at(raw, 0x94)?;
    // 实测 sm==0 与 sm==1 同源（当作 1 处理）；sm 离谱就不是 mesh。
    let sm = if submesh_field == 0 { 1 } else { submesh_count_of(submesh_field)? } as usize;

    const MAX_VERTS: u32 = 8_000_000;
    const MAX_FACES: u32 = 8_000_000;
    if vertex_count > MAX_VERTS || face_count > MAX_FACES {
        return Err(format!(
            "头部计数不合理（顶点 {vertex_count} / 面 {face_count}），拒绝解析"
        ));
    }
    let vc = vertex_count as usize;
    let fc = face_count as usize;
    if fc == 0 {
        return Err("文件里没有三角面（面数 0）".to_string());
    }

    let mut at = 0x118;
    let pos_flat = f32_slice(raw, at, vc * 3).ok_or_else(|| {
        format!(
            "几何数据在 {at:#x} 处截断：位置流需要 {} 字节，只剩 {}",
            vc * 12,
            raw.len().saturating_sub(at)
        )
    })?;
    at += vc * 12;
    let pos_end = at;

    let idx_at = locate_counts(raw, vertex_count, fc, sm, pos_end).ok_or_else(|| {
        format!(
            "找不到与头部自洽的索引块（子网格 {sm} 个、面数 {face_count}）——布局假设不成立，拒绝解析"
        )
    })?;
    let middle_bytes = idx_at - pos_end;
    let face_counts: Vec<u32> = (0..sm).map(|k| lane(raw, idx_at, k)).collect();
    let mut sum = 0usize;
    for &c in &face_counts {
        sum += c as usize;
    }
    if sum != fc {
        return Err(format!("子网格面数求和 {sum} 与头部面数 {fc} 不一致——数据不自洽"));
    }

    // 中间段按几何 + 内容校验拆解，通不过校验的一律不给。
    // 只宣称第一套 UV：再往后的 8·vc 无法和切线之类的其它顶点属性区分开，
    // 宁可说"没读到"，也不给 glTF 编一个假的 TEXCOORD_1。
    let normals = read_normals(raw, pos_end, vc);
    // 法线没通过校验，整段中间段的布局就都不作数——游标不推进，剩余字节如实报满。
    let mut cursor = pos_end;
    let mut uvs = Vec::new();
    let mut uv_sets = 0usize;
    if !normals.is_empty() {
        cursor += vc * 12;
        if idx_at - cursor >= vc * 8 {
            let read = read_uvs(raw, cursor, vc);
            if vc == 0 || !read.is_empty() {
                uvs = read;
                uv_sets = 1;
                cursor += vc * 8;
            }
        }
    }
    // 实测布局里中间段只可能是 A·vc (+ 2·fc)；剩下恰好等于 2·fc 才认那张面级表。
    let has_face_table = vc > 0 && idx_at - cursor == fc * 2;
    if has_face_table {
        cursor += fc * 2;
    }
    let middle_leftover = idx_at - cursor;

    // 索引区：fc × 3 个 u16，各子网格连续排列。
    let ip = idx_at + 4 * sm;
    let need = fc * 3 * 2;
    if ip + need > raw.len() {
        return Err(format!("索引数据在 {ip:#x} 处截断：需要 {need} 字节"));
    }
    let indices: Vec<u16> = (0..fc * 3).map(|i| u16_at(raw, ip + i * 2)).collect();
    if let Some(&m) = indices.iter().max() {
        if m as u32 >= vertex_count {
            return Err(format!(
                "索引引用了 {m} 号顶点，但顶点只有 {vertex_count} 个——数据不自洽"
            ));
        }
    }
    let trailing_bytes = raw.len() - (ip + need);

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

    let positions: Vec<[f32; 3]> = pos_flat
        .chunks_exact(3)
        .map(|c| [c[0], c[1], c[2]])
        .collect();

    Ok(MeshLayout {
        geometry: MeshGeometry {
            vertex_count,
            face_count,
            submesh_count: submesh_field,
            positions,
            normals,
            uvs,
            indices,
            bbox_min,
            bbox_max,
            middle_bytes,
            trailing_bytes,
        },
        face_counts,
        uv_sets,
        has_face_table,
        middle_leftover,
    })
}

fn submesh_count_of(v: u32) -> Result<u32, String> {
    if v > 64 {
        return Err(format!("子网格数字段读到 {v}，超过 64——不像合法的 mesh 头"));
    }
    Ok(v)
}

/// 旧入口：只要几何本体。字段语义与工作台现有前端一致。
pub fn parse_geometry(raw: &[u8]) -> Result<MeshGeometry, String> {
    parse_mesh(raw).map(|l| l.geometry)
}

/// 从 mesh 尾部把**骨架节点名**捞出来（去重保序）。
///
/// 尾部是「命名节点表」：每个节点一份 96B 记录，里面有名字、一份 4×4 仿射矩阵，
/// 以及看着像父索引的整数。矩阵阵列的相位与父指针的字段位置还没定死（见
/// `.scratch/动画骨架_线索_20260929.md`），所以这里**只报名字**——名字是 NUL 结尾
/// 的 ASCII，读得准；父子关系不猜、不画骨架线，也不报「第 i 个的爸爸是 j」。
///
/// 用途：让人一眼看出「这只模型的骨架在文件里」（`origin` / `top` / `bip01_*`），
/// 以及它和 `.ani` 的骨名表对不对得上。
/// 蒙皮权重**在**这份文件里——是按骨组织的影响顶点表，见 [`SkinInfluence`]；
/// 过去写的「权重不在 .mesh」是按「每顶点 4 影响」那一种编码穷举出来的，判早了。
pub fn node_names(raw: &[u8]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    // 名字段是 NUL 结尾 ASCII；从任何位置扫都行，尾部之外不会有这种串
    //（顶点流是浮点，索引是 u16，撞出连续 3..40 个可打印 ASCII 的概率极低，
    //  而且真撞上了也只是多列一个假节点——不拿它推任何结论）。
    let mut i = 0usize;
    while i < raw.len() {
        let c = raw[i];
        if c.is_ascii_alphabetic() || c == b'_' {
            let mut j = i;
            while j < raw.len() && (raw[j] as char).is_ascii_alphanumeric() || (j < raw.len() && matches!(raw[j], b'_' | b'-' | b'.')) {
                j += 1;
            }
            // 必须以 NUL 收尾才算一个名字段（浮点流里的 ASCII 片段后面跟着的是数据）
            if j > i && j - i >= 3 && j < raw.len() && raw[j] == 0 && j - i <= 40 {
                let s = &raw[i..j];
                let name = String::from_utf8_lossy(s).into_owned();
                if !out.iter().any(|x| x == &name) {
                    out.push(name);
                    if out.len() >= 1024 {
                        return out;
                    }
                }
                i = j + 1;
                continue;
            }
        }
        i += 1;
    }
    out
}

/// 一个骨架节点：名字 + 绑定矩阵（bind pose）+ 它影响哪些顶点。
#[derive(Debug, Clone, PartialEq)]
pub struct Node {
    pub name: String,
    /// 行主序 4×4，引擎的 D3DX 行向量约定：前三行是基向量，第四行 (m[12],m[13],m[14],1)
    /// 是绑定位移 + 齐次 1。识别一条记录的判据是「基向量两两垂直且等比、m[15]=1」。
    pub bind: [f32; 16],
    /// 紧跟在这条记录后面的影响顶点表；根骨（`origin`/`top`/`bip01`/`pelvis`）
    /// 这一段是个 0，读不出表，如实给 `None`。
    pub skin: Option<SkinInfluence>,
}

/// 一根骨影响哪些顶点、权重各多少。
///
/// **这条推翻了过去写在文档与代码里的结论「蒙皮权重不在 .mesh」**：
/// 当时穷举的是「每顶点 4 影响、Σ=1 的定长表」，全库最高命中 0.086（噪声），
/// 于是判成不存在。实际编码是**按骨组织的稀疏表**，紧跟在 96B 节点记录后面：
/// `[u32 顶点数 N][N 个顶点号 u32（严格递增）][N 个权重 f32]`。
/// 样本 `w1351_monster_xiyuqiezei_yifu_001.mesh`（781 顶点）：36 条记录里 26 条带表，
/// 并集覆盖 555 个顶点（71.1%），每个顶点被 1~3 根骨影响，
/// 按骨累加权重后 **441 个顶点的权重和正好 1.0**。
/// 剩下的缺口是那 10 根没有 96B 记录的骨——它们以名字挂在别的记录后面。
#[derive(Debug, Clone, PartialEq)]
pub struct SkinInfluence {
    /// 顶点号，实测严格递增；不递增就不认这张表。
    pub vertices: Vec<u32>,
    /// 与顶点号一一对应的权重，实测全在 0..=1。
    pub weights: Vec<f32>,
}

/// 尾部节点记录的形状：
/// ```text
/// 一条记录 96 字节 = 名字 char[32]（NUL 结尾，剩余填 0）
///                  + 绑定矩阵 f32[16]
/// ```
/// 矩阵是引擎那套 D3DX 行向量约定（引擎是 DX11）：**前三行是基向量，
/// 第四行是 (tx, ty, tz, 1)**——平移在最后一行，不是 (0,0,0,1)。
/// 一开始按「末行恒 0,0,0,1」认记录，只有单位矩阵的骨（origin、top）能过，
/// 真骨骼全被否掉了：46 根骨的怪只认出 2 根。改成允许平移后，同一文件认出 32 根。
/// 父指针**不在记录里**，所以这里只报名字与矩阵，不猜父子关系。
///
/// 另有两种记录混在同一段里，认出来但不当骨架节点：
/// 128 字节的挂点表 = `tx_*` 挂点名 char[32] + 骨名 char[32] + 矩阵 f32[16]
/// （骨名大写，如 `Bip01_Head`），以及只出现名字、后面不带矩阵的子骨名单。
const NODE_RECORD: usize = 96;
/// 头部声明的骨骼根数（46 根骨的怪在这里正好是 46，与它 `.ani` 的轨道数一致）。
const BONE_COUNT_AT: usize = 0x110;

/// 认一条记录：名字段必须可打印且 NUL 填充，基向量必须两两垂直、等比缩放，
/// 末位是齐次 1。任何一条不满足就跳过这个位置——不硬凑。
fn read_node(raw: &[u8], at: usize) -> Option<Node> {
    let name_bytes = raw.get(at..at + 32)?;
    // 名字必须从字段头开始：往前一个字节要是还是名字字符，那就是从长名字中间
    // 切出来的假记录（`bip01_l_finger0` 被读成 `1_l_finger0`，本机真撞到过）
    if at > 0 {
        let prev = raw[at - 1];
        if prev.is_ascii_alphanumeric() || matches!(prev, b'_' | b'-' | b'.') {
            return None;
        }
    }
    let end = name_bytes.iter().position(|&c| c == 0)?;
    if end < 3 || end > 40 {
        return None;
    }
    let nm = &name_bytes[..end];
    if !nm
        .iter()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.'))
    {
        return None;
    }
    // 名字段剩余必须真是填充 0（浮点流里撞出一段可打印 ASCII 后面跟着的不会是 0）
    if name_bytes[end..].iter().any(|&c| c != 0) {
        return None;
    }
    let mb = raw.get(at + 32..at + NODE_RECORD)?;
    let mut m = [0f32; 16];
    for (i, chunk) in mb.chunks_exact(4).enumerate() {
        m[i] = f32::from_le_bytes(chunk.try_into().ok()?);
    }
    if !m.iter().all(|v| v.is_finite() && v.abs() < 1e7) {
        return None;
    }
    // 行向量约定：m[15] 是齐次 1，m[12..15] 是平移（可以有值），前三行是基向量
    if (m[15] - 1.0).abs() > 1e-3 {
        return None;
    }
    let rows: [&[f32]; 3] = [&m[0..3], &m[4..7], &m[8..11]];
    let lens: [f32; 3] = [0, 1, 2].map(|k| rows[k].iter().map(|v| v * v).sum::<f32>().sqrt());
    let mn = lens.iter().fold(f32::INFINITY, |a, &b| a.min(b));
    let mx = lens.iter().fold(0f32, |a, &b| a.max(b));
    if mn <= 1e-6 || mx / mn > 1.05 {
        return None;
    }
    for i in 0..3 {
        for k in i + 1..3 {
            let d: f32 = (0..3).map(|t| rows[i][t] * rows[k][t]).sum();
            if d.abs() / (lens[i] * lens[k]) > 0.03 {
                return None;
            }
        }
    }
    Some(Node {
        name: String::from_utf8_lossy(nm).into_owned(),
        bind: m,
        skin: read_skin(raw, at + NODE_RECORD, vertex_count(raw)),
    })
}

/// 顶点数在头 `0x8C`——影响顶点表里的编号要拿它来卡上界，不然一张
/// 撞出来的浮点噪声也能凑成「递增的小整数」。
fn vertex_count(raw: &[u8]) -> usize {
    raw.get(0x8C..0x90)
        .and_then(|c| <[u8; 4]>::try_from(c).ok())
        .map(u32::from_le_bytes)
        .unwrap_or(0) as usize
}

/// 读紧跟在 96B 记录之后的影响顶点表：`[u32 N][N 个顶点号][N 个权重 f32]`。
/// 四道都不松：N 不得超过顶点数、顶点号必须严格递增且都 < 顶点数、
/// 权重必须全是有限且落在 0..=1、整张表全是 0 权重视为噪声不认。
fn read_skin(raw: &[u8], at: usize, vc: usize) -> Option<SkinInfluence> {
    if vc == 0 {
        return None;
    }
    let n = u32::from_le_bytes(raw.get(at..at + 4)?.try_into().ok()?) as usize;
    if n == 0 || n > vc || n > 65536 {
        return None;
    }
    let idx_end = at + 4 + 4 * n;
    let ib = raw.get(at + 4..idx_end)?;
    let wb = raw.get(idx_end..idx_end + 4 * n)?;
    let mut vertices = Vec::with_capacity(n);
    for c in ib.chunks_exact(4) {
        let v = u32::from_le_bytes(c.try_into().ok()?);
        if v as usize >= vc {
            return None;
        }
        if let Some(&last) = vertices.last() {
            if v <= last {
                return None;
            }
        }
        vertices.push(v);
    }
    let mut weights = Vec::with_capacity(n);
    for c in wb.chunks_exact(4) {
        let w = f32::from_le_bytes(c.try_into().ok()?);
        if !w.is_finite() || w < 0.0 || w > 1.0001 {
            return None;
        }
        weights.push(w);
    }
    if weights.iter().all(|w| *w <= 1e-6) {
        return None;
    }
    Some(SkinInfluence { vertices, weights })
}

/// 头部声明的骨骼根数；文件太短或读不出就不报（不猜）。
pub fn bone_count(raw: &[u8]) -> Option<usize> {
    let b = raw.get(BONE_COUNT_AT..BONE_COUNT_AT + 4)?;
    let n = u32::from_le_bytes(b.try_into().ok()?);
    if n == 0 || n > 4096 {
        return None;
    }
    Some(n as usize)
}

/// 扫出尾部的骨架节点（含绑定矩阵）。按 4 字节步长滑过去，只收「认得出是记录」
/// 的位置，并保证相邻两条至少隔一条记录的长度（不重叠计数）。
pub fn parse_nodes(raw: &[u8]) -> Vec<Node> {
    let mut out = Vec::new();
    let mut i = 0usize;
    while i + NODE_RECORD <= raw.len() {
        if let Some(n) = read_node(raw, i) {
            if !out.iter().any(|x: &Node| x.name == n.name && x.bind == n.bind) {
                out.push(n);
            }
            i += NODE_RECORD;
            continue;
        }
        i += 4;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 按已验证布局拼一个最小 mesh：4 顶点 / 2 面 / 1 子网格的双三角形平面。
    /// 0x118 头 + 位置 48B + 法线 48B + UV 32B + [u32 面数] + 索引 12B = 424B。
    fn synth_plane() -> Vec<u8> {
        let mut v = vec![0u8; 0x118 + 144];
        v[0x40..0x44].copy_from_slice(b"mesh");
        v[0x8C..0x90].copy_from_slice(&4u32.to_le_bytes());
        v[0x90..0x94].copy_from_slice(&2u32.to_le_bytes());
        v[0x94..0x98].copy_from_slice(&1u32.to_le_bytes());
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
        for i in 0..4 {
            let off = 0x118 + 48 + i * 12;
            v[off + 4..off + 8].copy_from_slice(&1.0f32.to_le_bytes());
        }
        for (i, uv) in [[0.0f32, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
            .iter()
            .enumerate()
        {
            let off = 0x118 + 96 + i * 8;
            v[off..off + 4].copy_from_slice(&uv[0].to_le_bytes());
            v[off + 4..off + 8].copy_from_slice(&uv[1].to_le_bytes());
        }
        let at = 0x118 + 128;
        v[at..at + 4].copy_from_slice(&2u32.to_le_bytes());
        for (i, idx) in [0u16, 1, 2, 2, 3, 0].iter().enumerate() {
            v[at + 4 + i * 2..at + 6 + i * 2].copy_from_slice(&idx.to_le_bytes());
        }
        v
    }

    /// 真·多子网格 + 蒙皮布局：法线 [+ 两套 UV] + 面级 u16 表 + sm 个计数 + 连续索引。
    fn synth_skinned_multi(sm: usize, two_uv_sets: bool) -> Vec<u8> {
        let vc = 6usize;
        let counts = vec![2u32; sm];
        let fc: usize = counts.iter().map(|c| *c as usize).sum();
        let uv_bytes = if two_uv_sets { 16 } else { 8 };
        let middle = vc * (12 + uv_bytes) + fc * 2;
        let mut v = vec![0u8; 0x118 + vc * 12 + middle + 4 * sm + fc * 6];
        v[0x40..0x44].copy_from_slice(b"mesh");
        v[0x8C..0x90].copy_from_slice(&(vc as u32).to_le_bytes());
        v[0x90..0x94].copy_from_slice(&(fc as u32).to_le_bytes());
        v[0x94..0x98].copy_from_slice(&(sm as u32).to_le_bytes());
        for i in 0..vc {
            let off = 0x118 + i * 12;
            for k in 0..3 {
                v[off + k * 4..off + k * 4 + 4].copy_from_slice(&((i * k) as f32 * 0.1).to_le_bytes());
            }
            let noff = 0x118 + vc * 12 + i * 12;
            v[noff + 4..noff + 8].copy_from_slice(&1.0f32.to_le_bytes());
            for s in 0..(uv_bytes / 8) {
                let uoff = 0x118 + vc * (12 + 8 * s) + vc * 12 + i * 8;
                v[uoff..uoff + 4].copy_from_slice(&(0.25 * i as f32).to_le_bytes());
                v[uoff + 4..uoff + 8].copy_from_slice(&(0.5 * i as f32).to_le_bytes());
            }
        }
        let face_at = 0x118 + vc * 12 + vc * (12 + uv_bytes);
        for i in 0..fc {
            v[face_at + i * 2..face_at + i * 2 + 2].copy_from_slice(&(i as u16).to_le_bytes());
        }
        let cnt_at = face_at + fc * 2;
        for (i, c) in counts.iter().enumerate() {
            v[cnt_at + i * 4..cnt_at + i * 4 + 4].copy_from_slice(&c.to_le_bytes());
        }
        let idx_at = cnt_at + 4 * sm;
        for i in 0..(fc * 3) {
            let x = (i % vc) as u16;
            v[idx_at + i * 2..idx_at + i * 2 + 2].copy_from_slice(&x.to_le_bytes());
        }
        v
    }

    #[test]
    fn plane_roundtrips() {
        let l = parse_mesh(&synth_plane()).expect("解析成功");
        let g = &l.geometry;
        assert_eq!(g.vertex_count, 4);
        assert_eq!(g.face_count, 2);
        assert_eq!(g.submesh_count, 1);
        assert_eq!(l.face_counts, vec![2]);
        assert_eq!(g.positions.len(), 4);
        assert_eq!(g.normals.len(), 4);
        assert_eq!(l.uv_sets, 1);
        assert_eq!(g.uvs.len(), 4);
        assert_eq!(g.indices, vec![0, 1, 2, 2, 3, 0]);
        assert_eq!(g.trailing_bytes, 0);
        assert_eq!(g.middle_bytes, 80); // 法线 48 + UV 32 = vc×20
        assert_eq!(l.middle_leftover, 0);
        assert!(!l.has_face_table);
        assert_eq!(g.bbox_min, [-0.5, 0.0, -0.5]);
        assert_eq!(g.bbox_max, [0.5, 0.0, 0.5]);
        assert!(g.normals.iter().all(|n| (n[1] - 1.0).abs() < 1e-6));
        assert_eq!(g.uvs[3], [0.0, 1.0]);
    }

    #[test]
    fn multi_submesh_counts_array_is_located_and_split() {
        // A=20·vc + 2·fc：法线 + 一套 UV + 面级表
        let l = parse_mesh(&synth_skinned_multi(3, false)).expect("解析成功");
        assert_eq!(l.face_counts, vec![2, 2, 2]);
        assert_eq!(l.uv_sets, 1);
        assert!(l.has_face_table);
        assert_eq!(l.middle_leftover, 0);
        assert_eq!(l.geometry.normals.len(), 6);
        assert_eq!(l.geometry.uvs.len(), 6);
        // 第 i 块索引起点 = 3 × Σcounts[..i]
        assert_eq!(&l.geometry.indices[6..9], &[0, 1, 2]);
        assert_eq!(&l.geometry.indices[12..15], &[0, 1, 2]);

        // A=28·vc：第二套 UV 与切线之类分不开，只认第一套，其余如实报剩余字节
        let t = parse_mesh(&synth_skinned_multi(2, true)).expect("解析成功");
        assert_eq!(t.uv_sets, 1);
        assert!(!t.has_face_table);
        assert_eq!(t.middle_leftover, 6 * 8 + 4 * 2);
        assert_eq!(t.face_counts, vec![2, 2]);
    }

    /// 真实样本：两个多材质槽网格。旧实现在这两个文件上直接失败。
    ///
    /// **夹具不入库**（客户端原始字节，见 README「测试夹具」）。缺样本就跳过；
    /// 想真跑这条，先用工作台「浏览」视图把同名 `.mesh` 导出到本目录：
    ///
    /// ```text
    /// cargo run --bin tlbb-shell          # 打开工作台 → 浏览 → 找到该 .mesh → 导出
    /// ```
    #[test]
    fn real_multi_submesh_samples() {
        let dir = env!("CARGO_MANIFEST_DIR");
        let pa = format!("{dir}/tests/w1351_model_emiter_lf002.mesh");
        let pb = format!("{dir}/tests/w1351_model_emiter_lf004.mesh");
        let (Ok(a), Ok(b)) = (std::fs::read(&pa), std::fs::read(&pb)) else {
            eprintln!("缺样本 {pa} / {pb}，跳过（夹具不入库，见 README「测试夹具」）");
            return;
        };
        // vc=434 fc=528 sm=2，计数数组在 0x3B78 = (264,264)
        let la = parse_mesh(&a).expect("lf002 应能解析");
        assert_eq!(la.face_counts, vec![264, 264]);
        assert_eq!(la.geometry.vertex_count, 434);
        assert_eq!(la.geometry.normals.len(), 434);
        assert_eq!(la.geometry.indices.len(), 528 * 3);
        // 两块各自覆盖的顶点区间互不重叠、且首尾相接（实测 (0,211) / (212,433)）
        let first = &la.geometry.indices[..264 * 3];
        let second = &la.geometry.indices[264 * 3..];
        assert!(*first.iter().max().unwrap() >= 211);
        assert_eq!(*second.iter().min().unwrap(), 212);

        // vc=436 fc=442 sm=3，计数在 0x3B0C = (402,8,32)
        let lb = parse_mesh(&b).expect("lf004 应能解析");
        assert_eq!(lb.face_counts, vec![402, 8, 32]);
        assert_eq!(lb.geometry.face_count, 442);
    }

    #[test]
    fn missing_normals_leaves_them_empty_not_garbage() {
        // 把法线区改成非单位向量——宁可报缺，不许拿脏数据当法线画。
        let mut v = synth_plane();
        for i in 0..4 {
            let off = 0x118 + 48 + i * 12;
            v[off..off + 12].copy_from_slice(&[0x41u8; 12]);
        }
        let l = parse_mesh(&v).expect("定位不依赖法线，仍应成功");
        assert!(l.geometry.normals.is_empty());
        assert_eq!(l.uv_sets, 0);
        assert_eq!(l.geometry.indices, vec![0, 1, 2, 2, 3, 0]);
    }

    #[test]
    fn inconsistent_index_count_is_rejected() {
        let mut v = synth_plane();
        let at = v.len() - 2 * 6 - 4;
        v[at..at + 4].copy_from_slice(&3u32.to_le_bytes());
        let err = parse_geometry(&v).unwrap_err();
        assert!(err.contains("不一致") || err.contains("找不到"), "实际报错：{err}");
    }

    #[test]
    fn out_of_range_index_is_rejected() {
        let mut v = synth_plane();
        let at = v.len() - 2 * 6;
        v[at..at + 2].copy_from_slice(&99u16.to_le_bytes());
        let err = parse_geometry(&v).unwrap_err();
        assert!(err.contains("不自洽") || err.contains("找不到"), "实际报错：{err}");
    }

    #[test]
    fn truncated_file_is_rejected() {
        let v = &synth_plane()[..0x120];
        assert!(parse_geometry(v).is_err());
    }
}

/// 骨架节点闸门。
///
/// 为什么要这两条：「96 字节 = 名字 + 矩阵」是在一堆浮点里认形状，很容易认错。
/// 判据不能只有自己顺眼——要外部对账：
/// 1. 左右对称。角色骨名有 `bip01_l_*` / `bip01_r_*` 成对，真实骨架必然镜像：
///    两条骨的绑定平移只有**一根轴差个符号**。这条只有世界坐标系的绑定位移才满足，
///    读歪一个字段就断。
/// 2. 头部声明的骨骼数与同组 `.ani` 的轨道数相等——两份不同容器里的数。
#[cfg(test)]
mod node_tests {
    use super::{bone_count, parse_nodes, vertex_count, Node, NODE_RECORD};
    use crate::jpak::Pak;
    use crate::payload;
    use crate::preview::parse_ani;
    use std::path::PathBuf;

    fn raw_of(root: &PathBuf, pak: &str, hash: u64) -> Option<Vec<u8>> {
        let p = Pak::open(root.join(format!("{pak}.pak"))).ok()?;
        let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
        payload::decode(&p, &rec).ok().map(|d| d.bytes)
    }

    /// w1351_monster_xiyuqiezei：yifu_001.mesh 与 walk.ani
    const MESH: u64 = 0xbcd65050a62986b7;
    const ANI: u64 = 0x361180fe30a07e32;
    /// 同一只怪的另一份网格（手套）：节点记录在、影响顶点表不在，用来核「按份报」
    const SHOUTAO: u64 = 0xa56297fce1a4f1c2;

    /// 绑定平移是浮点，建模时左右不完全对等；5e-3 在这批样本上够用（骨长量级 1.0）。
    fn near(a: f32, b: f32) -> bool {
        (a - b).abs() < 5e-3
    }

    /// 找到名字在原文里的位置（名字段固定 32 字节，NUL 补零）。
    fn name_at(raw: &[u8], name: &str) -> usize {
        let mut needle = [0u8; 32];
        needle[..name.len()].copy_from_slice(name.as_bytes());
        raw.windows(32).position(|w| w == needle).expect("名字在原文里")
    }

    /// 把 `bip01_l_xxx` 换成 `bip01_r_xxx`。
    fn mirror(name: &str) -> Option<String> {
        if let Some(rest) = name.strip_prefix("_l_") {
            return Some(format!("_r_{rest}"));
        }
        name.find("_l_").map(|i| format!("{}{}", &name[..i], &name[i..].replace("_l_", "_r_")))
    }

    /// 绑定平移是不是世界坐标里的骨架位姿：靠左右镜像对来判。
    #[test]
    fn bind_translations_mirror_left_and_right() {
        let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let Some(mesh) = raw_of(&root, "data", MESH) else {
            eprintln!("跳过：本机没有 data.pak 或这份资源不在里面");
            return;
        };
        let nodes = parse_nodes(&mesh);
        let declared = bone_count(&mesh).expect("头部该有骨骼数");
        assert!(nodes.len() >= 30, "只认出 {} 条节点记录（声明 {declared} 根骨）", nodes.len());
        let mut pairs = 0;
        for nd in &nodes {
            let Some(m) = mirror(&nd.name) else { continue };
            if !nd.name.contains("_l_") {
                continue;
            }
            let Some(other) = nodes.iter().find(|x| x.name == m) else { continue };
            let mut flipped = 0;
            let mut same = 0;
            for k in 0..3 {
                if near(nd.bind[12 + k], other.bind[12 + k]) {
                    same += 1;
                } else if near(nd.bind[12 + k] + other.bind[12 + k], 0.0) {
                    flipped += 1;
                }
            }
            assert_eq!(flipped, 1, "{} 与 {m} 的绑定平移不是镜像：{:?} vs {:?}", nd.name, &nd.bind[12..15], &other.bind[12..15]);
            assert_eq!(same, 2, "{} 与 {m} 只剩一根轴差符号才对", nd.name);
            pairs += 1;
        }
        assert!(pairs >= 4, "镜像对太少（{pairs}），这条闸门没内容");
        eprintln!("节点记录 {} 条（声明 {declared} 根骨），左右镜像对 {pairs} 对", nodes.len());
    }

    /// 头部 0x110 声明的骨骼数 = 同组动作的轨道数（两份不同容器对账）。
    #[test]
    fn declared_bone_count_equals_the_animation_track_count() {
        let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let (Some(mesh), Some(ani)) = (raw_of(&root, "data", MESH), raw_of(&root, "data", ANI)) else {
            eprintln!("跳过：本机没有 data.pak 或这两份资源不在里面");
            return;
        };
        let declared = bone_count(&mesh).expect("头部该有骨骼数");
        let a = parse_ani(&ani).expect("动作应能解出");
        assert_eq!(declared, a.bones, "mesh 头部声明 {declared} 根骨，动作里 {} 条轨道", a.bones);
    }

    /// 反证：把某条记录的平移改 1 个单位，镜像对就该断——说明闸门真的在看数。
    #[test]
    fn tampering_a_bind_row_breaks_the_mirror() {
        let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let Some(mut mesh) = raw_of(&root, "data", MESH) else {
            eprintln!("跳过：本机没有 data.pak");
            return;
        };
        let nodes = parse_nodes(&mesh);
        let nd = nodes.iter().find(|x| x.name.contains("_l_") && mirror(&x.name).map_or(false, |m| nodes.iter().any(|y| y.name == m))).cloned().expect("该有镜像对");
        let m = mirror(&nd.name).unwrap();
        let at = name_at(&mesh, &nd.name);
        let bumped = nd.bind[12] + 1.0;
        mesh[at + 32 + 12 * 4..at + 32 + 12 * 4 + 4].copy_from_slice(&bumped.to_le_bytes());
        let after = parse_nodes(&mesh);
        let hit = after.iter().find(|x| x.name == nd.name).expect("改动后记录应仍被认出");
        let other = after.iter().find(|x| x.name == m).expect("对侧仍在");
        let still_mirror = (0..3).filter(|k| near(hit.bind[12 + k], other.bind[12 + k])).count();
        assert!(still_mirror < 2, "改了平移却仍然对称，闸门是假的");
    }

    /// 真数据：影响顶点表读得出来，并且**逐顶点把各骨权重加起来应当 ≈1**。
    /// 这条是「权重在文件里」的硬证据——不是看着像浮点就算数。
    #[test]
    fn skin_influences_sum_to_one_per_vertex() {
        let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let Some(mesh) = raw_of(&root, "data", MESH) else {
            eprintln!("跳过：本机没有 data.pak");
            return;
        };
        let vc = vertex_count(&mesh);
        assert!(vc > 0, "头 0x8C 该读出顶点数");
        let nodes = parse_nodes(&mesh);
        let with: Vec<&Node> = nodes.iter().filter(|n| n.skin.is_some()).collect();
        assert!(
            with.len() >= 20,
            "{} 条记录里该有 20 根以上带影响表，实际 {}",
            nodes.len(),
            with.len()
        );
        let mut sum = vec![0f32; vc];
        let mut seen = vec![false; vc];
        let mut covered = 0usize;
        for n in &with {
            let s = n.skin.as_ref().unwrap();
            assert_eq!(s.vertices.len(), s.weights.len(), "顶点号与权重个数该相等");
            for (&v, &w) in s.vertices.iter().zip(s.weights.iter()) {
                if !seen[v as usize] {
                    seen[v as usize] = true;
                    covered += 1;
                }
                sum[v as usize] += w;
            }
        }
        let ones = (0..vc).filter(|&i| seen[i] && (sum[i] - 1.0).abs() < 0.02).count();
        assert!(
            ones * 2 >= covered,
            "覆盖 {covered} 个顶点，权重和≈1 的只有 {ones} 个，撑不起「这是权重」的说法"
        );
        eprintln!(
            "影响顶点表：{} 根骨带表 · 覆盖 {}/{} 顶点 · 权重和≈1 的 {ones} 个",
            with.len(),
            covered,
            vc
        );
    }

    /// 反证一：把一个权重改成 3.0（越界），这张表就该整个不认。
    #[test]
    fn a_weight_out_of_range_kills_the_table() {
        let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let Some(mut mesh) = raw_of(&root, "data", MESH) else {
            eprintln!("跳过：本机没有 data.pak");
            return;
        };
        let nodes = parse_nodes(&mesh);
        let nd = nodes.iter().find(|n| n.skin.as_ref().map_or(false, |s| s.vertices.len() > 4)).expect("该有带表的骨");
        let at = name_at(&mesh, &nd.name);
        let s = nd.skin.as_ref().unwrap();
        // 记录 96B + [u32 N] + N 个顶点号，之后才是权重
        let wbase = at + NODE_RECORD + 4 + 4 * s.vertices.len();
        mesh[wbase..wbase + 4].copy_from_slice(&3.0f32.to_le_bytes());
        let after = parse_nodes(&mesh);
        let hit = after.iter().find(|x| x.name == nd.name).expect("记录本身该还在");
        assert!(hit.skin.is_none(), "权重越界还认成表，说明边界判据是摆设");
    }

    /// 同一只怪的两份网格，影响顶点表的多少**由文件说了算**：衣服带、手套不带。
    /// 这条闸门盯的是「读得出就报数、读不出就报 0」——一旦哪天 `read_skin` 判据
    /// 改坏了，衣服也会掉到 0，这里立刻红。
    #[test]
    fn skin_tables_are_per_part_not_per_model() {
        let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let Some(yifu) = raw_of(&root, "data", MESH) else {
            eprintln!("跳过：本机没有 data.pak");
            return;
        };
        let Some(shoutao) = raw_of(&root, "data", SHOUTAO) else {
            eprintln!("跳过：本机没有 data.pak");
            return;
        };
        let yn = parse_nodes(&yifu);
        let sn = parse_nodes(&shoutao);
        let yk = yn.iter().filter(|n| n.skin.is_some()).count();
        let sk = sn.iter().filter(|n| n.skin.is_some()).count();
        assert!(yk >= 20, "衣服这份实测 {} 根骨带表，掉下 20 就是读表逻辑坏了", yk);
        assert!(yn.len() >= 30 && sn.len() >= 30, "两份都该认得出节点记录：{} / {}", yn.len(), sn.len());
        eprintln!(
            "同一只怪：yifu_001 节点 {} 条 / 带影响表 {} 根 · shoutao_001 节点 {} 条 / 带影响表 {} 根",
            yn.len(),
            yk,
            sn.len(),
            sk
        );
    }

    /// 反证二：把顶点号改成不递增（这张表的形状判据之一），同样不该认。
    #[test]
    fn unsorted_vertex_ids_are_not_a_table() {
        let root = std::env::var("TLBB_ROOT").map(PathBuf::from).unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
        let Some(mut mesh) = raw_of(&root, "data", MESH) else {
            eprintln!("跳过：本机没有 data.pak");
            return;
        };
        let nodes = parse_nodes(&mesh);
        let nd = nodes.iter().find(|n| n.skin.as_ref().map_or(false, |s| s.vertices.len() > 4)).expect("该有带表的骨");
        let at = name_at(&mesh, &nd.name);
        let s = nd.skin.as_ref().unwrap();
        let ibase = at + NODE_RECORD + 4;
        // 把第一个改成比第二个还大
        let second = s.vertices[1];
        mesh[ibase..ibase + 4].copy_from_slice(&(second + 7).to_le_bytes());
        let after = parse_nodes(&mesh);
        let hit = after.iter().find(|x| x.name == nd.name).expect("记录本身该还在");
        assert!(hit.skin.is_none(), "顶点号不递增还认成表，「递增」这条判据是摆设");
    }
}
