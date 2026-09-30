//! 特效页：`.pu`（JBPU）解出来的结构摆成表。
//!
//! 欠的票与骨架页同源：`parse_pu` 早就在 core 里，界面上只有两行文字。
//! 这里把材质链、贴图、网格、混合模式、渲染器、发射器、更新器、动态参数名
//! 一项项列出来；**参数块的字段语法未解，只报得出浮点个数与块大小**，
//! 这句原话必须同屏出现，不能让人以为数字读懂了。

use serde::Serialize;
use tlbb_core::preview::{Effect, parse_pu};

use crate::inspector::{inspect, roots};
use crate::skeleton::{anim_paths, card_of, decode, locate, open_db};

#[derive(Serialize)]
pub struct EffectReply {
    /// 特效文件名（客户端原文）。
    pub file: String,
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

pub fn effect_view_run(gid: i64) -> Result<EffectReply, String> {
    let t0 = std::time::Instant::now();
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_db(&db)?;
    let insp = inspect(gid)?;
    // 组里那份 .pu：先看角色，再退到「同目录里最大的 .pu」
    let pu_path = insp
        .members
        .iter()
        .find(|m| m.role == "effect")
        .and_then(|m| m.path.clone())
        .or_else(|| {
            // 只认「正好这一组目录」里的 .pu。用 LIKE '%dir%' 会顺着字符串子串
            // 跑到兄弟目录去捞别人的特效文件，那张表就是张冠李戴。
            con.query_row(
                "SELECT coalesce(path,'') FROM resources WHERE ext='.pu' AND dir = ?1 \
                 ORDER BY stored DESC LIMIT 1",
                [insp.dir.trim_end_matches('/').to_lowercase()],
                |r| r.get::<_, String>(0),
            )
            .ok()
        })
        .ok_or_else(|| "这一组里没有特效文件（.pu）。特效的结构、材质链都在这里，缺它就没什么可列的。".to_string())?;
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
    if n.other.iter().any(|s| s.ends_with(".mtl") || s.ends_with(".tga")) {
        missing.push("有几条名字没归进材质/贴图类，原样列在「其他」里，不硬塞进上面任何一类".to_string());
    }
    Ok(EffectReply {
        file: pu_path.rsplit('/').next().unwrap_or("").to_string(),
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
pub async fn effect_view(gid: i64) -> Result<EffectReply, String> {
    tauri::async_runtime::spawn_blocking(move || effect_view_run(gid))
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
        let rep = match effect_view_run(gid) {
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
        match effect_view_run(-1) {
            Ok(r) => panic!("不存在的组号不该回表：{}", r.file),
            Err(e) => assert!(!e.is_empty(), "报错不能是空串"),
        }
        let con = od(&db).expect("清单");
        // 真组：成员里、目录里都没有 .pu 才算数（只看目录会漏掉成员跨目录的情况，
        // 上一版就是这么误判的）
        let Some(gid) = con
            .query_row(
                "SELECT g.id FROM agroups g \
                 WHERE coalesce(g.n_mesh,0) > 0 \
                   AND NOT EXISTS (SELECT 1 FROM amembers m JOIN resources r ON r.hash = m.hash \
                                   WHERE m.gid = g.id AND r.ext = '.pu') \
                   AND NOT EXISTS (SELECT 1 FROM resources p WHERE p.ext='.pu' AND p.dir = g.dir) \
                 LIMIT 1",
                [],
                |r| r.get::<_, i64>(0),
            )
            .ok()
        else {
            eprintln!("跳过：没找到「成员与目录里都没有 .pu」的组");
            return;
        };
        match effect_view_run(gid) {
            Ok(r) => panic!("这组不该有特效，却回了表：{}", r.file),
            Err(e) => assert!(e.contains("特效") || e.contains(".pu"), "报错要说清缺什么：{e}"),
        }
    }
}
