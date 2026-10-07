//! `JBPU`（`.pu`）—— 粒子特效定义容器。
//!
//! 与 `BinaryConfigFile` 同一套字符串驻留法：先一张 `(长度, 哈希)` 表，
//! 再是一串紧挨着的字符池，后面跟参数块。
//!
//! ```text
//! 0x00  4B    'JBPU'
//! 0x04  u32   字符串条数
//! 0x08  n×    (u32 长度, u32 哈希)
//! …         字符池（无分隔符，按长度切）
//! …         参数块（记录文法已解；字段名字未解）
//! ```
//!
//! 有意思的是字符串：一个特效会写下它的材质、混合模式、渲染器、发射器形状、
//! 更新器与动态参数名，例如 `w1351_smoke_h005.mtl` / `add` / `Billboard` /
//! `Box` / `dyn_random` / `Colour` / `TextureRotator`。**特效 → 材质 → 贴图**
//! 这条链直接从文件内容里来，不是靠文件名猜的（建库时算 `refs` 用的就是这套
//! 分类，界面上却一直没能看）。
//!
//! 参数块（2026-10-05 解到记录级，见 `.scratch/pu参数块_字段对齐_20261005.md`）：
//!
//! ```text
//! 起点＝align4(字符池尾)，池尾不足 4 字节边界时用 0 补齐
//! 记录＝u32 key（高16=cls 类型，低16=fld 属性号）+ pw(cls,fld) 个 u32 载荷词
//! cls=0 无载荷（fld 本身是值/索引）；cls=1 单浮点；6=二维向量；7=三维向量；
//! 8/9=RGBA 颜色（字节量化 x/255）；10=四维[-1,1]；14=时间+RGBA 控制点；
//! 17=[整数,浮点,整数] 处理器块
//! ```
//!
//! 这套记录文法与 `.sfl`（JBCF）的 `[key][pw 词载荷]` 同构。宽度表由全库
//! 7,806 份反推：**7,806/7,806 从起点确定性零回溯走到精确末尾**。
//! 每条记录的 u32/f32 两种口径都从 [`PuRecord`] 拿得到；fld 的**名字**
//! （哪条是寿命、哪条是速度）仍未解，须 exe 侧属性表才能定。

/// 0x1C..0x1F 在这个容器里是合法的名字分隔符（`point\x1f_03`），
/// 其它控制字节说明读到的是二进制而不是文本。
fn is_name_byte(c: u8) -> bool {
    c >= 0x20 || (9..=13).contains(&c) || (0x1c..=0x1f).contains(&c)
}

fn decode_name(raw: &[u8]) -> String {
    let mapped: Vec<u8> = raw
        .iter()
        .map(|&c| if (0x1c..=0x1f).contains(&c) { b'/' } else { c })
        .collect();
    String::from_utf8_lossy(&mapped).into_owned()
}

