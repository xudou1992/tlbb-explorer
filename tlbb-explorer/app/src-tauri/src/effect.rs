//! 特效页：`.pu`（JBPU）解出来的结构摆成表。
//!
//! 欠的票与骨架页同源：`parse_pu` 早就在 core 里，界面上只有两行文字。
//! 这里把材质链、贴图、网格、混合模式、渲染器、发射器、更新器、动态参数名
//! 一项项列出来；**参数块的字段语法未解，只报得出浮点个数与块大小**，
//! 这句原话必须同屏出现，不能让人以为数字读懂了。
//!
//! 取哪一份 `.pu` 只认组内登记的成员：一个组名下同目录可能躺着几千份特效
//! （`data/effect/pu_other` 实测 3,326 份），按目录挑就是张冠李戴。

use serde::Serialize;
use tlbb_core::preview::{Effect, parse_pu};

use crate::inspector::{inspect, roots};
use crate::skeleton::{anim_paths, card_of, decode, locate, open_db};

#[derive(Serialize)]
pub struct EffectReply {
    /// 特效文件名（客户端原文）。
    pub file: String,
    /// 这一组登记了哪些 `.pu`（文件名，组名同名那份排第一），供界面切换。
    pub files: Vec<String>,
    /// 特效自己的名字、分组、层名——都是文件里的原文，不是猜的。
    pub name: String,
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
    /// 认不出类别的驻留字符串，原样带着（不塞进上面任何一类充数）。
    pub other: Vec<String>,
    pub string_total: usize,
    /// 参数块：字段语法未解，只报数量与大小。
    pub param_floats: usize,
    pub param_bytes: usize,
    /// 这个特效组旁边有没有动作文件（`.pu` 自己不带关键帧）。
    pub anims: usize,
    pub missing: Vec<String>,
    pub elapsed_ms: u64,
}

/// 这一组登记了哪些 `.pu`，按路径排序（顺序不能靠 SQLite 心情），
/// 组的本名那份排到最前——它才是这个屏该默认打开的文件。
fn pu_paths(con: &rusqlite::Connection, gid: i64, hub: &str) -> Vec<String> {
    let mut v: Vec<String> = match con.prepare(
        "SELECT coalesce(r.path,'') FROM amembers m JOIN resources r ON r.hash = m.hash \
         WHERE m.gid = ?1 AND r.ext = '.pu' ORDER BY r.path",
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

pub fn effect_view_run(gid: i64, want: &str) -> Result<EffectReply, String> {
    let t0 = std::time::Instant::now();
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_db(&db)?;
    // 组号要真实存在：不存在时报「组找不到」，不许退化成读一份无关的 .pu。
    inspect(gid)?;
    // 组的「本名」那份：清单登记组时用的 hub 路径，与组同名。
    let hub: String = con
        .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
            r.get(0)
        })
        .unwrap_or_default();
    let paths = pu_paths(&con, gid, &hub);
    if paths.is_empty() {
        return Err("这一组没有登记特效文件（.pu）。特效的结构、材质链都在这里，缺它就没什么可列的。".to_string());
    }
    // 换特效只在这组登记的那几份里换；名字对不上就回到第一份（组名同名那份），不给空白页。
    let pu_path = paths
        .iter()
        .find(|p| p.rsplit('/').next().unwrap_or("") == want)
        .cloned()
        .unwrap_or_else(|| paths[0].clone());
    let files = paths
        .iter()
        .filter_map(|p| p.rsplit('/').next().map(|s| s.to_string()))
        .collect::<Vec<_>>();
    let (h, pak) = locate(&con, &pu_path)
        .ok_or_else(|| format!("{} 在清单里对不上容器实体", pu_path.rsplit('/').next().unwrap_or("")))?;
    let mut paks = Default::default();
    let raw = decode(&mut paks, &root, &card_of(&pak), h)
        .ok_or_else(|| "特效文件的字节解不出来（容器读得出记录，解码失败）".to_string())?;
    let e: Effect = parse_pu(&raw).ok_or_else(|| "这份 .pu 不按已知的 JBPU 布局排布".to_string())?;
    let n = &e.names;
    let anims = anim_paths(&con, &pu_path).len();
    let mut missing = vec![
        format!(
            "参数块的字段语法未解：块里 {} 字节、{} 个像浮点的数，说清哪个数是干什么的还没做到",
            e.param_bytes, e.param_floats
        ),
        "播放未做：材质链与发射器形状读得出来，但没有参数含义就摆不出随时间变化的效果".to_string(),
    ];
    if !hub.is_empty() && !paths.iter().any(|p| p == &hub) {
        missing.push(format!(
            "组登记的本名 {} 不是特效文件（或不在这组成员里），这一屏列的是同组登记的 {}；同组一共 {} 份",
            hub.rsplit('/').next().unwrap_or(""),
            files[0],
            files.len()
        ));
    }
    if n.other.iter().any(|s| s.ends_with(".mtl") || s.ends_with(".tga")) {
        missing.push("有几条名字没归进材质/贴图类，原样列在「其他」里，不硬塞进上面任何一类".to_string());
    }
    Ok(EffectReply {
        file: pu_path.rsplit('/').next().unwrap_or("").to_string(),
        files,
        name: n.name.clone(),
        group: n.group.clone(),
        label: n.label.clone(),
        materials: n.materials.clone(),
        textures: n.textures.clone(),
        meshes: n.meshes.clone(),
        blends: n.blends.clone(),
        renderers: n.renderers.clone(),
        emitters: n.emitters.clone(),
        updaters: n.updaters.clone(),
        dynamics: n.dynamics.clone(),
        other: n.other.clone(),
        string_total: e.strings.len(),
        param_floats: e.param_floats,
        param_bytes: e.param_bytes,
        anims,
        missing,
        elapsed_ms: t0.elapsed().as_millis() as u64,
    })
}

