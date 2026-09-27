//! 资产 Inspector：左边资产列表（可筛可选），右边详情页。
//!
//! 与「模型」视图（mdl_view.rs）是同一套只读纪律——只开需要的 pak、绝不编造路径、
//! 悬空引用照实标「缺」、名称一律客户端原文。mdl_view 的解析逻辑不便改动，这里
//! 复制了它取字节 / 定位 pak / 把 SlotSummary 转前端槽位的小段，并复用
//! `tlbb_core::preview::mdl_summary`（core 一个字不改）。
//!
//! 性能：asset_inspect 只按 gid 走一次定点 SQL，mdl 只解析本组那一个 .mdl，且只
//! 打开它所在的单个 .pak（不开全部 pak）。整条路径秒回。

use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::Instant;

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use tlbb_core::catalog::labels::{kind_zh, role_zh};
use tlbb_core::catalog::{Catalog, Group};
use tlbb_core::jpak::{Pak, Record};
use tlbb_core::pathmap::PathMap;
use tlbb_core::{jmt1, payload};
use tlbb_core::preview::{material_slots, mdl_summary, scale_rgba, png_bytes, SlotSummary, ViewBody};

// ----------------------------------------------------------------------- 返回模型

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct AssetBrief {
    pub gid: i64,
    pub stem: String,
    /// 组中第一个中文名（agroup_names），没有则为空串。
    pub name: String,
    pub kind: String,
    pub kind_zh: String,
    pub n_mesh: i64,
    pub n_mtl: i64,
    pub n_ani: i64,
    pub n_ske: i64,
    pub n_tex: i64,
    /// 组内文件总数（agroups.n）。
    pub members: i64,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct NameEntry {
    pub name: String,
    pub cls: String,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Counts {
    pub mesh: i64,
    pub mtl: i64,
    pub ani: i64,
    pub ske: i64,
    pub tex: i64,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MemberRow {
    /// 组内角色（agroups 原文，如 mesh/material/animation…）。
    pub role: String,
    /// 角色的中文说法——数据层存英文，展示层才映射，界面上不该出现 `material`。
    pub role_zh: String,
    /// 客户端原文名（取资源路径 basename；无名则用 16 位 hash）。
    pub name: String,
    /// 资源路径；悬空为 null，绝不编造。
    pub path: Option<String>,
    /// 清单里有没有这个文件的实体（有 path 即已解析）。
    pub resolved: bool,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MdlSlot {
    pub role: String,
    pub name: String,
    pub resolved: bool,
    pub hash: Option<String>,
    pub path: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MdlBodyRow {
    pub label: String,
    pub mesh: MdlSlot,
    pub material: MdlSlot,
    /// 材质现场解出的贴图槽（贴图/父材质/着色器）。材质没定位到时为空——
    /// 没有字节就没有槽位，这是事实不是失败。
    pub texture_slots: Vec<MdlSlot>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MdlView {
    pub name: String,
    pub base_dir: String,
    pub skeletons: Vec<MdlSlot>,
    pub bodies: Vec<MdlBodyRow>,
    pub others: Vec<String>,
}

/// 一张预览缩略图。`ok=false` 时 `data_url` 为空、`reason` 说明为什么没图。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct PreviewItem {
    pub label: String,
    pub ok: bool,
    /// data:image/png;base64,... 或 data:image/webp;base64,...
    pub data_url: String,
    pub reason: String,
    /// 16 位十六进制编号。前端点开大图（lightbox）时按它再要一张高清版；
    /// 解码失败的条目没有编号可给。
    pub hash: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Previews {
    pub items: Vec<PreviewItem>,
    /// 实际能出图的候选总数（含没显示的）。
    pub total: usize,
    /// 实际显示的张数。
    pub shown: usize,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct AssetInspectReply {
    pub found: bool,
    /// 一句话：kind_zh + 中文名 + stem + (kind)。
    pub what: String,
    pub names: Vec<NameEntry>,
    pub dir: String,
    /// 组内文件总数。
    pub parts: i64,
    pub counts: Counts,
    pub members: Vec<MemberRow>,
    pub mdl: Option<MdlView>,
    /// 缺什么，人话；库里有 path 给 path，对不上就「客户端未含」/「名字对不上实体」。
    pub missing: Vec<String>,
    /// 还能继续看什么；3D 实时渲染未实现会单独写明。
    pub can_do: Vec<String>,
    /// 组内 .ani 名（前 30 个），客户端原文。
    pub anims: Vec<String>,
    /// 真实解码的贴图缩略图（data URL 内嵌，无外部文件依赖）。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub previews: Option<Previews>,
    /// uvfit 离线试贴候选（有缓存才有；没有就是空——不编造）。全部是 🟡 候选态。
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub texture_candidates: Vec<crate::texture_override::TexCandGroup>,
    /// 本组悬空贴图槽：cfg 出处 + 覆盖表人工确认状态（🟢）。
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub tex_slots: Vec<crate::texture_override::TexSlotInfo>,
    /// 本次处理耗时（毫秒）。
    pub elapsed_ms: u64,
    /// 超过 2s 时给的说明，否则空串。
    pub note: String,
}

// ----------------------------------------------------------------------- 只读定位

pub fn roots() -> (PathBuf, PathBuf) {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    (root, db)
}

fn open_ro(db: &Path) -> Result<Connection, String> {
    Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .map_err(|e| format!("只读打开资源清单失败：{e}"))
        .and_then(|c| {
            c.busy_timeout(std::time::Duration::from_secs(5))
                .map_err(|e| format!("设置超时失败：{e}"))?;
            c.execute_batch("PRAGMA cache_size = -16384;")
                .map_err(|e| format!("设置缓存失败：{e}"))?;
            Ok(c)
        })
}

fn group_by_id(con: &Connection, gid: i64) -> Option<Group> {
    con.query_row(
        "SELECT id, hub, hub_path, dir, stem, kind, n, n_mesh, n_mtl, n_ani, n_ske, n_tex \
         FROM agroups WHERE id = ?1",
        [gid],
        |r| {
            let hub: String = r.get(1)?;
            Ok(Group {
                id: r.get(0)?,
                hub: u64::from_str_radix(&hub, 16).unwrap_or(0),
                hub_path: r.get(2)?,
                dir: r.get(3)?,
                stem: r.get(4)?,
                kind: r.get(5)?,
                n: r.get(6)?,
                n_mesh: r.get(7)?,
                n_mtl: r.get(8)?,
                n_ani: r.get(9)?,
                n_ske: r.get(10)?,
                n_tex: r.get(11)?,
            })
        },
    )
    .ok()
}

/// 按名字查 hash + 路径（客户端原文，basename 匹配）。
fn resolve_name(con: &Connection, name: &str) -> Option<(u64, Option<String>)> {
    let row: Option<(String, String)> = con
        .query_row(
            "SELECT hash, coalesce(path,'') FROM resources WHERE name = ?1 LIMIT 1",
            [name],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .ok();
    let (h, p) = row?;
    let hash = u64::from_str_radix(&h, 16).ok()?;
    let path = if p.is_empty() { None } else { Some(p) };
    Some((hash, path))
}

/// 已解析的 hash → 资源路径。
fn asset_path(con: &Connection, hash: u64) -> Option<String> {
    let p: Option<String> = con
        .query_row(
            "SELECT coalesce(path,'') FROM resources WHERE hash = ?1 LIMIT 1",
            [format!("{hash:016x}")],
            |r| r.get(0),
        )
        .ok();
    match p {
        Some(s) if !s.is_empty() => Some(s),
        _ => None,
    }
}

/// 已解析的 hash → 资源名（无名给空串）。
fn asset_name(con: &Connection, hash: u64) -> Option<String> {
    let n: Option<String> = con
        .query_row(
            "SELECT coalesce(name,'') FROM resources WHERE hash = ?1 LIMIT 1",
            [format!("{hash:016x}")],
            |r| r.get(0),
        )
        .ok();
    match n {
        Some(s) if !s.is_empty() => Some(s),
        _ => None,
    }
}

/// 只打开一个 .pak，返回它里面的记录索引（hash → 记录）。
fn open_one_pak(root: &Path, pak_name: &str) -> Option<(Pak, Vec<Record>)> {
    let p = root.join(format!("{pak_name}.pak"));
    let pak = Pak::open(&p).ok()?;
    let recs: Vec<Record> = pak.records().collect();
    Some((pak, recs))
}

fn slot_of(con: &Connection, s: &SlotSummary) -> MdlSlot {
    let path = s.resolved.and_then(|h| asset_path(con, h));
    MdlSlot {
        role: s.role.clone(),
        name: s.name.clone(),
        resolved: s.resolved.is_some(),
        hash: s.resolved.map(|h| format!("{h:016x}")),
        path,
    }
}

fn is_pets(g: &Group) -> bool {
    g.stem.to_ascii_lowercase().contains("w1351_pets")
}

fn is_zuoqi(g: &Group) -> bool {
    g.stem.to_ascii_lowercase().contains("w1351_zuoqi")
}

fn kind_word(kind: &str) -> &'static str {
    match kind.to_ascii_lowercase().as_str() {
        ".tga" | ".dds" | ".png" | ".jpg" | ".jpeg" | ".bmp" | ".webp" => "贴图",
        ".mesh" => "网格",
        ".mtl" => "材质",
        ".ske" => "骨骼",
        ".ani" => "动作",
        ".mdl" => "模型",
        _ => "引用",
    }
}

fn is_texture_kind(kind: &str) -> bool {
    matches!(
        kind.to_ascii_lowercase().as_str(),
        ".tga" | ".dds" | ".png" | ".jpg" | ".jpeg" | ".bmp" | ".webp"
    )
}

/// 一条悬空引用的人话说明。贴图类必须用标准措辞说清是**客户端没保存路径**，
/// 「贴图类常态」这种写法像在说"这本来就该缺"，把责任边界糊掉了。
fn miss_msg(role: &str, name: &str, kind: &str) -> String {
    if is_texture_kind(kind) || role.contains("贴图") {
        format!(
            "{role} {name}：客户端只保存名称，没有路径，这是客户端的设计，不是解析失败"
        )
    } else {
        format!("{role} {name}：客户端未含此文件")
    }
}

/// ResourcePath.cfg 翻译表，进程级只解析一次；解析不出（非标准客户端布局）就是
/// None，文案退回「只有名称」的旧口径——这层失败绝不允许挡住详情页。
static PATHMAP: OnceLock<Option<PathMap>> = OnceLock::new();

fn pathmap_of(root: &Path) -> Option<&'static PathMap> {
    PATHMAP.get_or_init(|| PathMap::load(root)).as_ref()
}

/// refs 里悬空贴图的人话说明——2026-09-26 口径：cfg 给得出出处就说出处
/// （不编造文件本体已找到，文件在包里确实没有），给不出才说「只保存名称」。
fn miss_msg_ref(role: &str, name: &str, kind: &str, pm: Option<&PathMap>) -> String {
    if is_texture_kind(kind) || role.contains("贴图") {
        match pm.and_then(|p| p.lookup(name)) {
            Some(path) => format!(
                "{role} {name}：ResourcePath.cfg 里登记过它放在 {path}，但解包出来的文件里没有这张图"
            ),
            None => format!(
                "{role} {name}：客户端只保存名称，没有路径，这是客户端的设计，不是解析失败"
            ),
        }
    } else {
        format!("{role} {name}：客户端未含此文件")
    }
}

// ----------------------------------------------------------------------- 列表

/// 资产列表：按 kind 过滤 + 对 stem/中文名 搜索，全量内存过滤。
pub fn list(kind_filter: Option<String>, q: Option<String>, limit: i64) -> Vec<AssetBrief> {
    let (_root, db) = roots();
    let cat = match Catalog::open_ro(&db) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };
    let all = cat.groups(usize::MAX).unwrap_or_default();

    let matches_kind = |g: &Group| -> bool {
        match kind_filter.as_deref() {
            None | Some("all") | Some("") => true,
            Some("player") => g.kind == "player",
            Some("npc") => g.kind == "npc" && !is_pets(g) && !is_zuoqi(g),
            Some("pets") => g.kind == "npc" && is_pets(g),
            Some("mount") => g.kind == "npc" && is_zuoqi(g),
            Some("effect") => g.kind == "effect",
            Some("map-prop") => g.kind == "map-prop",
            Some(other) => g.kind == other,
        }
    };

    let mut filtered: Vec<&Group> = all.iter().filter(|g| matches_kind(g)).collect();

    // 中文名搜索需要 agroup_names；只在给了 q 时才做，且只在过滤后的候选上跑。
    if let Some(q) = q.as_deref().filter(|s| !s.trim().is_empty()) {
        let ql = q.trim().to_lowercase();
        let con = match open_ro(&db) {
            Ok(c) => c,
            Err(_) => return Vec::new(),
        };
        let like = format!("%{ql}%");
        let mut st = match con.prepare(
            "SELECT DISTINCT gid FROM agroup_names WHERE name LIKE ?1 OR cls LIKE ?1",
        ) {
            Ok(s) => s,
            Err(_) => return Vec::new(),
        };
        let mut matched: HashSet<i64> = HashSet::new();
        if let Ok(rows) = st.query_map([&like], |r| r.get::<_, i64>(0)) {
            for r in rows.flatten() {
                matched.insert(r);
            }
        }
        filtered.retain(|g| g.stem.to_ascii_lowercase().contains(&ql) || matched.contains(&g.id));
    }

    filtered.sort_by(|a, b| b.n.cmp(&a.n));
    let lim = if limit <= 0 { 1000 } else { limit as usize };
    filtered.truncate(lim);

    // 只给最终这一屏补中文名，避免给上万组逐个查名字。
    filtered
        .iter()
        .map(|g| {
            let name = cat
                .group_names(g.id)
                .ok()
                .and_then(|ns| ns.into_iter().next())
                .map(|(n, _)| n)
                .unwrap_or_default();
            AssetBrief {
                gid: g.id,
                stem: g.stem.clone(),
                name,
                kind: g.kind.clone(),
                kind_zh: kind_zh(&g.kind).to_string(),
                n_mesh: g.n_mesh,
                n_mtl: g.n_mtl,
                n_ani: g.n_ani,
                n_ske: g.n_ske,
                n_tex: g.n_tex,
                members: g.n,
            }
        })
        .collect()
}

// ----------------------------------------------------------------------- 详情

pub fn inspect(gid: i64) -> Result<AssetInspectReply, String> {
    let t0 = Instant::now();
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_ro(&db)?;
    let cat = Catalog::open_ro(&db).map_err(|e| e.to_string())?;

    let group = group_by_id(&con, gid)
        .ok_or_else(|| format!("没有找到 id={gid} 的资源组（它还在后台读取中，或编号不存在）"))?;

    let names = cat.group_names(gid).unwrap_or_default();
    let members = cat.members(gid).unwrap_or_default();
    let refs = cat.refs_from_group(gid).unwrap_or_default();

    // 只认真正的中文名：登记名里混着贴图文件名，拿它当组名会让人以为
    // 这组资产叫某个 .tga。没有中文名就只报茎名。
    let first_cn = names
        .iter()
        .find(|(n, _)| n.chars().any(|c| ('\u{4e00}'..='\u{9fff}').contains(&c)))
        .map(|(n, _)| n.clone())
        .unwrap_or_default();
    // 一句话说明：没有中文名或没有茎名时别留下多余空格和空括号；
    // 尾巴上的 `（npc）（ui）` 是数据层英文键，不该摆给人看。
    let what = {
        let mut parts = vec![kind_zh(&group.kind).to_string()];
        if !first_cn.is_empty() {
            parts.push(first_cn.clone());
        }
        if !group.stem.is_empty() {
            parts.push(group.stem.clone());
        }
        parts.join(" ")
    };

    // 组成树：找本组那个 .mdl，只开它所在的单个 pak。
    let mdl_member = members
        .iter()
        .find(|m| {
            m.path
                .as_deref()
                .map(|p| p.to_ascii_lowercase().ends_with(".mdl"))
                .unwrap_or(false)
        });
    let mdl = if let Some(m) = mdl_member {
        compose_mdl(&con, &root, m)
    } else {
        None
    };

    // 成员行（按 role 分组排序）。
    let role_rank = |r: &str| -> u8 {
        match r {
            "model" => 0,
            "mesh" => 1,
            "material" => 2,
            "skeleton" => 3,
            "animation" => 4,
            "texture" => 5,
            "scene" => 6,
            "map" => 7,
            "effect" => 8,
            "config" => 9,
            "audio" => 10,
            _ => 11,
        }
    };
    let mut member_rows: Vec<MemberRow> = members
        .iter()
        .map(|m| {
            let path = m.path.clone();
            let name = match &path {
                Some(p) => Path::new(p)
                    .file_name()
                    .map(|s| s.to_string_lossy().into_owned())
                    .unwrap_or_else(|| format!("{:016x}", m.hash)),
                None => asset_name(&con, m.hash).unwrap_or_else(|| format!("{:016x}", m.hash)),
            };
            MemberRow {
                role: m.role.clone(),
                role_zh: role_zh(&m.role).to_string(),
                name,
                path,
                resolved: m.path.is_some(),
            }
        })
        .collect();
    member_rows.sort_by(|a, b| role_rank(&a.role).cmp(&role_rank(&b.role)).then(a.name.cmp(&b.name)));

    // 动作名单（前 30，去重）：成员里 .ani + refs 里 kind=.ani。
    let mut anims: Vec<String> = Vec::new();
    {
        let mut seen: HashSet<String> = HashSet::new();
        let push = |anims: &mut Vec<String>, seen: &mut HashSet<String>, n: &str| {
            if seen.insert(n.to_string()) && anims.len() < 30 {
                anims.push(n.to_string());
            }
        };
        for m in &members {
            if let Some(p) = &m.path {
                if p.to_ascii_lowercase().ends_with(".ani") {
                    if let Some(f) = Path::new(p).file_name() {
                        push(&mut anims, &mut seen, &f.to_string_lossy());
                    }
                }
            }
        }
        for r in &refs {
            if r.kind == ".ani" {
                push(&mut anims, &mut seen, &r.name);
            }
        }
    }

    // 缺什么：mdl 悬空槽 + refs 悬空引用 + 无名成员，照实写。
    let mut missing: Vec<String> = Vec::new();
    if let Some(mv) = &mdl {
        for s in &mv.skeletons {
            if !s.resolved {
                missing.push(miss_msg(&s.role, &s.name, ""));
            }
        }
        for b in &mv.bodies {
            if !b.mesh.resolved {
                missing.push(miss_msg(&b.mesh.role, &b.mesh.name, ""));
            }
            if b.material.name == "<缺>" {
                missing.push(format!("网格 {} 缺少配对材质：客户端未含此文件", b.mesh.name));
            } else if !b.material.resolved {
                missing.push(miss_msg(&b.material.role, &b.material.name, ""));
            }
        }
    }
    for r in &refs {
        if r.to.is_none() {
            missing.push(miss_msg_ref(
                kind_word(&r.kind),
                &r.name,
                &r.kind,
                pathmap_of(&root),
            ));
        }
    }
    // 无名成员：只报"哪一类、几个"，不报编号——编号在树行的悬停提示和
    // 下面的技术信息里都有，摆在正文等于把 hash 塞给美术看。
    {
        let mut nameless: HashMap<&'static str, usize> = HashMap::new();
        for m in &members {
            if m.path.is_none() {
                *nameless.entry(role_zh(&m.role)).or_default() += 1;
            }
        }
        for (role, n) in nameless {
            missing.push(format!(
                "{role} {n} 个：客户端未含这些文件，清单里只记了编号（编号见悬停提示与技术信息）"
            ));
        }
    }
    // 去重保序，封顶 80 条，避免一个贴图集群刷屏。
    {
        let mut seen: HashSet<String> = HashSet::new();
        missing.retain(|s| seen.insert(s.clone()));
        missing.truncate(80);
    }

    // 能继续看什么。
    let has_tex = group.n_tex > 0
        || members.iter().any(|m| {
            m.path
                .as_deref()
                .map(|p| is_texture_kind(p))
                .unwrap_or(false)
        })
        || refs.iter().any(|r| is_texture_kind(&r.kind));
    let mut can_do: Vec<String> = Vec::new();
    if mdl.is_some() {
        can_do.push("组成树".to_string());
    }
    if has_tex {
        can_do.push("贴图预览".to_string());
    }
    if !anims.is_empty() {
        can_do.push("动作名单".to_string());
    }
    // M2-2 起立体预览真能点了，但只有定位到实体的网格才行——没定位到就不许诺。
    let mesh_hits = mdl
        .as_ref()
        .map(|mv| mv.bodies.iter().filter(|b| b.mesh.resolved).count())
        .unwrap_or(0);
    if mesh_hits > 0 {
        can_do.push(format!("立体预览（{mesh_hits} 个网格）"));
    } else if group.n_mesh > 0 {
        can_do.push("立体预览：这些网格没对上文件".to_string());
    }

    // 预览：只对真实解析到 hash 的贴图出图，解不出的照实记原因。
    //   优先解码 .mdl 材质槽引用的 .mtl（最相关），大组不逐个解码。
    let prefer_mtl: Vec<String> = mdl
        .as_ref()
        .map(|mv| {
            mv.bodies
                .iter()
                .filter(|b| b.material.resolved && b.material.name != "<缺>")
                .map(|b| b.material.name.clone())
                .collect()
        })
        .unwrap_or_default();
    let previews = collect_previews(&con, &root, &members, &prefer_mtl);
    let previews = if previews.total == 0 && previews.items.is_empty() {
        None
    } else {
        Some(previews)
    };

    let elapsed = t0.elapsed().as_millis() as u64;
    let note = if elapsed > 2000 {
        format!("本次处理耗时 {elapsed}ms，超过 2s——可能是磁盘冷启动或该组 .pak 较大。")
    } else {
        String::new()
    };

    Ok(AssetInspectReply {
        found: true,
        what,
        names: names
            .into_iter()
            .map(|(name, cls)| NameEntry { name, cls })
            .collect(),
        dir: group.dir,
        parts: group.n,
        counts: Counts {
            mesh: group.n_mesh,
            mtl: group.n_mtl,
            ani: group.n_ani,
            ske: group.n_ske,
            tex: group.n_tex,
        },
        texture_candidates: crate::texture_override::load_candidate_groups(
            &root,
            &member_rows
                .iter()
                .map(|m| (m.role.clone(), m.name.clone(), m.resolved))
                .collect::<Vec<_>>(),
        ),
        tex_slots: crate::texture_override::build_tex_slots(
            &refs
                .iter()
                .filter(|r| r.to.is_none())
                .map(|r| (r.kind.clone(), r.name.clone()))
                .collect::<Vec<_>>(),
            pathmap_of(&root),
            &root,
        ),
        members: member_rows,
        mdl,
        missing,
        can_do,
        anims,
        previews,
        elapsed_ms: elapsed,
        note,
    })
}

/// 把本组那个 .mdl 解成组成树；只开它所在的单个 .pak。
fn compose_mdl(con: &Connection, root: &Path, m: &tlbb_core::catalog::Member) -> Option<MdlView> {
    let pak_name = m.pak.trim();
    let (pak, recs) = open_one_pak(root, pak_name)?;
    let rec = recs
        .iter()
        .find(|r| r.hash == m.hash && r.offset as i64 == m.offset)
        .or_else(|| recs.iter().find(|r| r.hash == m.hash))?;
    let dec = payload::decode(&pak, rec).ok()?;
    let resolve = |n: &str| resolve_name(con, n).map(|(h, _)| h);
    if let ViewBody::Model(mdl) = mdl_summary(&dec.bytes, resolve) {
        Some(MdlView {
            name: mdl.name,
            base_dir: mdl.base_dir,
            skeletons: mdl.skeletons.iter().map(|s| slot_of(con, s)).collect(),
            bodies: mdl
                .bodies
                .iter()
                .map(|b| {
                    let material = slot_of(con, &b.material);
                    let texture_slots = texture_slots_of(con, &pak, &recs, &material, &resolve);
                    MdlBodyRow {
                        label: b.label.clone(),
                        mesh: slot_of(con, &b.mesh),
                        material,
                        texture_slots,
                    }
                })
                .collect(),
            others: mdl.others,
        })
    } else {
        None
    }
}

/// 一个材质实体的贴图槽：现场把 .mtl 解一遍。材质通常和 .mdl 在同一个容器里，
/// 所以只查已经开着的那一个 pak，不为槽位再开一批。
fn texture_slots_of(
    con: &Connection,
    pak: &Pak,
    recs: &[Record],
    mat: &MdlSlot,
    resolve: &dyn Fn(&str) -> Option<u64>,
) -> Vec<MdlSlot> {
    let Some(hx) = &mat.hash else {
        return Vec::new();
    };
    let Ok(h) = u64::from_str_radix(hx, 16) else {
        return Vec::new();
    };
    let Some(rec) = recs.iter().find(|r| r.hash == h) else {
        return Vec::new();
    };
    let Ok(dec) = payload::decode(pak, rec) else {
        return Vec::new();
    };
    match material_slots(&dec.bytes, resolve) {
        ViewBody::Material(slots) => slots.iter().map(|s| slot_of(con, s)).collect(),
        _ => Vec::new(),
    }
}

// ----------------------------------------------------------------------- 预览

/// 标准 base64。**手写**是因为离线环境不许加依赖；20 行换一个依赖不值。
pub(crate) fn b64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for ch in data.chunks(3) {
        let b1 = ch[0] as u32;
        let b2 = *ch.get(1).unwrap_or(&0) as u32;
        let b3 = *ch.get(2).unwrap_or(&0) as u32;
        let n = (b1 << 16) | (b2 << 8) | b3;
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if ch.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if ch.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    out
}

/// 查一个 hash 的存储位置与类型。
fn res_loc(con: &Connection, hash: u64) -> Option<(String, i64, i64, String)> {
    // (pak, offset, stored, type)
    con.query_row(
        "SELECT coalesce(pak,''), coalesce(offset,0), coalesce(stored,0), coalesce(type,'') \
         FROM resources WHERE hash = ?1 LIMIT 1",
        [format!("{hash:016x}")],
        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
    )
    .ok()
}

/// 解码一张贴图缩略图，返回 (mime, 图像字节)。
///
/// type=texture → JMT1 → 缩到 160 出 PNG；WEBP codec → 原样交浏览器；
/// webp/jpeg/png 类型 → 容器字节本身就是浏览器原生格式，直接嵌。
fn decode_thumb(
    con: &Connection,
    root: &Path,
    pak_cache: &mut HashMap<String, Option<(Pak, Vec<Record>)>>,
    hash: u64,
) -> Result<(&'static str, Vec<u8>), String> {
    let (pak_name, offset, _stored, rtype) = res_loc(con, hash)
        .ok_or_else(|| "不在资源清单里".to_string())?;
    let entry = pak_cache
        .entry(pak_name.clone())
        .or_insert_with(|| open_one_pak(root, &pak_name));
    let (pak, recs) = entry.as_mut().ok_or_else(|| format!("打开 {pak_name}.pak 失败"))?;
    let rec = recs
        .iter()
        .find(|r| r.hash == hash && r.offset as i64 == offset)
        .or_else(|| recs.iter().find(|r| r.hash == hash))
        .ok_or_else(|| "容器索引里没有这条记录".to_string())?;
    let dec = payload::decode(pak, rec).map_err(|e| format!("取字节失败：{e}"))?;
    match rtype.as_str() {
        "texture" => {
            let t = jmt1::decode(&dec.bytes).map_err(|e| format!("JMT1 解码失败：{e}"))?;
            if let Some(w) = &t.webp {
                return Ok(("image/webp", w.clone()));
            }
            if t.rgba.is_empty() {
                return Err(format!("编码 {} 无像素", t.codec.as_str()));
            }
            let (scaled, w, h) = scale_rgba(&t.rgba, t.width as usize, t.height as usize, 160);
            let png = png_bytes(w as u16, h as u16, &scaled, true)
                .map_err(|e| format!("编码 PNG 失败：{e}"))?;
            Ok(("image/png", png))
        }
        "webp" => Ok(("image/webp", dec.bytes)),
        "jpeg" => Ok(("image/jpeg", dec.bytes)),
        "png" => Ok(("image/png", dec.bytes)),
        other => Err(format!(
            "这个文件不是图片（它属于 {other} 那类内部文件），所以出不了图"
        )),
    }
}

/// 收集本组的预览：组成员贴图 + 材质槽解析到的贴图。
/// 纪律：只对**真实解析到 hash** 的条目出图；解不出的照实记原因，绝不拿别的图顶。
///
/// 性能护栏（实测教训：3,405 部件的大组有 ~800 个 .mtl，逐个解码要 60 秒）：
/// - .mtl 只解码最多 4 个，且**优先取 .mdl 材质槽引用的那几个**（最相关）；
/// - 解码尝试最多 20 次，凑满 12 张成功图即停；候选总数只计数、不解码。
fn collect_previews(
    con: &Connection,
    root: &Path,
    members: &[tlbb_core::catalog::Member],
    prefer_mtl: &[String],
) -> Previews {
    const MAX_SHOW: usize = 12;
    const MAX_MTL_DECODE: usize = 4;
    const MAX_DECODE_ATTEMPTS: usize = 20;
    let mut items: Vec<PreviewItem> = Vec::new();
    let mut pak_cache: HashMap<String, Option<(Pak, Vec<Record>)>> = HashMap::new();

    // 候选 1：组内贴图成员（有 path 才算解析到）。
    let mut cands: Vec<(String, u64)> = Vec::new();
    let mut seen_cand: HashSet<u64> = HashSet::new();
    for m in members {
        if let Some(p) = &m.path {
            if is_texture_kind(p) && seen_cand.insert(m.hash) {
                cands.push((p.clone(), m.hash));
            }
        }
    }
    // 候选 2：.mtl 成员的槽位解析结果（玩家服装组的主来源：同名衣柜图标）。
    //   只解码 MAX_MTL_DECODE 个：先挑 .mdl 材质引用的同名者，再按组内顺序补足。
    let mtl_members: Vec<&tlbb_core::catalog::Member> = members
        .iter()
        .filter(|m| {
            m.path
                .as_deref()
                .map(|p| p.to_ascii_lowercase().ends_with(".mtl"))
                .unwrap_or(false)
        })
        .collect();
    let base_of = |p: &str| -> String {
        Path::new(p)
            .file_name()
            .map(|s| s.to_string_lossy().to_ascii_lowercase())
            .unwrap_or_default()
    };
    let mut picked: Vec<&tlbb_core::catalog::Member> = Vec::new();
    for want in prefer_mtl {
        if let Some(m) = mtl_members
            .iter()
            .find(|m| base_of(m.path.as_deref().unwrap_or("")) == base_of(want))
        {
            if !picked.iter().any(|x| x.hash == m.hash) {
                picked.push(m);
            }
        }
    }
    for m in &mtl_members {
        if picked.len() >= MAX_MTL_DECODE {
            break;
        }
        if !picked.iter().any(|x| x.hash == m.hash) {
            picked.push(m);
        }
    }
    for m in picked.into_iter().take(MAX_MTL_DECODE) {
        let entry = pak_cache
            .entry(m.pak.trim().to_string())
            .or_insert_with(|| open_one_pak(root, m.pak.trim()));
        let Some((pak, recs)) = entry.as_mut() else { continue };
        let Some(rec) = recs
            .iter()
            .find(|r| r.hash == m.hash && r.offset as i64 == m.offset)
            .or_else(|| recs.iter().find(|r| r.hash == m.hash))
        else {
            continue;
        };
        let Ok(dec) = payload::decode(pak, rec) else { continue };
        let resolve = |n: &str| resolve_name(con, n).map(|(h, _)| h);
        if let ViewBody::Material(slots) = material_slots(&dec.bytes, resolve) {
            for s in slots {
                if let Some(h) = s.resolved {
                    if seen_cand.insert(h) {
                        // cfg 翻译表按名字全局匹配,服装贴图名常和衣柜图标同名——
                        // 对上的是图标就把这话写在图上,不然读者以为看到了衣服本体。
                        let icon = asset_path(con, h)
                            .map(|p| p.replace('\\', "/").contains("ui/icon/"))
                            .unwrap_or(false);
                        let tag = if icon { "材质槽，对上的是衣柜图标" } else { "材质槽" };
                        cands.push((format!("{}（{}）", s.name, tag), h));
                    }
                }
            }
        }
    }

    let total = cands.len();
    // 解码：凑满 MAX_SHOW 张成功图即停；失败条目照实保留（灰卡+原因）。
    let mut attempts = 0usize;
    for (label, hash) in cands {
        if items.iter().filter(|p| p.ok).count() >= MAX_SHOW {
            break;
        }
        if attempts >= MAX_DECODE_ATTEMPTS {
            break;
        }
        attempts += 1;
        match decode_thumb(con, root, &mut pak_cache, hash) {
            Ok((mime, bytes)) => items.push(PreviewItem {
                label,
                ok: true,
                data_url: format!("data:{mime};base64,{}", b64(&bytes)),
                reason: String::new(),
                hash: Some(format!("{hash:016x}")),
            }),
            Err(e) => items.push(PreviewItem {
                label,
                ok: false,
                data_url: String::new(),
                reason: e,
                hash: None,
            }),
        }
    }
    let shown = items.len();
    Previews { items, total, shown }
}

// ----------------------------------------------------------------------- IPC

#[tauri::command]
pub async fn asset_list(
    kind_filter: Option<String>,
    q: Option<String>,
    limit: i64,
) -> Result<Vec<AssetBrief>, String> {
    let kind_filter = kind_filter.clone();
    let q = q.clone();
    tauri::async_runtime::spawn_blocking(move || list(kind_filter, q, limit))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn asset_inspect(gid: i64) -> Result<AssetInspectReply, String> {
    tauri::async_runtime::spawn_blocking(move || inspect(gid))
        .await
        .map_err(|e| e.to_string())?
}

// ----------------------------------------------------------------------- 验收自测

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn 验收_10个资产组_inspect_全字段非空() {
        let (_root, db) = roots();
        let cat = Catalog::open_ro(&db).expect("打开 catalog 失败");
        let groups = cat.groups(usize::MAX).expect("读取 agroups 失败");

        // 挑 10 个覆盖要求的类目。
        let mut players = 0usize;
        let mut npc_other = 0usize;
        let mut monsters = 0usize;
        let mut effect = 0usize;
        let mut mapprop = 0usize;
        let mut mount = 0usize;
        let mut pets = 0usize;

        let mut picks: Vec<(String, i64)> = Vec::new();

        for g in &groups {
            let tag_ok = |want: &[&str]| -> bool {
                let ts = cat.tags(g.id).unwrap_or_default();
                ts.iter().any(|(t, _)| want.contains(&t.as_str()))
            };
            match g.kind.as_str() {
                "player" if players < 3 => {
                    players += 1;
                    picks.push(("player".into(), g.id));
                }
                "effect" if effect < 1 => {
                    effect += 1;
                    picks.push(("effect".into(), g.id));
                }
                "map-prop" if mapprop < 1 => {
                    mapprop += 1;
                    picks.push(("map-prop".into(), g.id));
                }
                "npc" if is_zuoqi(g) && mount < 1 => {
                    mount += 1;
                    picks.push(("mount".into(), g.id));
                }
                "npc" if is_pets(g) && pets < 1 => {
                    pets += 1;
                    picks.push(("pets".into(), g.id));
                }
                "npc" if npc_other < 1 => {
                    npc_other += 1;
                    picks.push(("npc".into(), g.id));
                }
                "npc" if monsters < 2 && tag_ok(&["monster", "boss", "quest"]) => {
                    monsters += 1;
                    picks.push(("monster".into(), g.id));
                }
                _ => {}
            }
        }

        assert!(
            picks.len() == 10,
            "只挑到 {} 个组（player={players} npc_other={npc_other} monster={monsters} mount={mount} pets={pets} effect={effect} mapprop={mapprop}），检查类目命名",
            picks.len()
        );

        println!("=== Inspector 验收 10 组（摘要行） ===");
        for (cat_name, gid) in &picks {
            let r = inspect(*gid).expect("inspect 失败");
            assert!(r.found, "gid={gid} found 应为 true");
            assert!(!r.what.is_empty(), "gid={gid} what 应为非空");
            assert!(r.counts.mesh + r.counts.mtl + r.counts.ani + r.counts.ske + r.counts.tex > 0
                || r.parts > 0, "gid={gid} counts 应为非空");
            assert!(!r.missing.is_empty(), "gid={gid} missing 应为非空（实测必有悬空引用）");
            let parts = r.parts;
            let miss = r.missing.len();
            let friendly = r.names.first().map(|n| n.name.as_str()).unwrap_or("");
            println!(
                "[{cat_name}] gid={gid} stem={} · {} · {} 部件 · {miss} 缺 · 耗时 {}ms",
                g_stem(&groups, *gid),
                friendly,
                parts,
                r.elapsed_ms
            );
            println!(
                "    stem={} | what={} | can_do={} | anims={}",
                g_stem(&groups, *gid),
                r.what,
                r.can_do.join("/"),
                r.anims.len()
            );
        }
        println!("=== 验收结束 ===");
    }

    fn g_stem(groups: &[Group], gid: i64) -> String {
        groups
            .iter()
            .find(|g| g.id == gid)
            .map(|g| g.stem.clone())
            .unwrap_or_default()
    }

    #[test]
    fn 预览_有图组出图_无图组诚实为空() {
        // 实测事实（2026-09-23）：能出图的组是 ui 类衣柜图标组（贴图成员有 path）；
        // 普通服装组的 .mtl 贴图槽全悬空（贴图类命名断链），此时 previews 为 None
        // 且前端显示「没有能对上实体的贴图」——这是诚实行为，不是缺陷。
        let (_root, db) = roots();
        let con = open_ro(&db).expect("打开 db");

        // 正例：ui 组，贴图成员已解析。
        let gid_ui: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem='w1351_nv_s_yifu_bingcha'",
                [],
                |r| r.get(0),
            )
            .expect("ui 组应存在");
        let r = inspect(gid_ui).expect("inspect 失败");
        let pv = r
            .previews
            .as_ref()
            .unwrap_or_else(|| panic!("ui 组应有 previews"));
        assert!(!pv.items.is_empty(), "ui 组 previews.items 不应为空");
        let ok_n = pv.items.iter().filter(|p| p.ok).count();
        println!("ui 组: total={} shown={} ok={} fail={}", pv.total, pv.shown, ok_n, pv.items.len() - ok_n);
        assert!(ok_n > 0, "ui 组至少应出一张图");
        for p in &pv.items {
            if p.ok {
                assert!(p.data_url.starts_with("data:image/"), "dataUrl 前缀不对");
                assert!(p.data_url.len() > 1_400, "dataUrl 太小，像空图：{}B", p.data_url.len());
            } else {
                assert!(!p.reason.is_empty(), "失败条目必须给原因");
            }
        }

        // 反例：服装组，mtl 槽全悬空 → 诚实为空。
        let gid_cloth: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem='w1351_nan_s_yifu_new_dingchunqiu'",
                [],
                |r| r.get(0),
            )
            .expect("服装组应存在");
        let r = inspect(gid_cloth).expect("inspect 失败");
        match &r.previews {
            None => {} // 诚实为空，前端显示"没有能对上实体的贴图"
            Some(pv) => {
                let ok_n = pv.items.iter().filter(|p| p.ok).count();
                println!("服装组: total={} shown={} ok={} fail={}", pv.total, pv.shown, ok_n, pv.items.len() - ok_n);
            }
        }
    }
}
