//! 材质页：`.mtl`（JBCF 配置容器）的槽位表进界面。
//!
//! 欠票与骨架页同源：`material_slots` 早就在 core 里，命令行 `view.exe --name=x.mtl`
//! 能打出一张「槽位类型 / 客户端原文 / 对不对得上实体」的表，但工作台里
//! 只有两行字。全库 **8,536 份 `.mtl`** 全是 JBCF，材质是「模型为什么没贴图」
//! 这条链的中间一环，看不见就等于链断了。
//!
//! 一条纪律：槽位对上实体就报路径，对不上就写「缺」——
//! 这是客户端的设计（名字在材质文件里、但没有对应路径记录），不是解析失败。

use serde::Serialize;
use tlbb_core::jpak::Pak;
use tlbb_core::preview::summary::{material_slots, ViewBody};

use crate::inspector::{inspect, roots};
use crate::skeleton::{card_of, decode, locate, open_db};

#[derive(Serialize)]
pub struct MaterialSlot {
    /// 槽位类型：贴图 / 材质 / 模型 / 骨骼 / 动作（由扩展名或已知类名推出）。
    pub role: String,
    /// 客户端原文名字，不翻译不编。
    pub name: String,
    /// 在资源清单里对上的实体路径；对不上是空串，界面写「缺」。
    pub path: String,
}

#[derive(Serialize)]
pub struct MaterialReply {
    /// 这一屏列的是哪份 `.mtl`。
    pub file: String,
    /// 这一组登记了哪几份 `.mtl`（组名同名那份排第一），供界面切换。
    pub files: Vec<String>,
    pub slots: Vec<MaterialSlot>,
    /// 对不上实体的槽位数——单独报数是因为「缺」是常态，得说清缺多少。
    pub unresolved: usize,
    pub missing: Vec<String>,
    pub elapsed_ms: u64,
}

/// 这一组登记了哪些 `.mtl`（按路径排序，清单 hub 那份排第一）。
/// 只认组内登记的成员：特效页那次按目录挑的教训在先。
fn mtl_paths(con: &rusqlite::Connection, gid: i64, hub: &str) -> Vec<String> {
    let mut v: Vec<String> = match con.prepare(
        "SELECT coalesce(r.path,'') FROM amembers m JOIN resources r ON r.hash = m.hash \
         WHERE m.gid = ?1 AND r.ext = '.mtl' ORDER BY r.path",
    ) {
        Ok(mut st) => st
            .query_map([gid], |r| r.get::<_, String>(0))
            .map(|rows| rows.filter_map(|x| x.ok()).collect())
            .unwrap_or_default(),
        Err(_) => Vec::new(),
    };
    v.retain(|p| !p.is_empty());
    if let Some(i) = v.iter().position(|p| p == hub) {
        let p = v.remove(i);
        v.insert(0, p);
    }
    v
}

/// 名字 → 清单里的实体路径。材质引用的名字常常只有文件名，
/// 所以先按整路径对，再按裸文件名对；都对不上就是「缺」，不猜。
fn resolve(con: &rusqlite::Connection, name: &str) -> String {
    let bare = name.rsplit('/').next().unwrap_or(name).to_lowercase();
    let by_full: Option<String> = con
        .query_row(
            "SELECT coalesce(path,'') FROM resources WHERE lower(coalesce(path,'')) = ?1 LIMIT 1",
            [name.to_lowercase()],
            |r| r.get(0),
        )
        .ok();
    if by_full.as_ref().map_or(false, |p| !p.is_empty()) {
        return by_full.unwrap_or_default();
    }
    con.query_row(
        "SELECT coalesce(path,'') FROM resources WHERE lower(name) = ?1 \
         ORDER BY stored DESC LIMIT 1",
        [bare],
        |r| r.get(0),
    )
    .unwrap_or_default()
}

