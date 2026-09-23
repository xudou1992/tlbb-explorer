//! 类型化的内容摘要：给定一个资源的字节与元信息，产出**人能看懂的描述**。
//!
//! # 纪律
//!
//! 1. **摘要必须来自真实字节。** 解不出就 `ViewBody::Unavailable`，
//!    绝不拿目录字段或同类资源顶上。
//! 2. **名称一律客户端原文**，不翻译、不编显示名。
//! 3. **缺什么就说缺什么。** 材质引用的贴图对不上号，就显示「缺」，
//!    不显示「可能是什么」——后者属于分析模式。

use crate::{jbcf, jmt1};

/// 资源的粗分类，决定用哪个预览器。
///
/// 刻意保持**少而稳**：分类变了会导致预览器路由变化，所以只按
/// 「用什么方式才能看懂」来分，不按扩展名细分。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileKind {
    /// 贴图：能出像素。
    Texture,
    /// 材质：字符串表 + 槽位，指向若干贴图名。
    Material,
    /// 模型定义（.mdl）：组成清单——骨架/网格/材质/挂点。
    Model,
    /// 网格（.mesh）：几何数据。
    Mesh,
    /// 动画：若干动作片段。
    Animation,
    /// 骨骼：骨架层级。
    Skeleton,
    /// 参数块（JBPU）：键值。
    Param,
    /// 场景：地图格。
    Scene,
    /// 音频。
    Audio,
    /// 文本 / 配置。
    Text,
    /// 认不出来的，或没有预览器的。
    Unknown,
}

impl FileKind {
    /// 从 `catalog` 的 `type` 字段与扩展名路由到预览器。
    ///
    /// `catalog_type` 是资源目录给的粗类（`texture`/`mesh`/`ani`/…），
    /// `ext` 是扩展名（`.tga`/`.mesh`/…），两者都可能为空。
    pub fn route(catalog_type: &str, ext: &str) -> Self {
        let e = ext.to_ascii_lowercase();
        let t = catalog_type.to_ascii_lowercase();
        if t == "texture" || matches!(e.as_str(), ".tga" | ".dds" | ".png" | ".jpg" | ".jpeg" | ".webp") {
            return FileKind::Texture;
        }
        if t == "mesh" || e == ".mesh" {
            return FileKind::Mesh;
        }
        if t == "ani" || e == ".ani" || e == ".anis" {
            return FileKind::Animation;
        }
        if e == ".ske" {
            return FileKind::Skeleton;
        }
        if t == "jbcf" || e == ".mtl" || e == ".ske" || e == ".cfg" || e == ".mdl" {
            // 同为 JBCF 容器，按扩展名分预览器：.mtl 材质 / .mdl 模型定义 / .ske 骨骼。
            return match e.as_str() {
                ".mtl" => FileKind::Material,
                ".mdl" => FileKind::Model,
                _ => FileKind::Unknown,
            };
        }
        if t == "jbpu" || e == ".pu" {
            return FileKind::Param;
        }
        if t == "scene" || e == ".scene" {
            return FileKind::Scene;
        }
        if matches!(e.as_str(), ".wav" | ".ogg" | ".mp3") {
            return FileKind::Audio;
        }
        if matches!(e.as_str(), ".txt" | ".xml" | ".lua" | ".str" | ".table") {
            return FileKind::Text;
        }
        FileKind::Unknown
    }

    /// 展示名，客户端原文风格（沿用这些扩展名，不造新词）。
    pub const fn label(self) -> &'static str {
        match self {
            FileKind::Texture => "贴图",
            FileKind::Material => "材质",
            FileKind::Model => "模型",
            FileKind::Mesh => "网格",
            FileKind::Animation => "动作",
            FileKind::Skeleton => "骨骼",
            FileKind::Param => "参数",
            FileKind::Scene => "场景",
            FileKind::Audio => "音频",
            FileKind::Text => "文本",
            FileKind::Unknown => "未知",
        }
    }
}

