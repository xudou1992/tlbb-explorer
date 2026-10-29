//! `.ani` 骨骼动画：信封 + 每条骨每帧的 TRS。
//!
//! 之前只解到信封和骨架名（能看到「有哪些动作」，点不出播放）。数据块口径
//! 在这里钉死。证据不止是手挑样本：工作台那条闸门从库里随机抽 60 份 `.ani`
//! （骨骼数 1~181 都覆盖到），**230,268 个旋转字段全部是单位四元数**，
//! 每份文件的轨道区都正好按「骨骼数 × 帧数 × 32」收口在文件末尾：
//!
//! ```text
//! 0x00  64B   版权串（信封 banner）
//! 0x40  8B    类型标签 "ani"
//! 0x48  u32   版本（样本都是 2）
//! 0x4C  64B   备注（"Upgraded mtl"）
//! 0x8C  4B    块标签 "MIN2"
//! 0x90  …     段内头（本轮只用到下面三个字段，其余原样不猜）
//! 0xBA  u16   骨骼数 = 轨道数
//! 0xBE  u16   与 0xBA 同值（两处各写一遍，用途未证）
//! 0xC2  u16   关键帧数
//! 0xC6  f32   帧率刻度（样本都是 40.0；是「每秒多少 tick」还是「总时长×40」未证）
//! 0xF0  骨名表：每条 30B，NUL 结尾，顺序就是数据块里轨道的顺序
//!       —— 样本里名字比轨道少一条（45 个名字 / 46 条轨道），多出来的那条无名，
//!          按「未命名骨」处理，不编名字，也不因为这个就不认整个动作。
//! 0x126E      轨道数据（4718 = 头部+名字表+中间那段未解的浮点区，同模型不同动作恒等）
//!
//! 轨道数据 := 轨道 × (关键帧数 × 32B)
//!   一条轨道 = 旋转[帧]（f32×4，单位四元数）
//!            + 位移[帧]（f32×3）
//!            + 缩放[帧]（f32，样本恒为 1.0）
//! ```
//!
//! 位移量级在 0.01~0.9（单位是骨骼局部长度，不是世界坐标）。缩放每条恒 1.0，
//! 是「这套动作没有缩放」还是「这个字段另有他用」——照实标未证，不编。
//!
//! 没解出来的：父骨链与绑定位（蒙皮权重也不在 `.mesh`/`.ske` 里）。所以本层
//! 能报「几骨几帧、每骨每帧怎么动」，还不能直接把模型驱动起来。

use crate::preview::Envelope;

/// 一条骨轨道：每帧一个四元数 + 一个位移 + 一个缩放。
#[derive(Debug, Clone, PartialEq)]
pub struct Track {
    /// 骨名（客户端原文，如 `bip01_pelvis`）。
    pub bone: String,
    pub rotations: Vec<[f32; 4]>,
    pub positions: Vec<[f32; 3]>,
    pub scales: Vec<f32>,
}

/// 解出来的动作。
#[derive(Debug, Clone, PartialEq)]
pub struct Anim {
    pub envelope: Envelope,
    pub bones: usize,
    pub frames: usize,
    /// 0xC6 那个 f32（样本恒 40.0）。含义未证，只如实带着。
    pub tick: f32,
    pub tracks: Vec<Track>,
}

fn f32s(raw: &[u8], off: usize, n: usize) -> Option<Vec<f32>> {
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let o = off + i * 4;
        let b: [u8; 4] = raw.get(o..o + 4)?.try_into().ok()?;
        out.push(f32::from_le_bytes(b));
    }
    Some(out)
}

/// `.ani` 头部里**确认过**的字段，不依赖关键帧块版式。
///
/// 为什么单独要这一层：有一族 `.ani`（实测 57 骨 × 50 帧、整份 27,584 字节）按
/// 「骨骼数 × 帧数 × 32B」根本装不下（需要 91,200 字节）⇒ 关键帧块是另一种布局，
/// 解析器只能回 None。头部这几个数仍然是可信的，界面应当把它们报出来，
/// 而不是只写一句「不按已知布局排布」。
#[derive(Debug, Clone, PartialEq)]
pub struct AnimHeader {
    /// 0xBA 的 u32（客户端拿它当「每骨静态记录的条数」）。
    pub bones: usize,
    /// 0xBE 的 u32。客户端**不要求它与 `bones` 相等**（实测 `longgui_b0_idle01` 是 67/65），
    /// 两者之差还写进内部字段 ⇒ 它是另一个计数（可疑是「有轨道的骨数」）。解析失败时
    /// 这个数照样可信，所以单独带出来。
    pub bones2: usize,
    pub frames: usize,
    /// 0xC6 的帧率刻度（样本恒 40.0，用法未证，原样带出）。
    pub tick: f32,
    pub bytes: usize,
}

impl AnimHeader {
    /// 按已知的 32B/帧布局需要多少字节（用来在失败时说明差在哪）。
    pub fn block_need(&self) -> usize {
        self.bones * self.frames * 32
    }
}

/// 只读 `.ani` 头部。信封不是 `ani` 或字段越界 → `None`。
pub fn parse_ani_header(raw: &[u8]) -> Option<AnimHeader> {
    let envelope = crate::preview::parse_envelope(raw)?;
    if envelope.tag != "ani" {
        return None;
    }
    let bones = u16::from_le_bytes(raw.get(0xba..0xbc)?.try_into().ok()?) as usize;
    let bones2 = u16::from_le_bytes(raw.get(0xbe..0xc0)?.try_into().ok()?) as usize;
    let frames = u16::from_le_bytes(raw.get(0xc2..0xc4)?.try_into().ok()?) as usize;
    // 只做「像不像 .ani」的边界检查；两个计数是否相等**不在这里判**——
    // 客户端不要求相等，而 MIN2 的解析器自己要靠它（那条闸门留在 parse_ani 里）。
    if bones == 0 || frames == 0 || bones > 4096 || frames > 8192 {
        return None;
    }
    let tick = f32::from_le_bytes(raw.get(0xc6..0xca)?.try_into().ok()?);
    Some(AnimHeader {
        bones,
        bones2,
        frames,
        tick,
        bytes: raw.len(),
    })
}