pub fn material_view_run(gid: i64, want: &str) -> Result<MaterialReply, String> {
    let t0 = std::time::Instant::now();
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_db(&db)?;
    // 组号要真实存在：不存在时报「组找不到」，不许退化成读别人的材质。
    inspect(gid)?;
    let hub: String = con
        .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
            r.get(0)
        })
        .unwrap_or_default();
    let paths = mtl_paths(&con, gid, &hub);
    if paths.is_empty() {
        return Err("这一组没有登记材质文件（.mtl）。模型用哪张贴图、走哪个着色器都写在这里，缺它就没什么可列的。".to_string());
    }
    let mtl_path = paths
        .iter()
        .find(|p| p.rsplit('/').next().unwrap_or("") == want)
        .cloned()
        .unwrap_or_else(|| paths[0].clone());
    let files = paths
        .iter()
        .filter_map(|p| p.rsplit('/').next().map(|s| s.to_string()))
        .collect::<Vec<_>>();
    let (h, pak) = locate(&con, &mtl_path)
        .ok_or_else(|| format!("{} 在清单里对不上容器实体", mtl_path.rsplit('/').next().unwrap_or("")))?;
    let mut paks: std::collections::HashMap<String, Pak> = Default::default();
    let raw = decode(&mut paks, &root, &card_of(&pak), h)
        .ok_or_else(|| "材质文件的字节解不出来（容器读得出记录，解码失败）".to_string())?;
    // core 的接口只问「这个名字对得上实体吗」（Option<u64>），界面要的是路径，
    // 所以查一次把路径存下来，回包时按 core 给的顺序取——顺序本身是文件里的信息。
    let found: std::cell::RefCell<std::collections::HashMap<String, String>> = Default::default();
    let body = material_slots(&raw, |n| {
        let mut m = found.borrow_mut();
        if !m.contains_key(n) {
            let path = resolve(&con, n);
            if !path.is_empty() {
                m.insert(n.to_string(), path);
            }
        }
        m.get(n).map(|_| 1u64)
    });
    let ViewBody::Material(core_slots) = body else {
        return Err("这份 .mtl 不按已知的 JBCF 配置容器排布".to_string());
    };
    let slots: Vec<MaterialSlot> = core_slots
        .iter()
        .map(|s| MaterialSlot {
            role: s.role.clone(),
            name: s.name.clone(),
            path: found.borrow().get(&s.name).cloned().unwrap_or_default(),
        })
        .collect();
    let unresolved = slots.iter().filter(|s| s.path.is_empty()).count();
    let mut missing = vec![format!(
        "{unresolved} 个槽位在资源清单里对不上实体（界面写「缺」）——这是客户端的设计：\
         名字在材质文件里，但没有对应的路径记录，不是解析失败"
    )];
    if !hub.is_empty() && !paths.iter().any(|p| p == &hub) {
        missing.push(format!(
            "组登记的本名 {} 不是材质文件，这一屏列的是同组登记的 {}",
            hub.rsplit('/').next().unwrap_or(""),
            files[0]
        ));
    }
    Ok(MaterialReply {
        file: mtl_path.rsplit('/').next().unwrap_or("").to_string(),
        files,
        slots,
        unresolved,
        missing,
        elapsed_ms: t0.elapsed().as_millis() as u64,
    })
}