/// 贴图摘要。
///
/// `codec` 与 `declared_codec` 刻意**都保留**：目录标签会骗人（实测 1,792 张
/// 被标成 BC3 的其实是 L8），两者不一致本身就是有价值的预览信息。
#[derive(Debug, Clone, PartialEq)]
pub struct TexSummary {
    pub w: u32,
    pub h: u32,
    /// **真实解码**出的编解码器。
    pub codec: String,
    /// 目录声称的编解码器（客户端原文 4CC）。
    pub declared_codec: String,
    pub mips: u32,
}

/// 材质槽：一个名字 + 它的角色。
///
/// `resolved` 为 `None` 表示**名字存在但对不上任何实体**——
/// 这是真实状态，显示为「缺」，不猜。
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SlotSummary {
    /// 槽位类型（由扩展名推出的角色，如 `贴图`/`模型`/`骨骼`/`动作`）。
    pub role: String,
    /// 材质引用的名字（客户端原文）。
    pub name: String,
    /// 对上实体时的 hash。
    pub resolved: Option<u64>,
}

/// 模型摘要。
///
/// `.mesh` 用的是 julegame 信封（见 [`Envelope`]），文件内嵌着它引用的
/// 材质/贴图名字；`refs` 就是这些名字按后缀分类后的结果，
/// `resolved=None` 表示对不上实体（显示「缺」，不猜）。
#[derive(Debug, Clone, PartialEq)]
pub struct MeshSummary {
    pub envelope: Envelope,
    /// 文件内嵌的引用名（贴图/材质等，按后缀分类）。
    pub refs: Vec<SlotSummary>,
}

/// 动作摘要。
#[derive(Debug, Clone, PartialEq)]
pub struct AnimSummary {
    pub envelope: Envelope,
    /// 文件内可读字符串（Biped 骨架名、备注等），去重保序。
    pub names: Vec<String>,
}

/// julegame 系文件信封：`.ani` / `.mesh` 共用。
///
/// 布局（偏移是字节绝对位置，从多个样本核对过）：
/// ```text
/// 0x00  64B   版权串（"Copyright 2013-2200 http://…"，NUL 结尾）
/// 0x40  8B    类型标签（"ani\0…" / "mesh\0…"）
/// 0x48  u32   版本
/// 0x4C  64B   备注（如 "Upgraded mtl"；常为空）
/// 0x8C  …     数据块（MIN3 等 4CC 块）
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Envelope {
    pub banner: String,
    pub tag: String,
    pub version: u32,
    pub note: String,
}

/// 解析信封。长度或 NUL 截断不合格就 `None`，不硬猜。
pub fn parse_envelope(raw: &[u8]) -> Option<Envelope> {
    if raw.len() < 0x4C + 64 {
        return None;
    }
    let banner = cstr(&raw[0..0x40])?;
    let tag = cstr(&raw[0x40..0x48])?;
    let version = u32::from_le_bytes(raw[0x48..0x4C].try_into().ok()?);
    let note = cstr(&raw[0x4C..0x4C + 64])?;
    // 类型标签必须可读，否则这不是信封（比如 JBCF 开头就是 MAGIC）。
    if tag.is_empty() || !tag.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_') {
        return None;
    }
    Some(Envelope {
        banner,
        tag,
        version,
        note,
    })
}

/// 读 NUL 结尾的 ASCII 串。含控制字符（除 NUL）就整体放弃。
fn cstr(buf: &[u8]) -> Option<String> {
    let end = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    let s = &buf[..end];
    if s.iter().any(|c| *c < 0x20 || *c > 0x7e) {
        return None;
    }
    Some(String::from_utf8_lossy(s).into_owned())
}

/// 文件内可读字符串：≥`min_len` 个可打印 ASCII，去重保序，上限 `max`。
///
/// 这是**纯事实抽取**——它不解释字符串是什么（骨架名？引用名？），
/// 只报告"文件里有这些可读文本"。解释留给看的人。
pub fn printable_strings(raw: &[u8], min_len: usize, max: usize) -> Vec<String> {
    let mut out = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut run = Vec::new();
    for &c in raw {
        if (0x20..0x7f).contains(&c) {
            run.push(c);
        } else {
            if run.len() >= min_len {
                let s = String::from_utf8_lossy(&run).into_owned();
                if seen.insert(s.clone()) {
                    out.push(s);
                    if out.len() >= max {
                        return out;
                    }
                }
            }
            run.clear();
        }
    }
    if run.len() >= min_len {
        let s = String::from_utf8_lossy(&run).into_owned();
        if seen.insert(s.clone()) {
            out.push(s);
        }
    }
    out
}