/// MIN3 动作的「有什么通道」摘要（结构层，不碰旋转数值）。
///
/// MIN3 与 MIN2 的差别是**每根骨只存真的在动的通道**（见
/// `.scratch/dyn/ani_layout_gap_20261027.md`）：文件里每根骨有一条 u32 标志，
/// bit0=有旋转块、bit1=有位移块、bit2=有缩放块，bit11(0x800)=旋转用 6 字节压缩存法。
/// 布局（逐骨消耗正好到文件尾，全库 2522/2522 份复算）：
/// ```text
/// [名表 0xD2 起 30B×骨数][静态区 44B×骨数][索引表 4B×骨数][每骨标志 4B×骨数2][逐骨数据]
/// ```
/// 标志条数用 0xBE（骨数用 0xBA）；两者不等的族（189/177 这种）名表、静态区、索引表仍按骨数排。
/// 旋转通道的 6 字节压缩存法见 [`decode_compact_quat`]（已解出：三个 15 位分量 + 2 位选择子）。
#[derive(Debug, Clone, PartialEq)]
pub struct Min3Summary {
    pub bones: usize,
    pub frames: usize,
    /// 带位移块（每帧 12 字节 f32）的骨数。
    pub with_positions: usize,
    /// 带缩放块（每帧 4 字节 f32）的骨数。
    pub with_scales: usize,
    /// 带**压缩**旋转块（每帧 6 字节）的骨数。
    pub compressed_rotations: usize,
    /// 带普通旋转块（每帧 16 字节 f32 四元数）的骨数。
    pub plain_rotations: usize,
    pub bytes: usize,
}

/// 骨名表起点：名表本身从 `0xD2` 起，每条 30B、NUL 结尾，条数 == 骨骼数，
/// 第一条实测就是骨架的根（`000` 或 `bip01`——`geometry.rs` 的 `BoneNode` 注释说的就是它）。
const ANI_NAMES_AT: usize = 0xd2;
const ANI_NAME_STRIDE: usize = 30;
/// **轨道与静态记录比名表晚一格**：第 i 条轨道/第 i 条静态记录归的是名表第 i+1 条那根骨。
/// 这不是猜——拿 `.mesh` 存的绑定矩阵当裁判，两种口径各扫一遍（复算：`examples/ani_align_probe.rs`）：
/// - MIN2：晚一格 旋转 931/1119、平移 892/1119（55 个模型）；同名同序只有 16/1119、31/1119。
///   另一批 26 个模型：395/500 对 7/500。
/// - MIN3：晚一格 旋转 **187/199**（两份 189 骨 / 182 骨的真实动作，静态四元数取 +28）；
///   同名同序 7/199。⇒ 两种容器同一套偏移。
/// 所以名表第 0 格（根骨）没有轨道，最后一条轨道落在名表之外——按未命名处理，不给它编名字。
/// 改前按 0xD2 同名同序贴名字，等于每根骨都拿到**前一根骨**的动作，画出来就是骨头乱飘、皮被撕开。
const ANI_TRACK_NAME_AT: usize = 0xf0;
/// 静态区记录起点按「名表末尾 + 16」算，用的就是轨道取名那个基址（与改前 `0xF0 + n×30 + 16` 同式）。
const ANI_MIN2_REST_NAME_AT: usize = ANI_TRACK_NAME_AT;
const MIN3_STATIC_STRIDE: usize = 44;
/// 静态记录里绑定旋转的子偏移（4 个 f32，正好收到记录尾 44）。
/// 全库实测：+28 时 130,114/130,114 条都是单位长；现在被误当 +0 读时只有 761 条。
const MIN3_BIND_QUAT_AT: usize = 28;
/// 同一条记录里**绑定局部平移**在 +4（三个 f32）。
/// 判据同样是 `.mesh` 存的绑定矩阵：189 骨那份 **+4 命中 99/104**、182 骨那份 **88/95**，
/// 而 +0/+8/+12/+16/+20/+24 全 0；命中的骨与旋转 +28 命中的是同一批。
/// 用途：MIN3 只给「真的在动」的骨存位移，没块的骨**不能填零**——
/// 填零等于把这根骨挪到父骨原点上，皮就被撕开。
const MIN3_BIND_POS_AT: usize = 4;

fn u32le(raw: &[u8], o: usize) -> Option<u32> {
    Some(u32::from_le_bytes(raw.get(o..o + 4)?.try_into().ok()?))
}

/// 从 `flags_at` 起按标志逐骨走一遍。返回 `(通道计数, 结束偏移)`；
/// 任何越界/计数不合法 → `None`（宁可不认，也不摆半套）。
fn min3_walk(
    raw: &[u8],
    flags_at: usize,
    flags_n: usize,
    frames: usize,
) -> Option<((usize, usize, usize, usize), usize)> {
    let mut cur = flags_at.checked_add(flags_n.checked_mul(4)?)?;
    if cur > raw.len() {
        return None;
    }
    let (mut with_positions, mut with_scales, mut compressed, mut plain) = (0, 0, 0, 0);
    for i in 0..flags_n {
        let f = u32le(raw, flags_at + i * 4)?;
        if f & 1 != 0 {
            if f & 0x10 != 0 {
                let n = u32le(raw, cur)? as usize;
                if n > frames {
                    return None;
                }
                cur = cur.checked_add(4 + n.checked_mul(if f & 0x800 != 0 { 6 } else { 16 })?)?;
            } else {
                cur = cur.checked_add(frames.checked_mul(if f & 0x800 != 0 { 6 } else { 16 })?)?;
            }
            if f & 0x800 != 0 {
                compressed += 1;
            } else {
                plain += 1;
            }
        }
        if f & 2 != 0 {
            if f & 0x20 != 0 {
                let n = u32le(raw, cur)? as usize;
                if n > frames {
                    return None;
                }
                cur = cur.checked_add(4 + n.checked_mul(12)?)?;
                cur = cur.checked_add(if f & 0x80 != 0 { n.checked_mul(2)? } else { n.checked_mul(4)? })?;
            } else {
                cur = cur.checked_add(frames.checked_mul(12)?)?;
            }
            with_positions += 1;
        }
        if f & 4 != 0 {
            if f & 0x40 != 0 {
                let n = u32le(raw, cur)? as usize;
                if n > frames {
                    return None;
                }
                cur = cur.checked_add(4 + n.checked_mul(4)?)?;
                cur = cur.checked_add(if f & 0x80 != 0 { n } else { n.checked_mul(2)? })?;
            } else {
                cur = cur.checked_add(frames.checked_mul(4)?)?;
            }
            with_scales += 1;
        }
        if cur > raw.len() {
            return None;
        }
    }
    Some(((with_positions, with_scales, compressed, plain), cur))
}

/// 给定标志区起点，按 MIN3 的逐骨存法走一遍，返回**离文件尾还差多少字节**
/// （0 = 正好收在尾；正 = 有字节没算进模型；负 = 模型超了）。
/// 只给普查用：拿它在全库上比不同的「标志区起点」算法，不改解析行为。
pub fn ani_min3_landing(raw: &[u8], flags_at: usize, flags_n: usize, frames: usize) -> Option<i64> {
    let (_, end) = min3_walk(raw, flags_at, flags_n, frames)?;
    Some(raw.len() as i64 - end as i64)
}