#[tauri::command]
pub async fn effect_view(gid: i64, file: String) -> Result<EffectReply, String> {
    tauri::async_runtime::spawn_blocking(move || effect_view_run(gid, &file))
        .await
        .map_err(|e| format!("特效线程没起来：{e}"))?
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::skeleton::open_db as od;

    /// 真数据：特效页要把材质链与各类类名列全，并同屏写明参数块未解。
    #[test]
    fn 特效页回包列得出材质链与未解项() {
        let (root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        let con = od(&db).expect("清单");
        let Some(gid) = con
            .query_row(
                "SELECT id FROM agroups WHERE kind = 'effect' AND n > 0 LIMIT 1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .ok()
        else {
            eprintln!("跳过：清单里没有特效组");
            return;
        };
        let rep = match effect_view_run(gid, "") {
            Ok(r) => r,
            Err(e) => {
                eprintln!("跳过：这个特效组读不开（{e}）");
                return;
            }
        };
        assert!(rep.file.ends_with(".pu"), "该跟着 .pu：{}", rep.file);
        assert!(rep.string_total > 0, "驻留字符串一条都没有");
        assert!(
            !rep.materials.is_empty() || !rep.textures.is_empty() || !rep.meshes.is_empty(),
            "材质链全空，多半是分类漏了：{:?}",
            &rep.other[..rep.other.len().min(5)]
        );
        assert!(!rep.name.is_empty(), "特效自己的名字该在字符串表第 0 条");
        assert!(rep.missing.iter().any(|m| m.contains("参数块")));
        assert!(rep.missing.iter().any(|m| m.contains("播放")));
        let _ = root;
        eprintln!(
            "特效页：{} · 字符串 {} 条 · 材质 {} · 贴图 {} · 网格 {} · 渲染器 {:?} · 发射器 {:?} · 参数块 {}B/{} 浮点",
            rep.file,
            rep.string_total,
            rep.materials.len(),
            rep.textures.len(),
            rep.meshes.len(),
            rep.renderers,
            rep.emitters,
            rep.param_bytes,
            rep.param_floats
        );
    }

    /// 没有特效文件的组要老实说没有，不许给一张空表当成功。
    #[test]
    fn 特效页对没有特效的组说清原因() {
        let (_root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        // 不存在的组号：确定性的错误路径，不靠挑数据
        match effect_view_run(-1, "") {
            Ok(r) => panic!("不存在的组号不该回表：{}", r.file),
            Err(e) => assert!(!e.is_empty(), "报错不能是空串"),
        }
        let con = od(&db).expect("清单");
        // 成员里没有 .pu 的组。上一版会退到「同目录挑一份」，而实测这种退路
        // 救不了任何组（全库没有「成员无 .pu 且组目录恰好只有一份 .pu」的组），
        // 只会从 3,326 份共享目录里挑到别人头上。
        let Some(gid) = con
            .query_row(
                "SELECT g.id FROM agroups g \
                 WHERE coalesce(g.n_mesh,0) > 0 \
                   AND NOT EXISTS (SELECT 1 FROM amembers m JOIN resources r ON r.hash = m.hash \
                                   WHERE m.gid = g.id AND r.ext = '.pu') \
                 LIMIT 1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .ok()
        else {
            eprintln!("跳过：没找到「成员里没有 .pu」的组");
            return;
        };
        match effect_view_run(gid, "") {
            Ok(r) => panic!("这组不该有特效，却回了表：{}", r.file),
            Err(e) => assert!(e.contains("特效") || e.contains(".pu"), "报错要说清缺什么：{e}"),
        }
    }

    /// 一个组名下可以登记好几份 .pu：默认必须是与组同名的那份（清单登记的 hub），
    /// 其余的进选择条；点谁就列谁，不许列着 A 的表却写着 B 的名字。
    #[test]
    fn 多份特效的组默认列本名那份且切换只在这几份里() {
        let (_root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        let con = od(&db).expect("清单");
        let Some((gid, hub)) = con
            .query_row(
                "SELECT g.id, g.hub_path FROM agroups g \
                 JOIN resources r ON r.path = g.hub_path AND r.ext = '.pu' \
                 WHERE (SELECT count(*) FROM amembers m JOIN resources rr ON rr.hash = m.hash \
                        WHERE m.gid = g.id AND rr.ext = '.pu') > 1 \
                 ORDER BY g.id LIMIT 1",
                [],
                |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?)),
            )
            .ok()
        else {
            eprintln!("跳过：清单里没有「登记了多份 .pu」的组");
            return;
        };
        let want = hub.rsplit('/').next().unwrap_or("").to_string();
        let rep = effect_view_run(gid, "").expect("本名那份该读得开");
        assert_eq!(rep.file, want, "默认该是与组同名的那份");
        assert_eq!(rep.files.first().map(String::as_str), Some(want.as_str()), "选择条第一位也该是它");
        let members: i64 = con
            .query_row(
                "SELECT count(*) FROM amembers m JOIN resources r ON r.hash = m.hash \
                 WHERE m.gid = ?1 AND r.ext = '.pu'",
                [gid],
                |r| r.get(0),
            )
            .unwrap_or(0);
        assert_eq!(rep.files.len(), members as usize, "选择条漏了同组登记的特效");
        eprintln!("特效页选择条：{} · 同组 {} 份", rep.file, rep.files.len());
        // 换一份：表头文件名必须跟着换
        let other = rep.files.iter().find(|f| **f != want).cloned().unwrap_or_default();
        let switched = effect_view_run(gid, &other).expect("切换后的那份该读得开");
        assert_eq!(switched.file, other, "点了一份却列的另一份");
    }

    /// 张冠李戴闸门：任何一组列出来的特效，都必须是这一组自己登记的成员。
    /// 上一版按「同目录里 stored 最大」挑（stored 是压缩标志不是大小），
    /// 在 data/effect/pu_other 这种 3,326 份共享的目录里会挑到别人的文件。
    #[test]
    fn 特效页只列这组自己登记的文件() {
        let (_root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        let con = od(&db).expect("清单");
        let gids: Vec<i64> = con
            .prepare(
                "SELECT m.gid FROM amembers m JOIN resources r ON r.hash = m.hash \
                 WHERE r.ext = '.pu' GROUP BY m.gid ORDER BY m.gid LIMIT 600",
            )
            .and_then(|mut st| {
                st.query_map([], |r| r.get::<_, i64>(0))
                    .map(|rows| rows.filter_map(|x| x.ok()).collect())
            })
            .unwrap_or_default();
        if gids.is_empty() {
            eprintln!("跳过：清单里没有含 .pu 的组");
            return;
        }
        let mut multi = 0;
        for gid in &gids {
            let hub: String = con
                .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
                    r.get(0)
                })
                .unwrap_or_default();
            let paths = pu_paths(&con, *gid, &hub);
            assert!(!paths.is_empty(), "组 {gid} 明明登记了 .pu 成员，这里却挑不出");
            for p in &paths {
                let own: i64 = con
                    .query_row(
                        "SELECT count(*) FROM amembers m JOIN resources r ON r.hash = m.hash \
                         WHERE m.gid = ?1 AND coalesce(r.path,'') = ?2",
                        rusqlite::params![gid, p],
                        |r| r.get(0),
                    )
                    .unwrap_or(0);
                assert_eq!(own, 1, "组 {gid} 的特效屏上要列 {p}，可它不是这组成员");
            }
            if hub.ends_with(".pu") {
                assert_eq!(paths[0], hub, "组 {gid} 没把本名那份排到第一");
            }
            if paths.len() > 1 {
                multi += 1;
            }
        }
        eprintln!("特效归属闸门：查了 {} 组，其中 {} 组登记了多份 .pu", gids.len(), multi);
        assert!(multi > 0, "样本里一份多份的组都没有，这条闸门等于没验");
    }
}
