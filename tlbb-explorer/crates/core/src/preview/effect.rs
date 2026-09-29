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
//! …         参数块（浮点，字段语法未解）
//! ```
//!
//! 有意思的是字符串：一个特效会写下它的材质、混合模式、渲染器、发射器形状、
//! 更新器与动态参数名，例如 `w1351_smoke_h005.mtl` / `add` / `Billboard` /
//! `Box` / `dyn_random` / `Colour` / `TextureRotator`。**特效 → 材质 → 贴图**
//! 这条链直接从文件内容里来，不是靠文件名猜的（建库时算 `refs` 用的就是这套
//! 分类，界面上却一直没能看）。
//!
//! 参数块只报「有多少个像浮点的数」，不猜字段名——那是下一步的事。

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

/// 一个特效文件。
#[derive(Debug, Clone, PartialEq)]
pub struct Effect {
    pub strings: Vec<String>,
    pub names: EffectNames,
    /// 参数块里「像浮点」的数的个数。字段语法未解，只报数量。
    pub param_floats: usize,
    /// 参数块字节数。
    pub param_bytes: usize,
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
    let n = blob.len() / 4;
    let param_floats = blob
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .filter(|v| v.is_finite() && *v != 0.0 && v.abs() > 1e-4 && v.abs() < 1e5)
        .count();
    Some(Effect {
        names: classify(&strings),
        param_floats,
        param_bytes: blob.len(),
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
}