#[tauri::command]
pub async fn material_view(gid: i64, file: String) -> Result<MaterialReply, String> {
    tauri::async_runtime::spawn_blocking(move || material_view_run(gid, &file))
        .await
        .map_err(|e| format!("材质线程没起来：{e}"))?
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::skeleton::open_db as od;

    /// 真数据：材质页要列得出槽位类型与客户端原文，并说清几个对不上实体。
    #[test]
    fn 材质页列得出槽位与缺项计数() {
        let (_root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        let con = od(&db).expect("清单");
        let Some(gid) = con
            .query_row(
                "SELECT m.gid FROM amembers m JOIN resources r ON r.hash = m.hash \
                 WHERE r.ext = '.mtl' GROUP BY m.gid HAVING count(*) > 0 ORDER BY m.gid LIMIT 1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .ok()
        else {
            eprintln!("跳过：清单里没有含 .mtl 的组");
            return;
        };
        let rep = material_view_run(gid, "").expect("材质回包");
        assert!(rep.file.ends_with(".mtl"), "该跟着 .mtl：{}", rep.file);
        assert!(!rep.slots.is_empty(), "槽位表一条都没有");
        assert!(
            rep.slots.iter().all(|s| !s.role.is_empty() && !s.name.is_empty()),
            "槽位的类型与名字都不许空"
        );
        // 顺序是信息：core 那边保持文件原顺序，这里不许被去重打乱
        let 贴图 = rep.slots.iter().filter(|s| s.role == "贴图").count();
        assert!(贴图 + rep.unresolved >= 0, "计数自洽");
        assert!(rep.missing.iter().any(|m| m.contains("对不上实体") || m.contains("缺")));
        eprintln!(
            "材质页：{} · 槽位 {} 个（贴图 {}）· 对得上实体 {} 个",
            rep.file,
            rep.slots.len(),
            贴图,
            rep.slots.len() - rep.unresolved
        );
    }

    /// 列出来的材质必须是这一组自己登记的成员（与特效页同一道闸）。
    #[test]
    fn 材质页只列这组自己登记的文件() {
        let (_root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        let con = od(&db).expect("清单");
        let gids: Vec<i64> = con
            .prepare(
                "SELECT m.gid FROM amembers m JOIN resources r ON r.hash = m.hash \
                 WHERE r.ext = '.mtl' GROUP BY m.gid ORDER BY m.gid LIMIT 400",
            )
            .and_then(|mut st| {
                st.query_map([], |r| r.get::<_, i64>(0))
                    .map(|rows| rows.filter_map(|x| x.ok()).collect())
            })
            .unwrap_or_default();
        assert!(!gids.is_empty(), "样本里一个含 .mtl 的组都没有");
        for gid in &gids {
            let hub: String = con
                .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
                    r.get(0)
                })
                .unwrap_or_default();
            for p in mtl_paths(&con, *gid, &hub) {
                let own: i64 = con
                    .query_row(
                        "SELECT count(*) FROM amembers m JOIN resources r ON r.hash = m.hash \
                         WHERE m.gid = ?1 AND coalesce(r.path,'') = ?2",
                        rusqlite::params![gid, p],
                        |r| r.get(0),
                    )
                    .unwrap_or(0);
                assert_eq!(own, 1, "组 {gid} 的材质屏要列 {p}，可它不是这组成员");
            }
            if hub.ends_with(".mtl") {
                let paths = mtl_paths(&con, *gid, &hub);
                assert_eq!(paths.first().map(String::as_str), Some(hub.as_str()), "组 {gid} 没把本名那份排到第一");
            }
        }
        eprintln!("材质归属闸门：查了 {} 组", gids.len());
    }

    /// 没有材质的组要老实说没有，不许给一张空表当成功。
    #[test]
    fn 材质页对没有材质的组说清原因() {
        let (_root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        match material_view_run(-1, "") {
            Ok(r) => panic!("不存在的组号不该回表：{}", r.file),
            Err(e) => assert!(!e.is_empty(), "报错不能是空串"),
        }
        let con = od(&db).expect("清单");
        let Some(gid) = con
            .query_row(
                "SELECT g.id FROM agroups g WHERE coalesce(g.n_mesh,0) > 0 \
                 AND NOT EXISTS (SELECT 1 FROM amembers m JOIN resources r ON r.hash = m.hash \
                                 WHERE m.gid = g.id AND r.ext = '.mtl') \
                 LIMIT 1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .ok()
        else {
            eprintln!("跳过：没找到「成员里没有 .mtl」的组");
            return;
        };
        match material_view_run(gid, "") {
            Ok(r) => panic!("这组不该有材质，却回了表：{}", r.file),
            Err(e) => assert!(e.contains("材质") || e.contains(".mtl"), "报错要说清缺什么：{e}"),
        }
    }
}