/// 标志区起点是闭式：`0xD2 + 78×骨数` = 名表(30B) + 静态区(44B) + 索引表(4B) 各一条骨。
/// 全库 2522/2522 份 MIN3 用它都**正好**收在文件尾（先前那版扫 ≤640 字节的定长块，
/// 块长随骨数线性涨到 700+，骨数多的 121 份就被误判成「结构不成立」）。
/// 闸门没有放松：仍然要求逐骨消耗精确落在文件尾，对不上就不认。
fn min3_flags_at(raw: &[u8], bones: usize, flags_n: usize, frames: usize) -> Option<usize> {
    let at = ANI_NAMES_AT
        .checked_add(bones.checked_mul(ANI_NAME_STRIDE + MIN3_STATIC_STRIDE + 4)?)?;
    if min3_walk(raw, at, flags_n, frames).map(|(_, end)| end) == Some(raw.len()) {
        Some(at)
    } else {
        None
    }
}

/// 只读 MIN3 的结构。标签不是 MIN3、越界、或**逐骨消耗对不上文件尾** → `None`（这份布局不成立就别报数）。
pub fn ani_min3_summary(raw: &[u8]) -> Option<Min3Summary> {
    if raw.get(0x8c..0x90)? != b"MIN3" {
        return None;
    }
    let h = parse_ani_header(raw)?;
    let bones = h.bones;
    let frames = h.frames;
    // 标志区起点靠「唯一精确解」扫出来（定长块在两种容器里不一样：200 / 240）。
    let flags_at = min3_flags_at(raw, bones, h.bones2, frames)?;
    let ((with_positions, with_scales, compressed, plain), end) =
        min3_walk(raw, flags_at, h.bones2, frames)?;
    if end != raw.len() {
        return None;
    }
    Some(Min3Summary {
        bones,
        frames,
        with_positions,
        with_scales,
        compressed_rotations: compressed,
        plain_rotations: plain,
        bytes: raw.len(),
    })
}

/// 6 字节压缩旋转 → 四元数。规则照客户端 `sub_14072F540`（逐条读出来的）：
/// 三个 15 位字段按 `v = field/23170 − 1/√2` 还原（每个都落在 ±0.7071），
/// 第 4 个分量由 `√(1−Σ²)` 补（**取正号**——q 与 −q 是同一个旋转，符号不影响结果）；
/// 「缺的是哪个分量」由第 3 个字的高 2 位选：0→槽0、1→槽1、2→槽2、其余→槽3。
fn decode_compact_quat(b: &[u8]) -> Option<[f32; 4]> {
    if b.len() < 6 {
        return None;
    }
    let w0 = u16::from_le_bytes([b[0], b[1]]);
    let w1 = u16::from_le_bytes([b[2], b[3]]);
    let w2 = u16::from_le_bytes([b[4], b[5]]);
    let f1 = (w0 & 0x7fff) as f32;
    let f2 = (((w0 >> 15) as u32 + 2 * w1 as u32) & 0x7fff) as f32;
    let f3 = (((w2 as u32) << 2) + (w1 >> 14) as u32 & 0x7fff) as f32;
    let sel = (w2 >> 14) as usize & 3;
    const SCALE: f32 = 23170.0;
    const OFF: f32 = std::f32::consts::FRAC_1_SQRT_2;
    let v = [f1 / SCALE - OFF, f2 / SCALE - OFF, f3 / SCALE - OFF];
    let sum = v[0] * v[0] + v[1] * v[1] + v[2] * v[2];
    let last = (1.0 - sum).max(0.0).sqrt();
    let slots: [usize; 3] = match sel {
        0 => [1, 2, 3],
        1 => [0, 2, 3],
        2 => [0, 1, 3],
        _ => [0, 1, 2],
    };
    let mut q = [0.0f32; 4];
    for (k, &s) in slots.iter().enumerate() {
        q[s] = v[k];
    }
    q[sel] = last;
    Some(q)
}

