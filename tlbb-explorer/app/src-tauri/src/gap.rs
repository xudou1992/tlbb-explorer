//! 容器与清单的缺口体检：pak 里有多少条，`resources.db` 里登记了多少条。
//!
//! 为什么要这一层：清单是某一刻扫容器落下来的快照。客户端打补丁（`data_1.pak`
//! 又长了几代索引）或者换机后没重建库，容器里就有文件是清单不认识的——「浏览」
//! 按容器列文件，看得见；「资产检索 / 反查」按清单查，看不见。两边不一致而工具
//! 不吭声，用户只会以为「客户端里没有这个文件」。
//!
//! 这里只做一件事：把差多少条说出来，并指出去哪重建（README「首次运行」§2）。
//! 不替用户动库——重建 145MB 的清单是几分钟的活儿，而且是口径变更。

use std::collections::HashSet;
use std::path::Path;
use std::sync::OnceLock;

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use tlbb_core::jpak::Pak;

/// 缺口账面。`container_*` 来自直接扫 6 个容器的索引，`db_resources` 来自清单。
#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct Gap {
    /// 容器里的索引槽位总数（含同 hash 的多份副本）。
    pub container_records: usize,
    /// 容器里去重后的 hash 数——清单理论上该有的条数。
    pub container_unique: usize,
    /// 清单实际登记了多少条。
    pub db_resources: usize,
    /// 容器有、清单没有的 hash 数（去重后逐一对过，不是两数相减的估算）。
    pub uncovered: usize,
    /// 扫了哪几个容器、有没有打不开的。
    pub paks: usize,
    pub unreadable: Vec<String>,
}

/// 一次进程内算一遍：扫 6 个容器要 mmap 几 GB 的索引区，不值得每次点界面都重来。
static CACHED: OnceLock<Option<Gap>> = OnceLock::new();

fn scan(root: &Path, db: &Path) -> Option<Gap> {
    let mut names: Vec<String> = Vec::new();
    for i in 0.. {
        let stem = if i == 0 { "data".to_string() } else { format!("data{i}") };
        if root.join(format!("{stem}.pak")).is_file() {
            names.push(stem);
        } else {
            break;
        }
        if i > 40 {
            break; // 防御：客户端不会有一百个容器，别把目录遍历当成循环
        }
    }
    // 更新器写的补丁包按约定叫 data_1.pak（不在 dataN 的连号里）。
    if root.join("data_1.pak").is_file() {
        names.push("data_1".into());
    }
    if names.is_empty() {
        return None;
    }
    let con = Connection::open_with_flags(
        db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .ok()?;

    let mut uniq: HashSet<u64> = HashSet::new();
    let mut records = 0usize;
    let mut unreadable = Vec::new();
    for stem in &names {
        match Pak::open(&root.join(format!("{stem}.pak"))) {
            Ok(pak) => {
                for rec in pak.records() {
                    records += 1;
                    uniq.insert(rec.hash);
                }
            }
            Err(e) => unreadable.push(format!("{stem}.pak：{e}")),
        }
    }

    let db_hashes: HashSet<u64> = con
        .prepare("SELECT hash FROM resources")
        .ok()
        .and_then(|mut st| {
            st.query_map([], |r| r.get::<_, String>(0)).ok().map(|rows| {
                rows.filter_map(|x| x.ok())
                    .filter_map(|s| u64::from_str_radix(s.trim_start_matches("0x"), 16).ok())
                    .collect::<HashSet<u64>>()
            })
        })
        .unwrap_or_default();
    let db_resources = con
        .query_row("SELECT COUNT(*) FROM resources", [], |r| r.get::<_, i64>(0))
        .unwrap_or(0) as usize;
    // 逐一对过，不用「两数相减」估算：清单里也可能有容器已经不认识的旧条目，
    // 那种情况下相减会把两个方向的差混成一个数。
    let uncovered = uniq.iter().filter(|h| !db_hashes.contains(h)).count();

    Some(Gap {
        container_records: records,
        container_unique: uniq.len(),
        db_resources,
        uncovered,
        paks: names.len(),
        unreadable,
    })
}

fn gap() -> Option<&'static Gap> {
    CACHED.get_or_init(|| {
        let (root, db) = crate::inspector::roots();
        scan(&root, &db)
    }).as_ref()
}

/// 给界面看的缺口体检回包。没有容器 / 没有清单时回一句实话，不编数字。
#[tauri::command]
pub fn catalog_gap() -> Result<serde_json::Value, String> {
    match gap() {
        Some(g) => Ok(serde_json::to_value(g).map_err(|e| e.to_string())?),
        None => Err("扫不到容器或清单：本机没放客户端，或用 TLBB_ROOT / TLBB_DB 指过来".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 真数据体检：容器扫得出数，缺口与「容器去重 − 清单登记」两个方向都对得上。
    /// 没有客户端的机器上跳过（与 browse 那几个用例同一降级口径）。
    #[test]
    fn 缺口算得出来且不用两数相减糊弄() {
        let (root, db) = crate::inspector::roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端 pak 或资源清单");
            return;
        }
        let g = scan(&root, &db).expect("扫得出来");
        assert!(g.paks >= 1, "至少该扫到一个容器");
        assert!(g.container_records >= g.container_unique, "槽位数不可能少于去重后的 hash 数");
        assert!(g.unreadable.is_empty(), "有容器打不开：{:?}", g.unreadable);
        // uncovered 是「容器有、清单没有」，它不可能超过容器去重数。
        assert!(g.uncovered <= g.container_unique, "{g:?}");
        eprintln!(
            "容器 {} 个 · 槽位 {} · 去重 {} · 清单 {} · 清单缺 {} 条",
            g.paks, g.container_records, g.container_unique, g.db_resources, g.uncovered
        );
    }
}