/// 参数块记录宽度表:`(cls, fld) -> 载荷 u32 词数`。
///
/// 2026-10-05 全库 7,806 份 `.pu` 反推:记录 = `u32 key`(高 16 位 cls、低 16 位 fld)
/// + `pw(cls,fld)` 个 u32 载荷词,从参数区起点**确定性零回溯**走到精确末尾
/// (7806/7806)。cls=0(裸值)与 cls=7(vec3)是全类统一规则,不占本表;
/// cls=2/3/5/11 等的载荷全是小整数,「N 词载荷」与「N 条裸值记录」字节同形,
/// 本表按走通全库的口径记录。
pub(crate) const PARAM_PW: &[(u16, u16, u8)] = &[
        (1, 1, 1),
        (1, 2, 1),
        (1, 3, 1),
        (1, 10, 1),
        (1, 11, 1),
        (1, 12, 1),
        (1, 13, 1),
        (1, 14, 1),
        (1, 15, 1),
        (1, 17, 1),
        (1, 18, 1),
        (1, 21, 1),
        (1, 27, 1),
        (1, 31, 1),
        (1, 59, 1),
        (1, 60, 1),
        (1, 63, 1),
        (1, 73, 1),
        (1, 74, 1),
        (1, 75, 1),
        (1, 79, 1),
        (1, 80, 1),
        (1, 81, 1),
        (1, 89, 1),
        (1, 90, 1),
        (1, 91, 1),
        (1, 92, 1),
        (1, 94, 1),
        (1, 95, 1),
        (1, 96, 1),
        (1, 97, 1),
        (1, 101, 1),
        (1, 103, 1),
        (1, 105, 1),
        (1, 108, 1),
        (1, 109, 1),
        (1, 111, 1),
        (1, 114, 1),
        (1, 124, 1),
        (1, 128, 1),
        (1, 135, 1),
        (1, 136, 1),
        (1, 138, 1),
        (1, 139, 1),
        (1, 140, 1),
        (1, 141, 1),
        (1, 142, 1),
        (1, 143, 1),
        (1, 150, 1),
        (1, 151, 1),
        (1, 152, 1),
        (1, 153, 1),
        (1, 154, 1),
        (1, 155, 1),
        (1, 158, 1),
        (1, 160, 1),
        (1, 166, 1),
        (1, 179, 1),
        (1, 180, 1),
        (1, 181, 1),
        (1, 182, 1),
        (1, 183, 1),
        (1, 184, 1),
        (1, 195, 1),
        (1, 197, 1),
        (1, 234, 1),
        (1, 235, 1),
        (1, 236, 1),
        (1, 237, 1),
        (1, 240, 0),
        (1, 241, 1),
        (1, 242, 1),
        (1, 243, 1),
        (1, 244, 1),
        (1, 245, 1),
        (1, 246, 1),
        (1, 252, 1),
        (1, 253, 1),
        (1, 254, 1),
        (1, 255, 0),
        (1, 260, 1),
        (1, 261, 1),
        (1, 262, 1),
        (1, 263, 1),
        (1, 268, 1),
        (1, 270, 1),
        (1, 279, 1),
        (1, 280, 1),
        (1, 286, 1),
        (1, 293, 1),
        (1, 294, 1),
        (1, 295, 1),
        (1, 296, 1),
        (1, 307, 1),
        (1, 309, 1),
        (1, 312, 1),
        (1, 314, 1),
        (1, 334, 1),
        (1, 335, 1),
        (1, 336, 1),
        (1, 337, 1),
        (1, 338, 1),
        (1, 340, 1),
        (1, 341, 1),
        (1, 342, 1),
        (1, 344, 0),
        (1, 355, 1),
        (1, 356, 1),
        (1, 357, 1),
        (1, 358, 1),
        (1, 367, 1),
        (1, 375, 1),
        (1, 377, 1),
        (1, 385, 1),
        (1, 386, 1),
        (1, 388, 1),
        (1, 390, 1),
        (1, 401, 1),
        (1, 403, 1),
        (1, 404, 1),
        (1, 405, 1),
        (1, 406, 1),
        (1, 426, 0),
        (1, 428, 1),
        (1, 431, 1),
        (1, 432, 1),
        (1, 433, 1),
        (1, 434, 1),
        (1, 435, 1),
        (1, 437, 1),
        (1, 439, 1),
        (1, 442, 1),
        (1, 443, 1),
        (1, 444, 1),
        (1, 445, 1),
        (1, 446, 1),
        (1, 447, 1),
        (1, 448, 1),
        (1, 450, 1),
        (1, 452, 1),
        (1, 453, 1),
        (1, 470, 1),
        (1, 471, 1),
        (1, 472, 1),
        (1, 473, 1),
        (1, 474, 1),
        (1, 475, 0),
        (1, 476, 0),
        (1, 477, 0),
        (1, 478, 1),
        (1, 479, 1),
        (1, 480, 1),
        (1, 481, 0),
        (1, 482, 1),
        (1, 483, 1),
        (1, 484, 1),
        (2, 7, 0),
        (2, 8, 0),
        (2, 9, 0),
        (2, 32, 0),
        (2, 34, 0),
        (2, 35, 0),
        (2, 49, 0),
        (2, 56, 0),
        (2, 61, 0),
        (2, 85, 0),
        (2, 86, 0),
        (2, 87, 0),
        (2, 93, 0),
        (2, 98, 0),
        (2, 110, 0),
        (2, 113, 0),
        (2, 115, 0),
        (2, 154, 0),
        (2, 155, 0),
        (2, 156, 0),
        (2, 157, 0),
        (2, 158, 0),
        (2, 167, 0),
        (2, 169, 0),
        (2, 197, 0),
        (2, 199, 0),
        (2, 207, 0),
        (2, 208, 0),
        (2, 209, 0),
        (2, 210, 0),
        (2, 304, 0),
        (2, 306, 0),
        (2, 309, 0),
        (2, 311, 0),
        (2, 325, 0),
        (2, 326, 0),
        (2, 327, 0),
        (2, 328, 0),
        (2, 336, 0),
        (2, 338, 0),
        (2, 366, 0),
        (2, 368, 0),
        (2, 402, 0),
        (2, 424, 0),
        (2, 426, 0),
        (2, 427, 0),
        (2, 436, 0),
        (2, 438, 0),
        (2, 449, 0),
        (2, 451, 0),
        (2, 459, 0),
        (2, 461, 0),
        (2, 469, 0),
        (2, 471, 0),
        (2, 473, 0),
        (2, 486, 0),
        (2, 489, 0),
        (2, 499, 0),
        (2, 508, 0),
        (3, 4, 0),
        (3, 21, 0),
        (3, 25, 0),
        (3, 26, 0),
        (3, 67, 0),
        (3, 68, 0),
        (3, 69, 0),
        (3, 70, 0),
        (3, 71, 0),
        (3, 72, 0),
        (3, 76, 0),
        (3, 77, 0),
        (3, 78, 0),
        (3, 117, 0),
        (3, 120, 0),
        (3, 122, 0),
        (3, 144, 0),
        (3, 145, 0),
        (3, 146, 0),
        (3, 147, 0),
        (3, 514, 0),
        (4, 255, 0),
        (4, 256, 0),
        (4, 257, 0),
        (4, 258, 0),
        (5, 29, 0),
        (5, 30, 0),
        (5, 55, 0),
        (5, 62, 0),
        (5, 84, 0),
        (5, 88, 0),
        (5, 99, 0),
        (5, 112, 0),
        (5, 127, 0),
        (5, 157, 0),
        (5, 159, 0),
        (5, 164, 0),
        (5, 168, 0),
        (5, 170, 0),
        (5, 227, 0),
        (5, 229, 0),
        (5, 270, 0),
        (5, 327, 0),
        (5, 328, 0),
        (5, 329, 0),
        (5, 330, 0),
        (5, 498, 0),
        (5, 505, 0),
        (5, 513, 0),
        (6, 178, 2),
        (6, 180, 2),
        (6, 262, 2),
        (6, 263, 2),
        (8, 236, 4),
        (8, 238, 4),
        (8, 267, 4),
        (8, 269, 4),
        (9, 5, 4),
        (9, 6, 4),
        (9, 102, 4),
        (9, 147, 4),
        (9, 148, 4),
        (9, 149, 4),
        (9, 150, 4),
        (9, 151, 4),
        (9, 246, 4),
        (9, 247, 4),
        (9, 248, 4),
        (9, 249, 4),
        (9, 250, 4),
        (10, 130, 4),
        (10, 133, 4),
        (10, 134, 4),
        (11, 160, 0),
        (11, 185, 0),
        (11, 198, 0),
        (11, 200, 0),
        (11, 202, 0),
        (11, 203, 0),
        (11, 204, 0),
        (11, 205, 0),
        (11, 206, 0),
        (11, 228, 0),
        (11, 230, 0),
        (11, 237, 0),
        (11, 239, 0),
        (11, 298, 0),
        (11, 300, 0),
        (11, 318, 0),
        (11, 320, 0),
        (11, 343, 0),
        (11, 357, 0),
        (11, 359, 0),
        (11, 361, 0),
        (11, 363, 0),
        (11, 371, 0),
        (11, 373, 0),
        (11, 377, 0),
        (11, 438, 0),
        (11, 440, 0),
        (11, 458, 0),
        (11, 460, 0),
        (12, 137, 0),
        (13, 159, 0),
        (13, 161, 0),
        (14, 368, 5),
        (14, 370, 5),
        (15, 500, 0),
        (15, 508, 0),
        (17, 496, 3),
        (17, 498, 3),
];