/// 解 MIN3。与 MIN2 的区别只有两处：静态区 44B/骨（不是 60），
/// 且**每根骨按标志只存真的在动的通道**（见 [`ani_min3_summary`] 的布局说明）；
/// 旋转的 6 字节压缩存法由 [`decode_compact_quat`] 还原。
/// 结构对不上文件尾、或某根骨缺旋转块 → `None`（宁可不解，也不摆半套）。
fn parse_ani_min3(raw: &[u8]) -> Option<Anim> {
    let envelope = crate::preview::parse_envelope(raw)?;
    let h = parse_ani_header(raw)?;
    let (bones, frames) = (h.bones, h.frames);
    // 两个计数不等的族（如 longgui 67/65）：标志只有 `bones2` 条。
    // 现按「前 `bones2` 根骨取标志、其余用绑定姿态」解释——**这条对应关系未经客户端验证**，
    // 所以只在这条解释能自洽（唯一精确解 + 逐骨走到文件尾）时采用。
    let flag_n = h.bones2.min(bones);
    let flags_at = min3_flags_at(raw, bones, flag_n, frames)?;
    let mut cur = flags_at.checked_add(flag_n.checked_mul(4)?)?;
    if cur > raw.len() {
        return None;
    }
    // 静态区的绑定旋转：44B/骨、四元数在 +28（全库 130,114/130,114 条单位长）。缺旋转块的骨拿它当常量。
    let static_at = ANI_NAMES_AT + bones * ANI_NAME_STRIDE;
    let name_at = |i: usize| -> String {
        // 名表按**骨下标**排（0xD2 起，30B/骨）；通道块归哪根骨由索引表决定。
        let o = ANI_NAMES_AT + i * ANI_NAME_STRIDE;
        let Some(slot) = raw.get(o..o + ANI_NAME_STRIDE) else {
            return String::new();
        };
        let end = slot.iter().position(|&c| c == 0).unwrap_or(ANI_NAME_STRIDE);
        // 与 MIN2 同一道闸门：只认「字母数字 _ - .」的名字。最后一格轨道落在名表之外，
        // 不做这道检查就会把静态区开头的浮点字节当名字读出来（实测读出过 "\u{5}"）。
        let bytes = &slot[..end];
        let clean = !bytes.is_empty()
            && bytes
                .iter()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.'));
        if clean {
            String::from_utf8_lossy(bytes).into_owned()
        } else {
            String::new()
        }
    };
    // 索引表：`0xD2 + 74×骨数` 起、4B/骨，值是**通道块序号**；`>0xFFFF0000` 是哨兵（该骨没有块）。
    // 客户端采样器就走这张表间接（`v13 = 表[骨]`、`记录 = 基址 + 76×v13`），
    // 非哨兵值恰好是 `0..块数-1` 的严格递增序列 ⇒ 块数 = 0xBE 的计数（实测 189 骨 / 10 哨兵 / 179 块）。
    let idx_at = ANI_NAMES_AT + bones * (ANI_NAME_STRIDE + MIN3_STATIC_STRIDE);
    let mut bone_of_rec = vec![usize::MAX; flag_n];
    let mut sentinels = 0usize;
    for j in 0..bones {
        let v = u32::from_le_bytes(raw.get(idx_at + j * 4..idx_at + j * 4 + 4)?.try_into().ok()?);
        if v > 0xFFFF_0000 {
            sentinels += 1;
        } else if (v as usize) < flag_n {
            bone_of_rec[v as usize] = j;
        } else {
            return None; // 块号越界 ⇒ 布局不成立，宁可不解
        }
    }
    if bone_of_rec.iter().any(|b| *b == usize::MAX) {
        return None; // 有块没有对应骨 ⇒ 与「非哨兵值 = 0..块数-1」矛盾
    }
    let mut slots: Vec<Option<Track>> = vec![None; bones];
    for r in 0..flag_n {
        let f = u32::from_le_bytes(raw.get(flags_at + r * 4..flags_at + r * 4 + 4)?.try_into().ok()?);
        let i = bone_of_rec[r];
        // 旋转：有块就解，没有就整条用绑定旋转（帧数份）。绑定旋转在 44B 记录的 +28。
        let rot = if f & 1 != 0 {
            if f & 0x10 != 0 {
                return None; // 计数前缀的稀疏存法还没实测过，先不解
            }
            let step = if f & 0x800 != 0 { 6 } else { 16 };
            let need = frames.checked_mul(step)?;
            let seg = raw.get(cur..cur + need)?;
            let mut out = Vec::with_capacity(frames);
            for k in 0..frames {
                let o = k * step;
                if step == 6 {
                    out.push(decode_compact_quat(&seg[o..o + 6])?);
                } else {
                    let c = seg.get(o..o + 16)?;
                    let g = |j: usize| f32::from_le_bytes([c[4 * j], c[4 * j + 1], c[4 * j + 2], c[4 * j + 3]]);
                    out.push([g(0), g(1), g(2), g(3)]);
                }
            }
            cur += need;
            out
        } else {
            let so = static_at + i * MIN3_STATIC_STRIDE + MIN3_BIND_QUAT_AT;
            let c = raw.get(so..so + 16)?;
            let g = |j: usize| f32::from_le_bytes([c[4 * j], c[4 * j + 1], c[4 * j + 2], c[4 * j + 3]]);
            vec![[g(0), g(1), g(2), g(3)]; frames]
        };
        // 位移：有块就是每帧 12B f32；没块的骨用静态记录 +4 的绑定局部平移（不是零，见常量注释）。
        let positions = if f & 2 != 0 {
            if f & 0x20 != 0 {
                return None;
            }
            let need = frames.checked_mul(12)?;
            let seg = raw.get(cur..cur + need)?;
            cur += need;
            (0..frames)
                .map(|k| {
                    let o = k * 12;
                    [
                        f32::from_le_bytes([seg[o], seg[o + 1], seg[o + 2], seg[o + 3]]),
                        f32::from_le_bytes([seg[o + 4], seg[o + 5], seg[o + 6], seg[o + 7]]),
                        f32::from_le_bytes([seg[o + 8], seg[o + 9], seg[o + 10], seg[o + 11]]),
                    ]
                })
                .collect()
        } else {
            let so = static_at + i * MIN3_STATIC_STRIDE + MIN3_BIND_POS_AT;
            let bind = (|| -> Option<[f32; 3]> {
                let c = raw.get(so..so + 12)?;
                Some([
                    f32::from_le_bytes([c[0], c[1], c[2], c[3]]),
                    f32::from_le_bytes([c[4], c[5], c[6], c[7]]),
                    f32::from_le_bytes([c[8], c[9], c[10], c[11]]),
                ])
            })().unwrap_or([0.0, 0.0, 0.0]);
            vec![bind; frames]
        };
        // 缩放：有块就是每帧 4B f32，没有就 1.0。
        let scales = if f & 4 != 0 {
            if f & 0x40 != 0 {
                return None;
            }
            let need = frames.checked_mul(4)?;
            let seg = raw.get(cur..cur + need)?;
            cur += need;
            (0..frames)
                .map(|k| f32::from_le_bytes([seg[4 * k], seg[4 * k + 1], seg[4 * k + 2], seg[4 * k + 3]]))
                .collect()
        } else {
            vec![1.0f32; frames]
        };
        if cur > raw.len() {
            return None;
        }
        slots[i] = Some(Track {
            bone: name_at(i),
            rotations: rot,
            positions,
            scales,
        });
    }
    // 哨兵骨（没有通道块）：给空轨道，播放侧按「没轨道」用绑定姿态。
    let tracks: Vec<Track> = (0..bones)
        .map(|j| match slots[j].take() {
            Some(t) => t,
            None => Track {
                bone: name_at(j),
                rotations: Vec::new(),
                positions: Vec::new(),
                scales: Vec::new(),
            },
        })
        .collect();
    // 结构必须正好收在文件尾（与 ani_min3_summary 同一条闸门）。
    if cur != raw.len() {
        return None;
    }
    Some(Anim {
        envelope,
        bones,
        frames,
        tick: h.tick,
        tracks,
    })
}