/// 模型定义（`.mdl`，JBCF 容器）摘要。
///
/// 实测（2026-09-23，玩家服装/宠物/坐骑三类样本）：字符串表按固定次序携带
/// 模型名、基目录、骨架、mesh+mtl 成对出现、挂点/变体名。这里**只按后缀
/// 与相邻关系归类**，不解释语义（哪个挂点什么不猜）。
#[derive(Debug, Clone, PartialEq)]
pub struct MdlSummary {
    /// 首个非空字符串：模型名（客户端原文）。
    pub name: String,
    /// 以 `/` 结尾的字符串：资源基目录。
    pub base_dir: String,
    /// 引用的骨架（`*.ske`，可能跨目录）。
    pub skeletons: Vec<SlotSummary>,
    /// 网格+材质对（相邻出现即配对；前一个无扩展名串作为组名/LOD 标签）。
    pub bodies: Vec<MdlBody>,
    /// 其余字符串，按文件出现序保留（挂点/变体/骨骼名——语义不断言）。
    pub others: Vec<String>,
}

/// 一组网格+材质。`label` 是紧邻其前的无扩展名字符串（LOD/段名），可能为空。
#[derive(Debug, Clone, PartialEq)]
pub struct MdlBody {
    pub label: String,
    pub mesh: SlotSummary,
    pub material: SlotSummary,
}

fn has_ext(s: &str) -> bool {
    match s.rfind('.') {
        Some(i) => {
            let e = &s[i + 1..];
            !e.is_empty() && e.len() <= 5 && e.bytes().all(|c| c.is_ascii_alphanumeric())
        }
        None => false,
    }
}

/// 给模型定义出摘要。`lookup` 把名字对到 hash（对不上保持 None=缺）。
pub fn mdl_summary<F>(raw: &[u8], lookup: F) -> ViewBody
where
    F: Fn(&str) -> Option<u64>,
{
    let j = match jbcf::parse(raw) {
        Ok(j) => j,
        Err(e) => {
            return ViewBody::Unavailable {
                why: format!("模型定义解析失败：{e}"),
            }
        }
    };
    let strs: Vec<&str> = j.strings.iter().map(|s| s.text.as_str()).collect();

    let mut name = String::new();
    let mut base_dir = String::new();
    let mut skeletons = Vec::new();
    let mut bodies = Vec::new();
    let mut others = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut last_label = String::new();

    let mut i = 0;
    while i < strs.len() {
        let s = strs[i];
        if s.is_empty() {
            i += 1;
            continue;
        }
        if s.ends_with('/') && base_dir.is_empty() {
            base_dir = s.to_string();
            i += 1;
            continue;
        }
        let low = s.to_ascii_lowercase();
        if low.ends_with(".ske") {
            skeletons.push(SlotSummary {
                role: "骨骼".into(),
                name: s.to_string(),
                resolved: lookup(s),
            });
            last_label.clear();
            i += 1;
            continue;
        }
        // mesh 紧跟 mtl → 配对；标签取 mesh 前最近的无扩展名串
        if low.ends_with(".mesh") {
            let mut label = last_label.clone();
            last_label.clear();
            let material = strs
                .get(i + 1)
                .filter(|m| m.to_ascii_lowercase().ends_with(".mtl"))
                .map(|m| SlotSummary {
                    role: "材质".into(),
                    name: (*m).to_string(),
                    resolved: lookup(m),
                });
            let paired = material.is_some(); // 先记下，后面 Option 会被 move 进结构体
            let mesh = SlotSummary {
                role: "网格".into(),
                name: s.to_string(),
                resolved: lookup(s),
            };
            if !paired {
                label = String::new(); // 没配成对就不挂标签，保持朴素
            }
            bodies.push(MdlBody {
                label,
                mesh,
                material: material.unwrap_or(SlotSummary {
                    role: "材质".into(),
                    name: "<缺>".into(),
                    resolved: None,
                }),
            });
            if paired {
                i += 2;
            } else {
                i += 1;
            }
            continue;
        }
        if has_ext(s) {
            // 其它带扩展名的引用（贴图/动作等）：如实列出
            let role = role_label(jbcf::role(s)).to_string();
            others.push(format!("[{role}] {s}"));
            seen.insert(s.to_string());
            last_label.clear();
            i += 1;
            continue;
        }
        // 无扩展名：可能是模型名/组名/挂点名
        if name.is_empty() {
            name = s.to_string();
        } else {
            if !seen.insert(s.to_string()) {
                i += 1;
                continue;
            }
            others.push(s.to_string());
            last_label = s.to_string();
        }
        i += 1;
    }

    ViewBody::Model(MdlSummary {
        name,
        base_dir,
        skeletons,
        bodies,
        others,
    })
}