/// 查 (cls,fld) 的载荷词数。cls=0 是裸值(fld 本身就是值),cls=7 是 vec3。
fn param_pw(cls: u16, fld: u16) -> Option<usize> {
    match cls {
        0 => Some(0),
        7 => Some(3),
        _ => PARAM_PW
            .iter()
            .find(|(c, f, _)| *c == cls && *f == fld)
            .map(|(_, _, w)| *w as usize),
    }
}

/// 分类用的词表。用**精确类名**而不是子串：层名里常有 `mesh_canying01`、
/// `Point` 这种，拿子串匹配会把层名念成渲染器类名。
const BLEND: &[&str] = &["add", "alpha", "blend", "multiply", "screen", "none", "subtract"];
const RENDERER: &[&str] = &[
    "billboard",
    "ribbontrail",
    "meshsurface",
    "entity",
    "trail",
    "plane",
    "pointcloud",
    "decal",
    "projector",
];
const EMITTER: &[&str] = &[
    "box", "sphere", "jet", "point", "ring", "cylinder", "circle", "line", "polar", "null",
    "boxedge",
];
const UPDATER: &[&str] = &[
    "rotator", "animator", "affector", "vortex", "force", "gravity", "fade", "scale", "colour",
    "color", "speed",
];

fn has_resource_ext(low: &str) -> bool {
    [".mtl", ".mesh", ".ske", ".ani", ".tga", ".dds", ".png", ".pu"]
        .iter()
        .any(|e| low.ends_with(e))
}