/// 解 `.ani`。信封不对、字段越界、名字表不规整 → `None`（不硬猜）。
pub fn parse_ani(raw: &[u8]) -> Option<Anim> {
    // MIN3 走它自己的读法（每骨只存动了的通道 + 6 字节压缩旋转）。
    if raw.get(0x8c..0x90) == Some(&b"MIN3"[..]) {
        return parse_ani_min3(raw);
    }
    let envelope = crate::preview::parse_envelope(raw)?;
    let h = parse_ani_header(raw)?;
    // MIN2 的读法要求两个计数相等（实测能解的份都相等）；不相等就不按这套读。
    if h.bones != h.bones2 {
        return None;
    }
    let bones = h.bones;
    let frames = h.frames;
    let tick = h.tick;
    // 名字表：`ANI_NAMES_AT` 起，每条 30B，NUL 结尾，条数 == 骨骼数（见上面的常量注释）。
    // 认不出的槽（全零、或混进非名字字符）按「未命名」处理：bone 留空串、展示层说「未命名骨」，
    // 不因为一条名字脏就整个动作不认，也不给空槽编一个名字。
    let mut names = Vec::with_capacity(bones);
    for i in 0..bones {
        let o = ANI_TRACK_NAME_AT + i * ANI_NAME_STRIDE;
        let Some(slot) = raw.get(o..o + ANI_NAME_STRIDE) else {
            names.push(String::new());
            continue;
        };
        let end = slot.iter().position(|&c| c == 0).unwrap_or(ANI_NAME_STRIDE);
        let bytes = &slot[..end];
        let clean = !bytes.is_empty()
            && bytes
                .iter()
                .all(|c| c.is_ascii_alphanumeric() || matches!(c, b'_' | b'-' | b'.'));
        names.push(if clean {
            String::from_utf8_lossy(bytes).into_owned()
        } else {
            String::new()
        });
    }
    // 数据块紧跟名字表之后；但真实偏移以「文件尾对齐」为准：
    // 轨道区 = bones × frames × 32 字节，必须在文件末尾收口。
    let block = frames * 32;
    let total = bones * block;
    let base = raw.len().checked_sub(total)?;
    if base < ANI_TRACK_NAME_AT + bones * ANI_NAME_STRIDE {
        return None;
    }
    let mut tracks = Vec::with_capacity(bones);
    for (i, name) in names.into_iter().enumerate() {
        let o = base + i * block;
        let rot_flat = f32s(raw, o, frames * 4)?;
        let rotations = rot_flat
            .chunks(4)
            .map(|c| [c[0], c[1], c[2], c[3]])
            .collect::<Vec<_>>();
        let pos_flat = f32s(raw, o + frames * 16, frames * 3)?;
        let positions = pos_flat
            .chunks(3)
            .map(|c| [c[0], c[1], c[2]])
            .collect::<Vec<_>>();
        let scales = f32s(raw, o + frames * 28, frames)?;
        tracks.push(Track { bone: name, rotations, positions, scales });
    }
    Some(Anim { envelope, bones, frames, tick, tracks })
}