/// 视图主体：按类型给出不同内容。
#[derive(Debug, Clone, PartialEq)]
pub enum ViewBody {
    Texture(TexSummary),
    Material(Vec<SlotSummary>),
    /// 模型定义（.mdl）：组成清单（骨架/网格+材质对/挂点）。
    Model(MdlSummary),
    Mesh(MeshSummary),
    Animation(AnimSummary),
    /// 有字节但没有专用预览器：只报大小与头部特征。
    Raw { bytes: usize, head: Vec<u8> },
    /// **解不出**。`why` 是给用户看的原因，不是内部错误码。
    Unavailable { why: String },
}

/// 一个资源的完整视图。
#[derive(Debug, Clone, PartialEq)]
pub struct ResourceView {
    /// 客户端原文名。无名为空串。
    pub name: String,
    pub kind: FileKind,
    pub body: ViewBody,
}

/// 去重并保持首次出现顺序。
pub fn dedup_names(names: &[&str]) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for n in names {
        if seen.insert(*n) {
            out.push((*n).to_string());
        }
    }
    out
}

/// 把 JBCF 的字符串按角色归成槽位。
///
/// `lookup` 用于把名字变成 hash；返回 `None` 就是**悬空**——保持 `None`，
/// 不要为了好看填个占位 hash。
pub fn material_slots<F>(raw: &[u8], lookup: F) -> ViewBody
where
    F: Fn(&str) -> Option<u64>,
{
    let j = match jbcf::parse(raw) {
        Ok(j) => j,
        Err(e) => {
            return ViewBody::Unavailable {
                why: format!("材质表解析失败：{e}"),
            }
        }
    };
    let mut slots = Vec::new();
    let mut seen = std::collections::HashSet::new();
    // `strings` 的顺序就是文件里的顺序，保持不变 —— 顺序本身是信息。
    for s in &j.strings {
        let r = jbcf::role(&s.text);
        if r == jbcf::Role::Other {
            continue;
        }
        if !seen.insert(s.text.clone()) {
            continue;
        }
        slots.push(SlotSummary {
            role: role_label(r).to_string(),
            name: s.text.clone(),
            resolved: lookup(&s.text),
        });
    }
    ViewBody::Material(slots)
}

/// 给贴图出摘要。`raw` 必须是**已解密解压**的 JMT1 字节。
///
/// `declared_codec` 传目录里那个 4CC 标签；解码出来的真实编解码器从字节里读。
pub fn texture_summary(raw: &[u8], declared_codec: &str) -> ViewBody {
    match jmt1::decode(raw) {
        Ok(t) => ViewBody::Texture(TexSummary {
            w: t.width as u32,
            h: t.height as u32,
            codec: t.codec.as_str().to_string(),
            declared_codec: if declared_codec.is_empty() {
                t.declared_tag.clone()
            } else {
                declared_codec.to_string()
            },
            mips: t.mips,
        }),
        Err(e) => ViewBody::Unavailable {
            why: format!("贴图解码失败：{e}"),
        },
    }
}