/// 驻留字符串按「在粒子系统里干什么」分桶。
#[derive(Debug, Clone, PartialEq, Default)]
pub struct EffectNames {
    /// 第 0 条：特效自己的名字。
    pub name: String,
    /// 第 1、2 条：分组与层名（客户端原文）。
    pub group: String,
    pub label: String,
    pub materials: Vec<String>,
    pub textures: Vec<String>,
    pub meshes: Vec<String>,
    pub blends: Vec<String>,
    pub renderers: Vec<String>,
    pub emitters: Vec<String>,
    pub updaters: Vec<String>,
    pub dynamics: Vec<String>,
    pub other: Vec<String>,
}

/// 参数块里的一条记录：`key = (cls << 16) | fld`，后跟 `pw(cls,fld)` 个 u32 载荷词。
///
/// cls 是载荷类型（1=单浮点、6=二维向量、7=三维向量、8/9=RGBA 颜色、
/// 14=时间+RGBA 颜色控制点……），fld 是该类型里的属性号。
/// cls=0 没有载荷，fld 本身就是值（索引/小整数）。
#[derive(Debug, Clone, PartialEq)]
pub struct PuRecord {
    pub cls: u16,
    pub fld: u16,
    /// 载荷原始 u32 词；按 f32 口径读用 [`PuRecord::floats`]。
    pub words: Vec<u32>,
}

impl PuRecord {
    /// 同一批词按 f32 解释（小端）。
    pub fn floats(&self) -> Vec<f32> {
        self.words
            .iter()
            .map(|&w| f32::from_le_bytes(w.to_le_bytes()))
            .collect()
    }
}

/// 一个特效文件。
#[derive(Debug, Clone, PartialEq)]
pub struct Effect {
    pub strings: Vec<String>,
    pub names: EffectNames,
    /// 参数块里「像浮点」的数的个数。记录文法已解，字段名字未解，这个数只是旁证。
    pub param_floats: usize,
    /// 参数块字节数（从池尾算起，含对齐补零）。
    pub param_bytes: usize,
    /// 参数区真实起点 = `align4(池尾)`；池尾不足 4 字节边界时用 0 补齐
    /// （全库 7,806 份验证：补齐字节全零，对齐后参数区长必为 4 的倍数）。
    pub param_start: usize,
    /// 参数块记录流（按 `PARAM_PW` 表确定性走出的部分）。
    pub param_records: Vec<PuRecord>,
    /// 记录流是否恰好走到参数区末尾。false = 中途撞到未知键，已走出的记录保留。
    pub param_walk_complete: bool,
}