/// 四元数是否单位长（容差按浮点执行）。全零四元数是「静止骨」的存法，
/// 也算合法，不当失败。
pub fn is_unit_quat(q: &[f32; 4]) -> bool {
    let n = (q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt();
    n < 1e-6 || (0.98..=1.02).contains(&n)
}

// ------------------------------------------------------------------- 骨架静态区
//
// 骨名表之后、轨道数据之前那段（样本里 1590..4718，共 3128 字节 = 46 × 68）
// 是**骨架静态数据**，不随动作变：同一只怪的 behit/walk/run/idle 四个动作，
// 头部到 4718 逐字节一致，只有 1722..1724 那 3 字节不同。
//
// 已证的部分（四条真样本 × 46 条记录，全部成立）：
// ```text
// 记录起点 = 名字表末尾 + 16（样本 1606），一条 60B，共骨骼数条
//   +0   f32×3  缩放：恒为 0.00992（≈1/100，单位换算的样子，用途未证）
//   +12  f32×4  绑定旋转：184/184 条都是单位四元数
//   +28  f32×3  恒为 0 —— 所以「绑定位移」不在这里
//   +40  f32    恒为 1.0
//   +44  f32    恒为 0
//   +48  f32×3  逐骨不同（样本范围 -1.09..0.55）——是什么未证。
//               曾猜它是「绑定位移」，被同一只怪的 `.mesh` 节点矩阵否掉了：
//               `.mesh` 那边小腿的平移是 1.09，这边是 0.405，量级都对不上
// 记录之后 352 字节：两段 u32，一段 42 个递增（4,5,…,45）、一段 46 个恒为 3，
//                    用途未证（看着像索引表，但不猜它是父骨链）。
// ```
//
// 父骨链 2026-10-05 已解出：在 `.mesh` 尾部的「条目 = [块]* [标志][名字×2][孩子数]
// [孩子…]」结构里，孩子名单给出整棵树（`geometry.rs::parse_hierarchy`，判据与证据见彼处）。
// `.ani` 这边仍只有逐骨局部位姿；播放 = 本层位姿沿父链逐级复合。

/// 一条骨的静态数据（骨架区里的记录）。
#[derive(Debug, Clone, PartialEq)]
pub struct Rest {
    /// 骨名（客户端原文）；名字表比轨道少一条时，多出来的那条为空串。
    pub bone: String,
    /// +0 那三个浮点（样本恒 0.00992，用途未证，原样带着不解释）。
    pub unit: [f32; 3],
    /// +12 绑定旋转（单位四元数）。
    pub rotation: [f32; 4],
    /// +48 那三个浮点，逐骨不同。用途未证（不是绑定位移，见上面注释），
    /// 原样带着，不当结论用。
    /// MIN3 这条记录里没有 +48（整条只有 44B），这里带的是它 **+16 的三个浮点**（同样未证）。
    pub offset: [f32; 3],
    /// **只有 MIN3 有值**：静态记录 +4 的绑定局部平移（三个 f32）。
    /// 判据：拿 `.mesh` 存的绑定局部平移对账，189 骨那份命中 99/104、182 骨那份 88/95，
    /// 其余子偏移（+0/+8/+12/+16/+20/+24）全 0。MIN2 是 `None`——它那条记录里 +28 恒为 0，
    /// 绑定位移不在这个容器里（见上面注释块）。
    pub pos: Option<[f32; 3]>,
}

/// 读骨架静态区：MIN2 绑定旋转在记录 +12、MIN3 在 +28（另带 MIN3 的绑定局部平移 +4）。
/// MIN2 的 +0 / +48 两组浮点原样带出，用途未证。
///
/// 记录区起点 = 名表末尾 + 16（名表 `ANI_NAMES_AT` 起、每条 30B、共 `bones` 条），
/// 一条 60B。判据不合（记录区越过轨道数据、某条旋转不是单位长）→ `None`。
/// MIN3 记录 44B：`+4` 绑定局部平移、`+28` 绑定旋转（全库 130,114/130,114 条单位长）。
pub fn rest_poses(raw: &[u8]) -> Option<Vec<Rest>> {
    let a = parse_ani(raw)?;
    let min3 = raw.get(0x8c..0x90) == Some(&b"MIN3"[..]);
    // MIN2：记录 60B、绑定旋转 +12，区起点 = 名表末尾 + 16。名表条数按「有名轨道数 / 骨骼数」
    //   两个候选试（末条轨道落在名表之外 ⇒ 有名轨道通常比骨骼数少一条，但不是必然，
    //   只挑一个候选会把全名的那批样本挡掉），取整区旋转都单位长的候选。
    // MIN3：记录 44B、绑定旋转 +28、绑定局部平移 +4，区起点紧跟名表；
    //   整区必须落在标志区之前，而标志区起点是闭式 `0xD2 + 78×骨数`（2522/2522 份逐骨复算）。
    // 装载器：两种容器的静态区起点都是 `0xD2 + 30×骨数`，步长 MIN2=60 / MIN3=44。
    // MIN2 旧写法是「基址多算 16、旋转记在 +12」，读的字节其实等于真实记录 **+28**（与 MIN3 同位）；
    // 这里把三处子偏移按**同样的字节**写死，行为一字不变，但不再靠 `named` 去凑基址。
    let (stride, unit_at, quat_at, off_at, pos_at) = if min3 {
        (MIN3_STATIC_STRIDE, 0, MIN3_BIND_QUAT_AT, 16, Some(MIN3_BIND_POS_AT))
    } else {
        (60, 16, 28, 64, None)
    };
    // MIN3 的名表基址就是 0xD2（记录紧跟其后）；MIN2 用轨道取名那个基址 0xF0（晚一格）
    // 静态区基址按装载器写死：`0xD2 + 30×骨数`（MIN2 步长 60、MIN3 步长 44，起点同一个）。
    // 旧写法 `0xF0 + named×30 + 16` 数值等价，但把「有名轨道条数」和「静态区基址」捆在一起，
    // 改名字口径就会连带挪基址（2026-10-28 两次踩到）。
    let names_at = ANI_NAMES_AT;
    let bound = if min3 {
        ANI_NAMES_AT.checked_add(a.bones.checked_mul(ANI_NAME_STRIDE + MIN3_STATIC_STRIDE + 4)?)?
    } else {
        raw.len().checked_sub(a.bones.checked_mul(a.frames)?.checked_mul(32)?)?
    };
    let _named = a.tracks.iter().filter(|t| !t.bone.is_empty()).count();
    let cands: &[usize] = &[a.bones];
    for &_n in cands {
        let Some(base) = names_at.checked_add(a.bones.checked_mul(ANI_NAME_STRIDE)?) else {
            continue;
        };
        if base.checked_add(a.bones.checked_mul(stride)?)? > bound {
            continue;
        }
        let mut out = Vec::with_capacity(a.bones);
        let mut ok = true;
        for i in 0..a.bones {
            let Some(o) = base.checked_add(i.checked_mul(stride)?) else { ok = false; break };
            let Some(rotation) = struct_of::<4>(raw, o.checked_add(quat_at)?) else { ok = false; break };
            if !is_unit_quat(&rotation) {
                ok = false;
                break;
            }
            let Some(unit) = struct_of::<3>(raw, o.checked_add(unit_at)?) else { ok = false; break };
            let Some(offset) = struct_of::<3>(raw, o.checked_add(off_at)?) else {
                ok = false;
                break;
            };
            let pos = match pos_at {
                Some(sub) => struct_of::<3>(raw, o.checked_add(sub)?),
                None => None,
            };
            out.push(Rest { bone: a.tracks[i].bone.clone(), unit, rotation, offset, pos });
        }
        if ok {
            return Some(out);
        }
    }
    None
}

fn struct_of<const N: usize>(raw: &[u8], off: usize) -> Option<[f32; N]> {
    let mut a = [0f32; N];
    for (i, slot) in a.iter_mut().enumerate() {
        let b: [u8; 4] = raw.get(off + i * 4..off + i * 4 + 4)?.try_into().ok()?;
        *slot = f32::from_le_bytes(b);
    }
    Some(a)
}

#[cfg(test)]
mod rest_tests {
    use super::*;

    /// 骨架区的绑定旋转：四份真样本 × 46 条全部单位长，且同模型不同动作
    /// 读出来的静态区逐字节一致（动作不该改骨架）。
    #[test]
    fn 绑定旋转每条都是单位长() {
        let Ok(dir) = std::env::var("TLBB_ANI_DIR") else {
            eprintln!("跳过：没有 TLBB_ANI_DIR 指向的 .ani 样本");
            return;
        };
        let read = |n: &str| std::fs::read(std::path::Path::new(&dir).join(n)).ok();
        let a = match read("w1351_monster_xiyuqiezei_behit01.ani") {
            Some(v) => v,
            None => {
                eprintln!("跳过：样本不在");
                return;
            }
        };
        let rest = rest_poses(&a).expect("骨架区应能解出");
        assert_eq!(rest.len(), 46);
        assert_eq!(rest[0].bone, "bip01");
        assert!(rest.iter().all(|r| is_unit_quat(&r.rotation)));
        // 静态单位值：四份样本都是 0.00992 三元组（不解释它，只钉住「恒等」）
        for r in &rest {
            assert!(r.unit.iter().all(|v| (v - 0.00992).abs() < 5e-4), "单位值恒等破了：{:?}", r.unit);
        }
        // 同一骨架的另一个动作，读出来的骨架区应与这一个完全一致。
        let b = read("w1351_monster_xiyuqiezei_walk.ani").expect("walk 样本应在");
        let rest_b = rest_poses(&b).expect("walk 骨架区应能解出");
        assert_eq!(rest, rest_b, "同模型不同动作的骨架静态数据必须一致");
    }

    /// 布局不合（记录区越界 / 旋转不是单位长）就整份不认。
    #[test]
    fn 骨架区不合就不硬给() {
        assert_eq!(rest_poses(&[]), None);
        let mut raw = vec![0u8; 4096];
        raw[0..10].copy_from_slice(b"Copyright\x00");
        raw[0x40..0x44].copy_from_slice(b"ani\x00");
        raw[0xba..0xbc].copy_from_slice(&2u16.to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&2u16.to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&2u16.to_le_bytes());
        // 轨道区按 2 骨 × 2 帧摆到文件尾，骨架区记录全零 → 旋转零四元数：
        // 零四元数按「静止骨」是合法的，所以这里应该解得出 2 条，而不是报错。
        let got = rest_poses(&raw).expect("全零旋转按静止骨处理，应能解出");
        assert_eq!(got.len(), 2);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 吃 `.ani` 真字节（客户端素材不入库；没有样本就跳过，不算失败）。
    /// 导出方式：`cargo run --offline --example fetch -- <动作名>.ani --out <目录>/<名字>`，
    /// 再把 `TLBB_ANI_DIR` 指到那个目录。
    ///
    /// 这四个动作来自同一只怪：帧数各不相同，正好验到「块长随帧数伸缩」。
    #[test]
    fn 真样本四份都解得出且四元数单位长() {
        let cases = [
            ("w1351_monster_xiyuqiezei_behit01.ani", 21),
            ("w1351_monster_xiyuqiezei_run.ani", 26),
            ("w1351_monster_xiyuqiezei_walk.ani", 31),
            ("w1351_monster_xiyuqiezei_idle01.ani", 41),
        ];
        let mut ran = 0usize;
        for (name, want_frames) in cases {
            let Ok(dir) = std::env::var("TLBB_ANI_DIR") else { continue };
            let Ok(raw) = std::fs::read(std::path::Path::new(&dir).join(name)) else {
                continue;
            };
            ran += 1;
            let a = parse_ani(&raw).unwrap_or_else(|| panic!("{name} 应能解出"));
            assert_eq!(a.frames, want_frames, "{name} 帧数");
            assert_eq!(a.bones, 46, "{name} 骨骼数");
            assert_eq!(a.tracks.len(), 46);
            assert_eq!(a.tick, 40.0, "{name} 帧率刻度");
            assert_eq!(a.tracks[0].bone, "bip01", "{name} 第一条骨名");
            assert!(a.tracks.iter().all(|t| t.rotations.len() == want_frames));
            assert!(a.tracks.iter().all(|t| t.positions.len() == want_frames));
            assert!(a.tracks.iter().all(|t| t.scales.len() == want_frames));
            // 四元数单位长：允许全零（静止骨），不许出现「明显不是四元数」的值。
            let bad = a
                .tracks
                .iter()
                .flat_map(|t| t.rotations.iter())
                .filter(|q| !is_unit_quat(q))
                .count();
            assert_eq!(bad, 0, "{name} 有 {bad} 个四元数不是单位长");
        }
        if ran == 0 {
            eprintln!("跳过：没有 TLBB_ANI_DIR 指向的 .ani 样本（夹具不入库）");
        }
    }

    /// 坏输入必须回 None，不能硬凑出一个动作。
    #[test]
    fn 坏输入不硬猜() {
        assert_eq!(parse_ani(&[]), None);
        // 信封都不对
        assert_eq!(parse_ani(&[0u8; 512]), None);
        let mut raw = vec![0u8; 4096];
        raw[0..10].copy_from_slice(b"Copyright\x00");
        raw[0x40..0x44].copy_from_slice(b"ani\x00");
        // 骨骼数 0 → 不是这份布局
        assert_eq!(parse_ani(&raw), None);
        // 两处骨骼数不一致 → None
        raw[0xba..0xbc].copy_from_slice(&3u16.to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&4u16.to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&2u16.to_le_bytes());
        assert_eq!(parse_ani(&raw), None);
    }
}

#[cfg(test)]
mod header_tests {
    use super::*;

    fn synth(bones: u16, frames: u16, len: usize) -> Vec<u8> {
        let mut raw = vec![0u8; len];
        raw[0..10].copy_from_slice(b"Copyright\x00");
        raw[0x40..0x44].copy_from_slice(b"ani\x00");
        raw[0xba..0xbc].copy_from_slice(&bones.to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&bones.to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&frames.to_le_bytes());
        raw[0xc6..0xca].copy_from_slice(&40.0f32.to_le_bytes());
        raw
    }

    /// 头部能读、但 32B/帧装不下：正是变体宠物与部分 NPC 动作那一族的形状
    /// （实测 57 骨 × 50 帧 = 需 91,200 字节，整份只有 27,584）。
    #[test]
    fn 头部可读但关键帧块装不下也要报得出来() {
        let raw = synth(57, 50, 27_584);
        let h = parse_ani_header(&raw).expect("头部应能读");
        assert_eq!((h.bones, h.frames), (57, 50));
        assert_eq!(h.block_need(), 57 * 50 * 32);
        assert!(h.block_need() > h.bytes, "装不下正是这一族的判据");
        assert_eq!(parse_ani(&raw), None, "关键帧块解不出仍要回 None");
    }

    #[test]
    fn 信封不对就不认_两计数不等只挡解析不挡读头() {
        let mut raw = synth(2, 2, 4096);
        raw[0x40..0x44].copy_from_slice(b"mes\x00");
        assert!(parse_ani_header(&raw).is_none(), "信封不是 ani 就不认");
        // 客户端不要求 0xBA/0xBE 两处计数相等（实测 longgui_b0_idle01 是 67/65），
        // 所以头部读得出来；但 MIN2 那套读法仍要求相等 ⇒ 解析返回 None。
        let mut raw = synth(2, 2, 4096);
        raw[0xbe..0xc0].copy_from_slice(&3u16.to_le_bytes());
        let h = parse_ani_header(&raw).expect("两计数不等也要能读头");
        assert_eq!((h.bones, h.bones2), (2, 3));
        assert!(parse_ani(&raw).is_none(), "MIN2 的读法仍要求两计数相等");
    }

    /// MIN3 结构摘要：合成一份最小 MIN3（1 骨 / 2 帧 / 只有压缩旋转块），
    /// 消耗正好收在文件尾才算「结构成立」；标签不对或长度对不上都回 None。
    #[test]
    fn min3_结构摘要_消耗必须正好收在文件尾() {
        let bones = 2usize;
        let frames = 2usize;
        // 闭式布局：名表 0xD2 起 30B/骨，静态区 44B/骨，索引表 4B/骨，然后才是标志区
        let flags_at = 0xd2 + bones * (30 + 44 + 4);
        let len = flags_at + bones * 4 + frames * 6 * bones;
        let mut raw = vec![0u8; len];
        raw[0..10].copy_from_slice(b"Copyright\x00");
        raw[0x40..0x44].copy_from_slice(b"ani\x00");
        raw[0x8c..0x90].copy_from_slice(b"MIN3");
        raw[0xba..0xbc].copy_from_slice(&(bones as u16).to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&(bones as u16).to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&(frames as u16).to_le_bytes());
        raw[0xc6..0xca].copy_from_slice(&40.0f32.to_le_bytes());
        raw[0xd2..0xd2 + 4].copy_from_slice(b"000\0"); // 名表第 0 格 = 根骨（它没有轨道）
        raw[0xf0..0xf0 + 6].copy_from_slice(b"bip01\0"); // 第 1 格才是第 0 条轨道的骨
        // bit0（有旋转）+ 0x800（压缩存法）⇒ 每帧 6 字节
        for i in 0..bones {
            raw[flags_at + i * 4..flags_at + i * 4 + 4].copy_from_slice(&0x801u32.to_le_bytes());
        }
        // 索引表：骨 → 通道块号。这份合成样本每根骨都有块 ⇒ 恒等映射。
        for j in 0..bones {
            let o = 0xd2 + bones * (30 + 44) + j * 4;
            raw[o..o + 4].copy_from_slice(&(j as u32).to_le_bytes());
        }
        let s = ani_min3_summary(&raw).expect("合成 MIN3 应能读结构");
        assert_eq!((s.bones, s.frames), (2, 2));
        assert_eq!(s.compressed_rotations, 2);
        assert_eq!((s.plain_rotations, s.with_positions, s.with_scales), (0, 0, 0));
        let a = parse_ani(&raw).expect("合成 MIN3 应能解");
        assert_eq!(a.tracks[0].bone, "000", "轨道名按骨下标取名表那一格");
        assert_eq!(a.tracks[1].bone, "bip01");
        // 名字闸门：那一格被非名字字节污染 ⇒ 读成空串，不把浮点字节当名字（真机实测读到过 0x05）。
        raw[0xd2 + 30] = 0x05;
        let dirty = parse_ani(&raw).expect("污染名字不该影响结构");
        assert_eq!(dirty.tracks[1].bone, "");

        // 标签换成 MIN2 → 不认（这条摘要是 MIN3 专用）
        raw[0x8c..0x90].copy_from_slice(b"MIN2");
        assert!(ani_min3_summary(&raw).is_none());
        raw[0x8c..0x90].copy_from_slice(b"MIN3");
        // 多一个字节 → 消耗对不上文件尾 → 不认（宁可说没有，也不报半套结构）
        raw.push(0);
        assert!(ani_min3_summary(&raw).is_none());
    }

    /// MIN3 的骨架静态区也能读了：记录 44B，绑定旋转在 +28、绑定局部平移在 +4。
    /// 这条把两个偏移钉死——写反了这里就会红。
    #[test]
    fn min3_静态区读得出绑定旋转与绑定局部平移() {
        let bones = 2usize;
        let frames = 2usize;
        let flags_at = 0xd2 + bones * (30 + 44 + 4);
        let mut raw = vec![0u8; flags_at + bones * 4 + frames * 6 * bones];
        raw[0..10].copy_from_slice(b"Copyright ");
        raw[0x40..0x44].copy_from_slice(b"ani ");
        raw[0x8c..0x90].copy_from_slice(b"MIN3");
        raw[0xba..0xbc].copy_from_slice(&(bones as u16).to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&(bones as u16).to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&(frames as u16).to_le_bytes());
        raw[0xc6..0xca].copy_from_slice(&40.0f32.to_le_bytes());
        raw[0xd2..0xd2 + 4].copy_from_slice(b"000 ");
        raw[0xf0..0xf0 + 6].copy_from_slice(b"bip01 ");
        for i in 0..bones {
            raw[flags_at + i * 4..flags_at + i * 4 + 4].copy_from_slice(&0x801u32.to_le_bytes());
        }
        // 索引表：骨 → 通道块号。这份合成样本每根骨都有块 ⇒ 恒等映射。
        for j in 0..bones {
            let o = 0xd2 + bones * (30 + 44) + j * 4;
            raw[o..o + 4].copy_from_slice(&(j as u32).to_le_bytes());
        }
        // 第 0 条记录：+4 平移 (1,2,3)、+28 旋转 (0,0,0,1)
        let r0 = 0xd2 + bones * 30;
        for (k, v) in [1.0f32, 2.0, 3.0].iter().enumerate() {
            raw[r0 + 4 + k * 4..r0 + 8 + k * 4].copy_from_slice(&v.to_le_bytes());
        }
        for (k, v) in [0.0f32, 0.0, 0.0, 1.0].iter().enumerate() {
            raw[r0 + 28 + k * 4..r0 + 32 + k * 4].copy_from_slice(&v.to_le_bytes());
        }
        let rests = rest_poses(&raw).expect("MIN3 的静态区应能读");
        assert_eq!(rests.len(), bones);
        assert_eq!(rests[0].pos, Some([1.0, 2.0, 3.0]), "绑定局部平移取的是 +4");
        assert_eq!(rests[0].rotation, [0.0, 0.0, 0.0, 1.0], "绑定旋转取的是 +28");
        assert_eq!(rests[1].pos, Some([0.0, 0.0, 0.0]), "第二条记录没写就是零，不编值");
    }

    /// 6 字节压缩旋转的编解码往返：随便取几个四元数，编码再解码必须回到**同一个旋转**
    /// （允许整体取反，也允许丢的是哪个分量不同）。规则来自客户端 `sub_14072F540`。
    #[test]
    fn 压缩旋转编解码往返() {
        fn encode(q: [f32; 4]) -> [u8; 6] {
            let mut idx = 0usize;
            for k in 1..4 {
                if q[k].abs() > q[idx].abs() {
                    idx = k;
                }
            }
            let s = if q[idx] < 0.0 { -1.0 } else { 1.0 };
            let q = [q[0] * s, q[1] * s, q[2] * s, q[3] * s];
            let vals: Vec<f32> = (0..4).filter(|&k| k != idx).map(|k| q[k]).collect();
            let f = |v: f32| (((v + std::f32::consts::FRAC_1_SQRT_2) * 23170.0).round().clamp(0.0, 32767.0)) as u32;
            let (a, b, c) = (f(vals[0]), f(vals[1]), f(vals[2]));
            let w0 = (a & 0x7fff) as u16 | (((b & 1) as u16) << 15);
            let w1 = ((b >> 1) & 0x3fff) as u16 | (((c & 0x3) as u16) << 14);
            let w2 = ((c >> 2) & 0x1fff) as u16 | ((idx as u16) << 14);
            let mut out = [0u8; 6];
            out[0..2].copy_from_slice(&w0.to_le_bytes());
            out[2..4].copy_from_slice(&w1.to_le_bytes());
            out[4..6].copy_from_slice(&w2.to_le_bytes());
            out
        }
        let cases = [
            [0.7071, 0.0, 0.0, 0.7071f32],
            [0.5, 0.5, 0.5, 0.5],
            [0.0, 0.0, 0.0, 1.0],
            [-0.26, 1.0, -0.001, -0.01],
            [0.183, -0.365, 0.73, 0.55],
        ];
        for q in cases {
            let enc = encode(q);
            let got = decode_compact_quat(&enc).expect("六个字节应能解");
            let n = (got[0] * got[0] + got[1] * got[1] + got[2] * got[2] + got[3] * got[3]).sqrt();
            assert!((n - 1.0).abs() < 1e-4, "解出来不是单位长：{got:?} n={n}");
            let dot: f32 = (0..4).map(|k| q[k] * got[k]).sum();
            assert!(dot.abs() > 0.9999, "往返不是同一个旋转：{q:?} → {got:?} dot={dot}");
        }
    }
}