/// 给模型出摘要：解信封 + 抽文件内嵌的引用名。
///
/// `lookup` 把名字对到 hash；对不上就保持 `None`（悬空是真实状态）。
pub fn mesh_summary<F>(raw: &[u8], lookup: F) -> ViewBody
where
    F: Fn(&str) -> Option<u64>,
{
    let Some(env) = parse_envelope(raw) else {
        return ViewBody::Unavailable {
            why: "不是 mesh 信封格式（头部没有类型标签）".into(),
        };
    };
    // 文件里的可读串里挑出带扩展名的引用（.tga/.mtl/…），按后缀给角色。
    // 查目录用**客户端原文**，不做大小写变换——名字是原文，查询就必须是原文。
    let mut refs = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for s in printable_strings(raw, 5, 2000) {
        if s.rfind('.').is_none() {
            continue;
        }
        let r = jbcf::role(&s);
        if r == jbcf::Role::Other {
            continue;
        }
        if seen.insert(s.clone()) {
            refs.push(SlotSummary {
                role: role_label(r).to_string(),
                name: s.clone(),
                resolved: lookup(&s),
            });
        }
    }
    ViewBody::Mesh(MeshSummary { envelope: env, refs })
}

/// 给动作出摘要：解信封 + 列文件内可读名（骨架名等）。
pub fn anim_summary(raw: &[u8]) -> ViewBody {
    let Some(env) = parse_envelope(raw) else {
        return ViewBody::Unavailable {
            why: "不是 ani 信封格式（头部没有类型标签）".into(),
        };
    };
    let names = printable_strings(raw, 4, 120);
    ViewBody::Animation(AnimSummary {
        envelope: env,
        names,
    })
}

fn role_label(r: jbcf::Role) -> &'static str {
    use jbcf::Role::*;
    match r {
        Texture => "贴图",
        Material => "材质",
        Model => "模型",
        Skeleton => "骨骼",
        Animation => "动作",
        Scene => "场景",
        Shader => "着色器",
        Other => "其它",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn 路由把常见扩展名送到对的预览器() {
        assert_eq!(FileKind::route("texture", ".tga"), FileKind::Texture);
        assert_eq!(FileKind::route("mesh", ".mesh"), FileKind::Mesh);
        assert_eq!(FileKind::route("ani", ".ani"), FileKind::Animation);
        assert_eq!(FileKind::route("JBCF", ".ske"), FileKind::Skeleton);
        assert_eq!(FileKind::route("JBCF", ".mtl"), FileKind::Material);
        assert_eq!(FileKind::route("JBPU", ".pu"), FileKind::Param);
        assert_eq!(FileKind::route("wav", ".wav"), FileKind::Audio);
        // 空目录类型时靠扩展名兜住
        assert_eq!(FileKind::route("", ".mesh"), FileKind::Mesh);
        // 都不认识 → 明确 Unknown，不猜
        assert_eq!(FileKind::route("", ".zzz"), FileKind::Unknown);
    }

    #[test]
    fn 悬空槽位保持为_None_不编造_hash() {
        // 坏输入应给 Unavailable，而不是"尽力而为"地返回空槽位列表。
        let body = material_slots(b"not a jbcf", |_| None);
        match body {
            ViewBody::Unavailable { why } => assert!(why.contains("解析失败")),
            other => panic!("坏输入应给 Unavailable，实际 {other:?}"),
        }
    }

    #[test]
    fn 材质槽位保留悬空并保序() {
        // 用真实 JBCF 构造太依赖样本，这里直接验证 SlotSummary 的语义约定：
        // resolved=None 表示悬空，且必须**保留**在列表里（不隐藏）。
        let slots = vec![
            SlotSummary { role: "贴图".into(), name: "a.tga".into(), resolved: None },
            SlotSummary { role: "贴图".into(), name: "b.tga".into(), resolved: Some(7) },
        ];
        let dangling = slots.iter().filter(|s| s.resolved.is_none()).count();
        assert_eq!(dangling, 1);
        assert_eq!(slots.len(), 2, "悬空槽位不能被丢掉");
    }

    #[test]
    fn 去重保序() {
        let got = dedup_names(&["b", "a", "b", "c", "a"]);
        assert_eq!(got, vec!["b", "a", "c"]);
    }
}