/// 解 `.pu`。容器不合规（magic / 条数 / 字符池越界 / 名字里有二进制字节）→ `None`。
pub fn parse_pu(raw: &[u8]) -> Option<Effect> {
    if raw.len() < 8 || &raw[..4] != b"JBPU" {
        return None;
    }
    let cnt = u32::from_le_bytes(raw[4..8].try_into().ok()?) as usize;
    if cnt == 0 || cnt >= 4096 || raw.len() < 8 + 8 * cnt {
        return None;
    }
    let mut pairs = Vec::with_capacity(cnt);
    for i in 0..cnt {
        let o = 8 + i * 8;
        let len = u32::from_le_bytes(raw[o..o + 4].try_into().ok()?) as usize;
        let hash = u32::from_le_bytes(raw[o + 4..o + 8].try_into().ok()?);
        pairs.push((len, hash));
    }
    let pool = 8 + 8 * cnt;
    let total: usize = pairs.iter().map(|(l, _)| l).sum();
    if pool + total > raw.len() {
        return None;
    }
    let mut p = pool;
    let mut strings = Vec::with_capacity(cnt);
    for (len, _) in &pairs {
        let s = raw.get(p..p + len)?;
        if s.iter().any(|&c| !is_name_byte(c)) {
            return None;
        }
        strings.push(decode_name(s));
        p += len;
    }
    let blob = &raw[p..];
    let param_floats = blob
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .filter(|v| v.is_finite() && *v != 0.0 && v.abs() > 1e-4 && v.abs() < 1e5)
        .count();
    // 参数区从 align4(池尾) 开始（补零对齐），按记录表确定性走。
    let param_start = (p + 3) & !3;
    let n_words = raw.len().saturating_sub(param_start) / 4;
    let words: Vec<u32> = raw[param_start..param_start + n_words * 4]
        .chunks_exact(4)
        .map(|c| u32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    let mut param_records = Vec::new();
    let mut param_walk_complete = true;
    let mut q = 0usize;
    while q < words.len() {
        let (cls, fld) = ((words[q] >> 16) as u16, (words[q] & 0xffff) as u16);
        let Some(pw) = param_pw(cls, fld) else {
            param_walk_complete = false;
            break;
        };
        if q + 1 + pw > words.len() {
            param_walk_complete = false;
            break;
        }
        param_records.push(PuRecord {
            cls,
            fld,
            words: words[q + 1..q + 1 + pw].to_vec(),
        });
        q += 1 + pw;
    }
    Some(Effect {
        names: classify(&strings),
        param_floats,
        param_bytes: blob.len(),
        param_start,
        param_records,
        param_walk_complete,
        strings,
    })
}

fn classify(strings: &[String]) -> EffectNames {
    let mut out = EffectNames::default();
    for (i, n) in strings.iter().enumerate() {
        let low = n.to_lowercase();
        if has_resource_ext(&low) {
            if low.ends_with(".mtl") {
                out.materials.push(n.clone());
            } else if [".tga", ".dds", ".png"].iter().any(|e| low.ends_with(e)) {
                out.textures.push(n.clone());
            } else {
                out.meshes.push(n.clone());
            }
            continue;
        }
        if low.starts_with("dyn_") {
            out.dynamics.push(n.clone());
        } else if RENDERER.contains(&low.as_str()) {
            out.renderers.push(n.clone());
        } else if EMITTER.contains(&low.as_str()) {
            out.emitters.push(n.clone());
        } else if BLEND.iter().any(|b| low.starts_with(b)) {
            out.blends.push(n.clone());
        } else if UPDATER.iter().any(|u| low.contains(u)) {
            out.updaters.push(n.clone());
        } else if i == 0 {
            out.name = n.clone();
        } else if i == 1 {
            out.group = n.clone();
        } else if i == 2 {
            out.label = n.clone();
        } else {
            out.other.push(n.clone());
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 手搓一份合规容器：验证驻留表、分隔符翻译与分桶。
    #[test]
    fn 合成容器解得开且分桶不误伤层名() {
        let names: Vec<&[u8]> = vec![
            b"w1351_scene_smoke01",
            b"scene",
            b"smoke_01",
            b"w1351_smoke_h005.mtl",
            b"add",
            b"Billboard",
            b"Box",
            b"dyn_random",
            b"TextureRotator",
            b"mesh_canying01",
            b"point\x1c_03",
        ];
        let mut raw: Vec<u8> = vec![];
        raw.extend_from_slice(b"JBPU");
        raw.extend_from_slice(&(names.len() as u32).to_le_bytes());
        for n in &names {
            raw.extend_from_slice(&(n.len() as u32).to_le_bytes());
            raw.extend_from_slice(&123u32.to_le_bytes());
        }
        for n in &names {
            raw.extend_from_slice(n);
        }
        raw.extend_from_slice(&0f32.to_le_bytes());
        raw.extend_from_slice(&1.5f32.to_le_bytes());
        let e = parse_pu(&raw).expect("合成容器应能解");
        assert_eq!(e.names.name, "w1351_scene_smoke01");
        assert_eq!(e.names.group, "scene");
        assert_eq!(e.names.label, "smoke_01");
        assert_eq!(e.names.materials, vec!["w1351_smoke_h005.mtl"]);
        assert_eq!(e.names.renderers, vec!["Billboard"]);
        assert_eq!(e.names.emitters, vec!["Box"]);
        assert_eq!(e.names.blends, vec!["add"]);
        assert_eq!(e.names.dynamics, vec!["dyn_random"]);
        // 层名 mesh_canying01 没有资源扩展名，也不在类名表里 ⇒ 只能落进 other。
        // 它同时验的是「不拿子串装类名」：叫 mesh 开头不等于网格引用。
        assert!(e.names.meshes.is_empty(), "没有 .mesh 后缀的不算网格引用");
        assert!(e.names.other.contains(&"mesh_canying01".to_string()), "层名该老实落在 other");
        assert!(!e.names.renderers.contains(&"mesh_canying01".to_string()));
        assert_eq!(e.names.updaters, vec!["TextureRotator"]);
        // 0x1C 是分隔符，翻成 '/'；参数块里两个浮点
        assert_eq!(e.strings.last().unwrap(), "point/_03");
        assert_eq!(e.param_floats, 1, "0.0 不算「像浮点的数」");
        assert_eq!(e.param_bytes, 8);
    }

    /// 坏输入一律 `None`：magic 不对、条数越界、字符池溢出、名字里是二进制。
    #[test]
    fn 坏输入不硬猜() {
        assert_eq!(parse_pu(&[]), None);
        assert_eq!(parse_pu(&[b'J', b'B', b'P', b'S', 0, 0, 0, 0]), None);
        let mut raw = b"JBPU".to_vec();
        raw.extend_from_slice(&2u32.to_le_bytes());
        raw.extend_from_slice(&4u32.to_le_bytes());
        raw.extend_from_slice(&0u32.to_le_bytes());
        raw.extend_from_slice(&4u32.to_le_bytes());
        raw.extend_from_slice(&0u32.to_le_bytes());
        // 字符池：两条各 4 字节
        raw.extend_from_slice(b"abcd");
        raw.extend_from_slice(b"efgh");
        assert!(parse_pu(&raw).is_some(), "合规容器应能解：{:?}", raw.len());
        // 名字里塞一个控制字节（0x05）→ 那是二进制，不是名字
        raw[24] = 0x05;
        assert_eq!(parse_pu(&raw), None, "名字含控制字节必须整体不认");
    }

    /// 真数据：从容器里取一份 `.pu`，要求解得开、有材质引用、名字是客户端原文。
    #[test]
    fn 真特效解得开且能报出材质() {
        let (root, db) = match (
            std::env::var("TLBB_ROOT").map(std::path::PathBuf::from).ok(),
            std::env::var("TLBB_DB").map(std::path::PathBuf::from).ok(),
        ) {
            (Some(r), Some(d)) => (r, d),
            (Some(r), None) => {
                let r2 = r;
                let d = r2.join(".scratch/resources.db");
                (r2, d)
            }
            _ => {
                eprintln!("跳过：没有 TLBB_ROOT 指向的客户端");
                return;
            }
        };
        if !db.is_file() {
            eprintln!("跳过：没有资源清单");
            return;
        }
        let con = rusqlite::Connection::open_with_flags(
            &db,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("清单打不开");
        // 取前 40 个 .pu，要求至少 9 成套得开（真客户端里参数块形态多，
        // 不假装 100%；一套都开不了才说明这份解析是错的）。
        let rows: Vec<(String, String)> = con
            .prepare("SELECT hash, pak FROM resources WHERE ext='.pu' AND pak IS NOT NULL LIMIT 40")
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
            .unwrap()
            .filter_map(|x| x.ok())
            .collect();
        if rows.is_empty() {
            eprintln!("跳过：清单里没有 .pu");
            return;
        }
        let mut ok = 0usize;
        let mut with_material = 0usize;
        for (hex, pak_name) in &rows {
            let hash = match u64::from_str_radix(hex, 16) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let Ok(pak) = crate::jpak::Pak::open(root.join(format!("{pak_name}.pak"))) else {
                continue;
            };
            let Some(rec) = pak.records().find(|r| r.hash == hash && r.stored > 0) else {
                continue;
            };
            let Ok(dec) = crate::payload::decode(&pak, &rec) else { continue };
            match parse_pu(&dec.bytes) {
                Some(e) => {
                    ok += 1;
                    if !e.names.materials.is_empty() {
                        with_material += 1;
                    }
                    if ok == 1 {
                        println!(
                            "真特效 {hex}：字符串 {} 条 · 材质 {:?} · 渲染器 {:?} · 发射器 {:?}",
                            e.strings.len(),
                            e.names.materials,
                            e.names.renderers,
                            e.names.emitters
                        );
                    }
                }
                None => continue,
            }
        }
        assert!(ok >= rows.len() as usize * 9 / 10, "{ok}/{} 套得开，解析不成立", rows.len());
        assert!(
            with_material > 0,
            "真特效里一个材质引用都没读到，分桶词表八成不对"
        );
    }

    /// 合成参数块：验边界补零、记录切分与 u32/f32 双口径。
    /// 字节取自真样本 fanli_system/shijian_doaffector_fanli.pu 的开头形状：
    /// 头 (50,0,3)、(1,59)=0.01、(7,58)=3×0.01、(5,62)=1、cls=0 裸值。
    #[test]
    fn 参数区按记录表确定性切分且补零对齐() {
        let mut raw: Vec<u8> = vec![];
        let names: Vec<&[u8]> = vec![b"fx", b"g", b"add"];
        raw.extend_from_slice(b"JBPU");
        raw.extend_from_slice(&(names.len() as u32).to_le_bytes());
        for n in &names {
            raw.extend_from_slice(&(n.len() as u32).to_le_bytes());
            raw.extend_from_slice(&123u32.to_le_bytes());
        }
        for n in &names {
            raw.extend_from_slice(n);
        }
        // 池尾 = 8 + 8×3 表 + (2+1+3) 字符 = 38,在 4 字节边界前 2 字节处：
        // 补 2 个 0,参数区从 40 开始。
        assert_eq!(raw.len() % 4, 2, "前置条件：池尾不对齐");
        raw.extend_from_slice(&[0u8, 0]);
        let pool_end = raw.len();
        let words: Vec<u32> = vec![
            50, 0, 3,          // 头
            (1 << 16) | 59,    // cls=1 fld=59
            0x3c23d70a,        //   0.01f32
            (7 << 16) | 58,    // cls=7 fld=58（类硬规则 vec3）
            0x3c23d70a,
            0x3c23d70a,
            0x3c23d70a,
            (5 << 16) | 62,    // cls=5 fld=62
            1,
            (0 << 16) | 66,    // cls=0 裸值 66
            2,
        ];
        for w in &words {
            raw.extend_from_slice(&w.to_le_bytes());
        }
        let e = parse_pu(&raw).expect("合成容器应能解");
        assert!(e.param_walk_complete);
        assert_eq!(e.param_start, pool_end, "补 2 个 0 后参数区从对齐点开始");
        assert_eq!(e.param_start % 4, 0, "参数区起点必须 4 字节对齐");
        assert_eq!(e.param_records.len(), 9, "3 头裸值 + (1,59)+(7,58)+(5,62) + 3 条裸值");
        let r59 = &e.param_records[3];
        assert_eq!((r59.cls, r59.fld), (1, 59));
        assert_eq!(r59.floats(), vec![0.01], "f32 口径");
        assert_eq!(r59.words, vec![0x3c23d70a], "u32 口径");
        let r58 = &e.param_records[4];
        assert_eq!((r58.cls, r58.fld), (7, 58));
        assert_eq!(r58.floats(), vec![0.01, 0.01, 0.01], "cls=7 一律 3 词");
        assert_eq!(e.param_records[8].cls, 0, "cls=0 无载荷(最后的裸值 2)");
        assert!(e.param_records[8].words.is_empty());
    }

    /// 参数区中途撞到未知键：走出的记录保留，walk_complete=false，整体不失败。
    #[test]
    fn 未知键截断记录流但不否定整个文件() {
        let mut raw: Vec<u8> = vec![];
        let names: Vec<&[u8]> = vec![b"fx"];
        raw.extend_from_slice(b"JBPU");
        raw.extend_from_slice(&(names.len() as u32).to_le_bytes());
        for n in &names {
            raw.extend_from_slice(&(n.len() as u32).to_le_bytes());
            raw.extend_from_slice(&123u32.to_le_bytes());
        }
        for n in &names {
            raw.extend_from_slice(n);
        }
        while raw.len() % 4 != 0 {
            raw.push(0);
        }
        let words: Vec<u32> = vec![
            50, 0, 3,
            (1 << 16) | 59,
            0x3c23d70a,
            (99 << 16) | 1, // cls=99 越类，表里没有
            7,
        ];
        for w in &words {
            raw.extend_from_slice(&w.to_le_bytes());
        }
        let e = parse_pu(&raw).expect("容器仍合规");
        assert!(!e.param_walk_complete);
        assert_eq!(e.param_records.len(), 4, "3 条头裸值 + 一条 (1,59)");
        assert_eq!(e.param_records[3].floats(), vec![0.01]);
    }

    /// 真数据：参数块记录流必须从起点恰好走到末尾。
    /// 2026-10-05 全库 7,806/7,806 成立；这里抽前 60 份守住红线。
    #[test]
    fn 真特效参数块记录流走通() {
        let (root, db) = match (
            std::env::var("TLBB_ROOT").map(std::path::PathBuf::from).ok(),
            std::env::var("TLBB_DB").map(std::path::PathBuf::from).ok(),
        ) {
            (Some(r), Some(d)) => (r, d),
            (Some(r), None) => {
                let r2 = r;
                let d = r2.join(".scratch/resources.db");
                (r2, d)
            }
            _ => {
                eprintln!("跳过：没有 TLBB_ROOT 指向的客户端");
                return;
            }
        };
        if !db.is_file() {
            eprintln!("跳过：没有资源清单");
            return;
        }
        let con = rusqlite::Connection::open_with_flags(
            &db,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .expect("清单打不开");
        let rows: Vec<(String, String)> = con
            .prepare("SELECT hash, pak FROM resources WHERE ext='.pu' AND pak IS NOT NULL LIMIT 60")
            .unwrap()
            .query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
            .unwrap()
            .filter_map(|x| x.ok())
            .collect();
        if rows.is_empty() {
            eprintln!("跳过：清单里没有 .pu");
            return;
        }
        let mut ok = 0usize;
        let mut with_colour = 0usize;
        for (hex, pak_name) in &rows {
            let hash = match u64::from_str_radix(hex, 16) {
                Ok(v) => v,
                Err(_) => continue,
            };
            let Ok(pak) = crate::jpak::Pak::open(root.join(format!("{pak_name}.pak"))) else {
                continue;
            };
            let Some(rec) = pak.records().find(|r| r.hash == hash && r.stored > 0) else {
                continue;
            };
            let Ok(dec) = crate::payload::decode(&pak, &rec) else { continue };
            let Some(e) = parse_pu(&dec.bytes) else { continue };
            assert!(
                e.param_walk_complete,
                "{hex}: 参数块记录流没走到末尾，宽度表有缺口"
            );
            ok += 1;
            if e.param_records
                .iter()
                .any(|r| matches!(r.cls, 8 | 9 | 14))
            {
                with_colour += 1;
            }
        }
        assert!(ok > 0, "一份 .pu 都没取到");
        assert!(
            with_colour * 2 > ok,
            "带颜色记录(cls=8/9/14)的特效不足一半({with_colour}/{ok})，颜色类判读可疑"
        );
    }
}
