//! 「模型组成」卡片的 IPC 入口。
//!
//! 用户输入一个 .mdl 资源名（客户端原文，如 `w1351_nan_s_yifu_new_dingchunqiu`），
//! 这里把它定位、取字节、解成模型定义摘要，并把「骨架 / 网格+材质 / 挂点」如实摆出来。
//!
//! 三条纪律与项目一致：
//! 1. 解不出就说解不出，不猜、不拿同类资源顶。
//! 2. 缺什么显示什么：引用对不上名字就标「缺」，不编路径。
//! 3. 名称一律客户端原文，不翻译。
//!
//! 本模块完全自包含、只读：直接以只读方式打开 resources.db 与各 .pak，不依赖
//! `AppData` 的任何内部状态，因此也不改动 `data.rs` 等既有文件。

use std::collections::HashMap;
use std::path::PathBuf;

use serde::Serialize;
use tlbb_core::jpak::{Pak, Record};
use tlbb_core::payload;
use tlbb_core::preview::{material_slots, mdl_summary, SlotSummary, ViewBody};

// ---- 返回给前端的视图模型（键用 camelCase，值用中文） ----

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MdlSlot {
    /// 槽位角色（骨骼 / 网格 / 材质），客户端原文风格。
    pub role: String,
    /// 引用名（客户端原文）。
    pub name: String,
    /// 是否在资源库里对上了实体。
    pub resolved: bool,
    /// 对上时的实体 hash（16 位 hex）；悬空为 null。
    pub hash: Option<String>,
    /// 对上时的资源路径；悬空为 null。绝不编造。
    pub path: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MdlBodyRow {
    /// 紧邻其前的无扩展名串（LOD/段名），可能为空。
    pub label: String,
    pub mesh: MdlSlot,
    pub material: MdlSlot,
    /// 材质现场解出的贴图槽状态（材质在库里定位到才展开；空 = 没解出材质体）。
    pub texture_slots: Vec<MdlSlot>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct MdlComposeReply {
    /// 是否在资源清单里定位到了这个 .mdl。
    pub found: bool,
    /// 给用户的说明（找不到 / 解不出 / 成功都靠它说人话）。
    pub note: String,
    /// 模型名（客户端原文）。
    pub name: String,
    /// 资源基目录（来自文件内字符串，可能为空）。
    pub base_dir: String,
    /// 这个 .mdl 自己在客户端里的路径；找不到为空。
    pub path: String,
    pub skeletons: Vec<MdlSlot>,
    pub bodies: Vec<MdlBodyRow>,
    /// 动作列表。`.mdl` 里没有动作引用——它们挂在资源组上（refs kind='.ani'），
    /// 所以这一栏来自清单，不来自模型文件本身。
    pub animations: Vec<MdlSlot>,
    /// 其余成员（挂点/变体名，按文件出现序，语义不断言）。
    pub others: Vec<String>,
}

// ---- 只读定位：与 lib.rs::roots 同一套环境变量 ----

fn roots() -> (PathBuf, PathBuf) {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    (root, db)
}

/// 按名字查 hash + 路径（客户端原文，basename 匹配，与 view.rs 的 resolve_name 一致）。
fn resolve_name(con: &rusqlite::Connection, name: &str) -> Option<(u64, Option<String>)> {
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

/// 已解析的 hash → 资源路径（找不到/无名给 None）。
fn asset_path(con: &rusqlite::Connection, hash: u64) -> Option<String> {
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

/// 已解析的 hash → 它所在的 .pak 名与容器内偏移（用于挑对 PAK）。
fn asset_loc(con: &rusqlite::Connection, hash: u64) -> Option<(String, i64)> {
    let row: Option<(String, i64)> = con
        .query_row(
            "SELECT coalesce(pak,''), offset FROM resources WHERE hash = ?1 LIMIT 1",
            [format!("{hash:016x}")],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .ok();
    row.filter(|(pak, _)| !pak.is_empty())
}

/// 在清单里定位输入的 .mdl：先精确名，再补 .mdl，再模糊。
fn find_mdl(con: &rusqlite::Connection, name: &str) -> Result<(u64, String), String> {
    let nm = name.trim();
    if nm.is_empty() {
        return Err("请输入一个模型资源名".to_string());
    }
    let exact = |n: &str| -> Option<(u64, String)> {
        let row: Option<(String, String)> = con
            .query_row(
                "SELECT hash, coalesce(path,'') FROM resources WHERE name = ?1 LIMIT 1",
                [n],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .ok();
        let (h, p) = row?;
        let hash = u64::from_str_radix(&h, 16).ok()?;
        Some((hash, p))
    };
    if let Some(r) = exact(nm) {
        return Ok(r);
    }
    if !nm.to_ascii_lowercase().ends_with(".mdl") {
        if let Some(r) = exact(&format!("{nm}.mdl")) {
            return Ok(r);
        }
    }
    let like = format!("%{nm}%");
    let fuzzy: Option<(String, String)> = con
        .query_row(
            "SELECT hash, coalesce(path,'') FROM resources WHERE name LIKE ?1 \
             ORDER BY length(name) LIMIT 1",
            [&like],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .ok();
    match fuzzy {
        Some(row) => u64::from_str_radix(&row.0, 16)
            .ok()
            .map(|h| (h, row.1))
            .ok_or_else(|| format!("在资源清单里没有找到与「{nm}」匹配的 .mdl。")),
        None => Err(format!("在资源清单里没有找到与「{nm}」匹配的 .mdl。")),
    }
}

/// 打开所有 .pak，建 hash → (pak 序号, 记录) 与 pak 名 → 序号 两份索引。
fn open_paks(root: &std::path::Path) -> (Vec<Pak>, HashMap<String, usize>, HashMap<u64, Vec<(usize, Record)>>) {
    let mut paks: Vec<Pak> = Vec::new();
    let mut by_name: HashMap<String, usize> = HashMap::new();
    let mut recs: HashMap<u64, Vec<(usize, Record)>> = HashMap::new();
    if let Ok(es) = std::fs::read_dir(root) {
        for e in es.flatten() {
            let p = e.path();
            if p.extension().map(|x| !x.eq_ignore_ascii_case("pak")).unwrap_or(true) {
                continue;
            }
            let Some(stem) = p.file_stem().map(|s| s.to_string_lossy().to_string()) else {
                continue;
            };
            let Ok(pak) = Pak::open(&p) else { continue };
            let idx = paks.len();
            by_name.insert(stem, idx);
            paks.push(pak);
        }
    }
    for (i, pak) in paks.iter().enumerate() {
        for rec in pak.records() {
            recs.entry(rec.hash).or_default().push((i, rec));
        }
    }
    (paks, by_name, recs)
}

/// 容器索引的进程级缓存：paks 打开 + 11 万条记录索引每次重建要 ~1s，
/// 是「打开一个资源 <1 秒」这条验收线的主要成本。索引只读，缓存一次终身受用。
struct PakCache {
    paks: Vec<Pak>,
    by_name: HashMap<String, usize>,
    recs: HashMap<u64, Vec<(usize, Record)>>,
}

fn pak_cache() -> &'static PakCache {
    static CACHE: std::sync::OnceLock<PakCache> = std::sync::OnceLock::new();
    CACHE.get_or_init(|| {
        let (root, _) = roots();
        let (paks, by_name, recs) = open_paks(&root);
        PakCache { paks, by_name, recs }
    })
}

fn slot_of(con: &rusqlite::Connection, s: &SlotSummary) -> MdlSlot {
    let path = s.resolved.and_then(|h| asset_path(con, h));
    MdlSlot {
        role: s.role.clone(),
        name: s.name.clone(),
        resolved: s.resolved.is_some(),
        hash: s.resolved.map(|h| format!("{h:016x}")),
        path,
    }
}

/// 按 hash 从对应容器里取出完整字节（清单给容器名与偏移，容器索引给记录）。
fn read_res_bytes(
    con: &rusqlite::Connection,
    paks: &[Pak],
    by_name: &HashMap<String, usize>,
    recs: &HashMap<u64, Vec<(usize, Record)>>,
    hash: u64,
) -> Result<Vec<u8>, String> {
    let Some((pak_name, offset)) = asset_loc(con, hash) else {
        return Err("清单里没有记录它所在的容器".to_string());
    };
    let &slot = by_name
        .get(&pak_name)
        .ok_or_else(|| format!("找不到它所在的容器：{pak_name}"))?;
    let same: Vec<&(usize, Record)> = recs
        .get(&hash)
        .ok_or("这个 hash 不在任何 .pak 的记录里——无法取字节")?
        .iter()
        .filter(|(i, _)| *i == slot)
        .collect();
    let rec = same
        .iter()
        .copied()
        .find(|(_, r)| r.offset as i64 == offset)
        .or_else(|| same.first().copied())
        .map(|(_, r)| r)
        .ok_or("这个 hash 在对应容器里的记录对不上")?;
    payload::decode(&paks[slot], rec)
        .map(|d| d.bytes)
        .map_err(|e| format!("取字节失败：{e}"))
}

/// 一个材质实体的贴图槽状态：把 .mtl 现场解一遍。
/// 材质没定位到（悬空）时返回空——没有字节就没有槽位，这是事实不是失败。
fn texture_slots_of(
    con: &rusqlite::Connection,
    paks: &[Pak],
    by_name: &HashMap<String, usize>,
    recs: &HashMap<u64, Vec<(usize, Record)>>,
    mat: &MdlSlot,
    resolve: &dyn Fn(&str) -> Option<u64>,
) -> Vec<MdlSlot> {
    let Some(hx) = &mat.hash else { return Vec::new() };
    let Ok(h) = u64::from_str_radix(hx, 16) else { return Vec::new() };
    let Ok(bytes) = read_res_bytes(con, paks, by_name, recs, h) else {
        return Vec::new();
    };
    match material_slots(&bytes, |n| resolve(n)) {
        ViewBody::Material(slots) => slots.iter().map(|s| slot_of(con, s)).collect(),
        _ => Vec::new(),
    }
}

/// 动作列表：模型定义本身不含动作，动作挂在它所属的资源组上。
/// 查清单：hash → 组 → 该组引用的 `.ani` 名单（逐个对实体，对不上就「缺」）。
fn animations_of(con: &rusqlite::Connection, hash: u64) -> Vec<MdlSlot> {
    let Some(gid): Option<i64> = con
        .query_row(
            "SELECT gid FROM amembers WHERE hash = ?1 LIMIT 1",
            [format!("{hash:016x}")],
            |r| r.get(0),
        )
        .ok()
    else {
        return Vec::new();
    };
    let Ok(mut st) = con.prepare(
        "SELECT DISTINCT r.name FROM refs r \
         JOIN amembers m ON m.hash = r.from_hash AND m.gid = ?1 \
         WHERE r.kind = '.ani' ORDER BY r.name",
    ) else {
        return Vec::new();
    };
    let Ok(names) = st.query_map([gid], |r| r.get::<_, String>(0)) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    for name in names.flatten() {
        let hit = resolve_name(con, &name);
        let path = hit.as_ref().and_then(|(_, p)| p.clone());
        out.push(MdlSlot {
            role: "动作".to_string(),
            resolved: hit.is_some(),
            hash: hit.map(|(h, _)| format!("{h:016x}")),
            path,
            name,
        });
    }
    out
}

/// 实际解析流程（同步，跑在 spawn_blocking 里）。`pub(crate)` 供 `--probe` 无头验收。
pub(crate) fn mdl_compose_run(name: &str) -> Result<MdlComposeReply, String> {
    let (_, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = rusqlite::Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .map_err(|e| format!("只读打开资源清单失败：{e}"))?;

    let (hash, mdl_path) = find_mdl(&con, name)?;

    let cache = pak_cache();
    let paks = &cache.paks;
    let by_name = &cache.by_name;
    let recs = &cache.recs;
    if paks.is_empty() {
        return Err("没有在客户端目录里找到任何 .pak 容器".to_string());
    }
    let dec_bytes =
        read_res_bytes(&con, paks, by_name, recs, hash).map_err(|e| e)?;

    // 名字 → hash 只查只读库；绝不为好看而填占位 hash。
    let resolve = |n: &str| -> Option<u64> { resolve_name(&con, n).map(|(h, _)| h) };

    let body = mdl_summary(&dec_bytes, resolve);

    match body {
        ViewBody::Model(m) => {
            let skeletons = m.skeletons.iter().map(|s| slot_of(&con, s)).collect();
            let bodies = m
                .bodies
                .iter()
                .map(|b| {
                    let material = slot_of(&con, &b.material);
                    let texture_slots =
                        texture_slots_of(&con, paks, by_name, recs, &material, &resolve);
                    MdlBodyRow {
                        label: b.label.clone(),
                        mesh: slot_of(&con, &b.mesh),
                        material,
                        texture_slots,
                    }
                })
                .collect();
            let others = m.others.clone();
            let animations = animations_of(&con, hash);
            Ok(MdlComposeReply {
                found: true,
                note: if m.skeletons.is_empty()
                    && m.bodies.is_empty()
                    && m.others.is_empty()
                {
                    "模型定义解析成功，但里面没有读到任何组成成员。".to_string()
                } else {
                    "已现场从客户端数据解出模型组成。".to_string()
                },
                name: m.name,
                base_dir: m.base_dir,
                path: mdl_path,
                skeletons,
                bodies,
                animations,
                others,
            })
        }
        ViewBody::Unavailable { why } => Ok(MdlComposeReply {
            found: true,
            note: why,
            name: String::new(),
            base_dir: String::new(),
            path: mdl_path,
            skeletons: Vec::new(),
            bodies: Vec::new(),
            animations: Vec::new(),
            others: Vec::new(),
        }),
        other => Ok(MdlComposeReply {
            found: true,
            note: format!("这个文件不是模型定义（识别为 {other:?}），无法给出组成树。"),
            name: String::new(),
            base_dir: String::new(),
            path: mdl_path,
            skeletons: Vec::new(),
            bodies: Vec::new(),
            animations: Vec::new(),
            others: Vec::new(),
        }),
    }
}

#[tauri::command]
pub async fn mdl_compose(name: String) -> Result<MdlComposeReply, String> {
    tauri::async_runtime::spawn_blocking(move || mdl_compose_run(&name))
        .await
        .map_err(|e| e.to_string())?
}
