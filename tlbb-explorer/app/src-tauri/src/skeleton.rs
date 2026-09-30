//! 骨架与动作的界面回包。
//!
//! 为什么要这一页：`parse_nodes` / `parse_ani` 早就进 core 了，但界面上只剩
//! 一行字「骨架节点 36 个」。数据解出来了却没地方看，等于没做完（v0.4.4 补的票）。
//!
//! 这里只报**已被闸门证明过的东西**：
//! - 节点：`.mesh` 尾部 96 字节记录 = 名字 + 绑定矩阵（D3DX 行向量，末行是绑定位移）
//! - 声明骨骼数：`.mesh` 头部 `0x110` 的 u32（与同组 `.ani` 轨道数一致，有闸门）
//! - 动作：每条 `.ani` 的骨骼数 / 帧数 / 帧率刻度 / 会动的骨数
//!
//! 没证的东西一律写进 `missing`，不猜：**父骨链未解**（所以画不出骨架连线，只能列点）。
//! 蒙皮权重**已解**——2026-09-30 实测在 `.mesh` 里，按骨组织成「影响顶点表」
//! （见 `preview::SkinInfluence`）；此前写的「权重不在 .mesh」是按「每顶点 4 影响」
//! 那一种编码穷举出来的，判早了。帧率刻度的含义仍未证。

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{bone_count, parse_ani, parse_nodes};

use crate::inspector::{inspect, roots};

#[derive(Serialize)]
#[derive(Clone)]
pub struct BoneRow {
    /// 客户端原文骨名，不翻译不编造。
    pub name: String,
    /// 绑定位移（模型坐标）：矩阵末行 (tx,ty,tz)。`None` = 这根骨在 `.mesh` 里没有记录。
    pub pos: Option<[f32; 3]>,
    /// 基向量长度（等比缩放）；1.0 附近是正常单位。
    pub scale: Option<f32>,
    /// 这根骨的名字从哪来：`mesh`（节点记录）、`ani`（只有轨道名单）、`mesh+ani`（两边都有）。
    pub source: String,
    /// 这根骨影响多少个顶点（0 = 这条记录后面没带影响表，根骨就是这样）。
    pub skin: usize,
}

#[derive(Serialize)]
pub struct AnimRow {
    pub file: String,
    pub bones: usize,
    pub frames: usize,
    /// 帧率刻度：样本恒 40.0，含义未证，原样带着不换算成秒。
    pub tick: f32,
    /// 真正在动的骨数（有一条轨道逐帧数值不完全相同）。
    pub moving: usize,
}

#[derive(Serialize)]
pub struct SkeletonReply {
    /// 骨架来自哪份 `.mesh`（客户端原文名）。
    pub mesh: String,
    /// 这一组登记了哪几份 `.mesh`（组名同名那份排第一），供界面切换。
    pub meshes: Vec<String>,
    /// `.mesh` 头部声明的骨骼根数。
    pub declared: usize,
    pub nodes: Vec<BoneRow>,
    /// 带影响顶点表的骨有几根（0 = 这份网格不跟骨走）。
    pub skin_bones: usize,
    /// 所有骨的（顶点-骨）绑定对总数——不是顶点数，一个顶点可以被几根骨同时影响。
    pub skin_pairs: usize,
    pub animations: Vec<AnimRow>,
    /// 一份文件里没认出节点记录时给的原因，人话。
    pub note: String,
    pub missing: Vec<String>,
    pub elapsed_ms: u64,
}

/// 容器名归一：清单里 `pak` 存裸名（`data`），开文件要 `data.pak`。
pub(crate) fn card_of(pak: &str) -> String {
    if pak.ends_with(".pak") {
        pak.to_string()
    } else {
        format!("{pak}.pak")
    }
}

pub(crate) fn open_db(db: &std::path::Path) -> Result<Connection, String> {
    Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .map_err(|e| format!("资源清单打不开：{e}"))
}

/// 按完整路径取一条资源的 (hash, 容器)。
pub(crate) fn locate(con: &Connection, path: &str) -> Option<(u64, String)> {
    con.query_row(
        "SELECT hash, coalesce(pak,'') FROM resources WHERE path = ?1 AND stored > 0 LIMIT 1",
        [path],
        |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
    )
    .ok()
    .and_then(|(h, p)| u64::from_str_radix(&h, 16).ok().map(|h| (h, p)))
}

/// 同组动作：`<组目录>/ani/*.ani`。
/// 按目录而不是按名字子串捞——部件网格名带 `_yifu_001` 这类后缀，动作名不带。
pub(crate) fn anim_paths(con: &Connection, mesh_path: &str) -> Vec<String> {
    let dir = match mesh_path.rfind('/') {
        Some(i) => &mesh_path[..i],
        None => return Vec::new(),
    };
    let mut stmt = match con.prepare(
        "SELECT coalesce(path,'') FROM resources WHERE ext='.ani' AND path LIKE ?1 ORDER BY path",
    ) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    stmt.query_map([format!("%{dir}/ani/%")], |r| r.get::<_, String>(0))
        .map(|rows| rows.flatten().collect())
        .unwrap_or_default()
}

pub(crate) fn decode(paks: &mut std::collections::HashMap<String, Pak>, root: &std::path::Path, card: &str, hash: u64) -> Option<Vec<u8>> {
    if !paks.contains_key(card) {
        paks.insert(card.to_string(), Pak::open(root.join(card)).ok()?);
    }
    let p = paks.get(card)?;
    let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
    payload::decode(p, &rec).ok().map(|d| d.bytes)
}

/// 一条轨道是否真的在动：任何一帧与首帧不同就算。
/// 只比首末两帧会漏掉「动完回到原位」的骨（挥手、点头这类动作首末相同），
/// 那样报出来的「会动的骨」会偏少，宁可从左算到右。
fn track_moves(rot: &[[f32; 4]], pos: &[[f32; 3]]) -> bool {
    let Some((first, rest)) = rot.split_first() else {
        return false;
    };
    let Some((p0, prest)) = pos.split_first() else {
        return false;
    };
    let moved_q = rest.iter().any(|q| {
        q.iter()
            .zip(first.iter())
            .any(|(a, b)| (a - b).abs() > 1e-5)
    });
    let moved_p = prest.iter().any(|p| {
        p.iter()
            .zip(p0.iter())
            .any(|(a, b)| (a - b).abs() > 1e-5)
    });
    moved_q || moved_p
}

/// 这一组登记了哪些 `.mesh`（完整路径，按路径排序，清单 hub 那份排第一）。
/// 只认组内登记的成员：特效页那次教训在先，按目录挑会挑到兄弟目录的网格。
fn mesh_paths(con: &Connection, gid: i64, hub: &str, dir: &str) -> Vec<String> {
    let mut v: Vec<String> = match con.prepare(
        "SELECT coalesce(r.path,'') FROM amembers m JOIN resources r ON r.hash = m.hash \
         WHERE m.gid = ?1 AND r.ext = '.mesh' ORDER BY r.path",
    ) {
        Ok(mut st) => st
            .query_map([gid], |r| r.get::<_, String>(0))
            .map(|rows| rows.filter_map(|x| x.ok()).collect())
            .unwrap_or_default(),
        Err(_) => Vec::new(),
    };
    v.retain(|p| !p.is_empty());
    if v.is_empty() {
        // 成员里一份网格都没有时，才允许看目录——且只在这目录**恰好一份** .mesh
        // 的时候看；多份就没法判定是哪一份，宁可不列。
        let one: Option<String> = con
            .query_row(
                "SELECT coalesce(path,'') FROM resources WHERE ext='.mesh' AND dir = ?1 \
                 HAVING count(*) = 1",
                [dir.trim_end_matches('/').to_lowercase()],
                |r| r.get::<_, String>(0),
            )
            .ok();
        v = one.into_iter().collect();
    }
    if let Some(i) = v.iter().position(|p| p == hub) {
        let p = v.remove(i);
        v.insert(0, p);
    }
    v
}

pub fn skeleton_view_run(gid: i64, want: &str) -> Result<SkeletonReply, String> {
    let t0 = std::time::Instant::now();
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_db(&db)?;
    let insp = inspect(gid)?;
    let hub: String = con
        .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
            r.get(0)
        })
        .unwrap_or_default();
    let paths = mesh_paths(&con, gid, &hub, &insp.dir);
    if paths.is_empty() {
        return Err("这一组里没有网格文件，骨架跟着网格走，没有网格就没有骨架。".to_string());
    }
    // 换一份网格：只在这组登记的那几份里换；名字对不上回到第一份（组名同名那份）
    let mesh_path = paths
        .iter()
        .find(|p| p.rsplit('/').next().unwrap_or("") == want)
        .cloned()
        .unwrap_or_else(|| paths[0].clone());
    let meshes = paths
        .iter()
        .filter_map(|p| p.rsplit('/').next().map(|s| s.to_string()))
        .collect::<Vec<_>>();

    let mut paks: std::collections::HashMap<String, Pak> = Default::default();
    let mut nodes = Vec::new();
    let mut declared = 0usize;
    let mut with_skin = 0usize;
    let mut touched = 0usize;
    let mut note = String::new();
    if let Some((h, pak)) = locate(&con, &mesh_path) {
        if let Some(raw) = decode(&mut paks, &root, &card_of(&pak), h) {
            declared = bone_count(&raw).unwrap_or(0);
            let got = parse_nodes(&raw);
            nodes = got
                .iter()
                .map(|nd| BoneRow {
                    name: nd.name.clone(),
                    pos: Some([nd.bind[12], nd.bind[13], nd.bind[14]]),
                    scale: Some(
                        (nd.bind[0] * nd.bind[0] + nd.bind[1] * nd.bind[1] + nd.bind[2] * nd.bind[2])
                            .sqrt(),
                    ),
                    skin: nd.skin.as_ref().map_or(0, |s| s.vertices.len()),
                    source: "mesh".to_string(),
                })
                .collect();
            with_skin = nodes.iter().filter(|n| n.skin > 0).count();
            touched = nodes.iter().map(|n| n.skin).sum();
            if nodes.is_empty() {
                note = "这份网格是静态的：文件里没有骨架节点表（几何照旧能看，只是没有骨）。"
                    .to_string();
            }
        } else {
            note = "网格字节解不出来（容器读得出记录但解码失败），这一页先空着。".to_string();
        }
    } else {
        note = "清单里对不上这份网格的实体（路径有、容器里没有对应记录）。".to_string();
    }

    let mut animations = Vec::new();
    let mut roster: Vec<String> = Vec::new();
    for p in anim_paths(&con, &mesh_path) {
        let name = p.rsplit('/').next().unwrap_or("").to_string();
        let Some((h, pak)) = locate(&con, &p) else { continue };
        let Some(raw) = decode(&mut paks, &root, &card_of(&pak), h) else { continue };
        let Some(a) = parse_ani(&raw) else { continue };
        if roster.is_empty() {
            // 第一条动作的轨道名单就是这具骨架的骨序：声明 46 根、`.mesh` 只给 32 条矩阵，
            // 差的那些骨**名字在这里有**，不并进来就等于界面上看不见。
            roster = a.tracks.iter().map(|t| t.bone.clone()).collect();
        }
        let moving = a
            .tracks
            .iter()
            .filter(|t| track_moves(&t.rotations, &t.positions))
            .count();
        animations.push(AnimRow {
            file: name,
            bones: a.bones,
            frames: a.frames,
            tick: a.tick,
            moving,
        });
    }

    // 骨表 = `.ani` 轨道名单（骨序）+ `.mesh` 里多出来的记录（origin/top 这类没有轨道的）
    if !roster.is_empty() {
        let mut rows: Vec<BoneRow> = Vec::with_capacity(roster.len() + nodes.len());
        for (i, nm) in roster.iter().enumerate() {
            match nodes.iter().find(|n| &n.name == nm) {
                Some(n) => rows.push(BoneRow { source: "mesh+ani".to_string(), ..n.clone() }),
                None => rows.push(BoneRow {
                    name: if nm.is_empty() { format!("未命名骨 #{i}") } else { nm.clone() },
                    pos: None,
                    scale: None,
                    skin: 0,
                    source: "ani".to_string(),
                }),
            }
        }
        for n in nodes.iter().filter(|n| !roster.contains(&n.name)) {
            rows.push(n.clone());
        }
        nodes = rows;
    }
    let mut missing = vec![
        "父骨链未解：只知道每根骨在模型里的位置，不知道谁挂谁，所以这里画不出骨架连线，只能列点".to_string(),
    ];
    if with_skin > 0 {
        missing.push(format!(
            "播放还差的就是这条父骨链：这份网格的权重已经按骨读出（{} 根骨、{} 个顶点对），\
             可逐骨变换要沿父链相乘，链没解出来，模型还是不能跟着摆姿势",
            with_skin, touched
        ));
    } else {
        missing.push(
            "这一份网格没有影响顶点表（同一只怪的衣服那份有）：蒙皮权重是按份登记的，\
             换一份网格看得到"
                .to_string(),
        );
    }
    if !animations.is_empty() {
        missing.push("帧率刻度（样本恒 40.0）到底是每秒 tick 还是别的，未证——所以不换算成秒".to_string());
    }
    let 带矩阵 = nodes.iter().filter(|n| n.pos.is_some()).count();
    if declared > 带矩阵 {
        missing.push(format!(
            "{declared} 根骨里只有 {带矩阵} 根在 `.mesh` 里有绑定矩阵：其余 {} 根的名字在 `.ani` 的轨道名单里，\
             矩阵不在节点表里——它们在这份文件里以名字挂在别的记录后面（一张 32 字节步长的名单），\
             那张名单哪几条算子骨还没对上",
            declared - 带矩阵
        ));
    }

    Ok(SkeletonReply {
        mesh: mesh_path.rsplit('/').next().unwrap_or("").to_string(),
        meshes,
        declared,
        nodes,
        skin_bones: with_skin,
        skin_pairs: touched,
        animations,
        note,
        missing,
        elapsed_ms: t0.elapsed().as_millis() as u64,
    })
}

#[tauri::command]
pub async fn skeleton_view(gid: i64, mesh: String) -> Result<SkeletonReply, String> {
    tauri::async_runtime::spawn_blocking(move || skeleton_view_run(gid, &mesh))
        .await
        .map_err(|e| format!("骨架线程没起来：{e}"))?
}

// ------------------------------------------------------------------ 动作页
//
// 一次把整条动作的关键帧发过去，前端拖游标本地取帧：逐帧问后端会变成
// 「动一下滑块等一次 IPC」，比看不到更烦。

#[derive(Serialize)]
pub struct TrackSeries {
    pub bone: String,
    /// 每帧一个单位四元数。
    pub rotations: Vec<[f32; 4]>,
    /// 每帧一个位移（骨骼局部量级 0.01~0.9，不是世界坐标）。
    pub positions: Vec<[f32; 3]>,
    /// 每帧一个缩放（样本恒 1.0，含义未证，原样带着）。
    pub scales: Vec<f32>,
}

#[derive(Serialize)]
pub struct AnimReply {
    pub file: String,
    /// 同组还有哪些动作，供界面切换。
    pub files: Vec<String>,
    pub bones: usize,
    pub frames: usize,
    /// 帧率刻度：样本恒 40.0，含义未证——界面不许换算成秒。
    pub tick: f32,
    pub moving: usize,
    pub tracks: Vec<TrackSeries>,
    pub missing: Vec<String>,
    pub elapsed_ms: u64,
}

/// 浮点留 5 位小数：源数据是 f32，界面读数不需要 18 个字符。
fn q5(v: f32) -> f32 {
    if !v.is_finite() {
        return v;
    }
    (v as f64 * 1e5).round() as f32 / 1e5 as f32
}

fn series(a: &tlbb_core::preview::Anim) -> Vec<TrackSeries> {
    a.tracks
        .iter()
        .map(|t| TrackSeries {
            bone: t.bone.clone(),
            rotations: t
                .rotations
                .iter()
                .map(|q| q.map(q5))
                .collect(),
            positions: t.positions.iter().map(|p| p.map(q5)).collect(),
            scales: t.scales.iter().copied().map(q5).collect(),
        })
        .collect()
}

pub fn anim_view_run(gid: i64, want: &str) -> Result<AnimReply, String> {
    let t0 = std::time::Instant::now();
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_db(&db)?;
    let insp = inspect(gid)?;
    // 动作跟着组里那份网格走：同组 `<目录>/ani/*.ani`
    let mesh_path = insp
        .members
        .iter()
        .find(|m| m.role == "mesh")
        .and_then(|m| m.path.clone())
        .ok_or_else(|| "这一组里没有网格文件，动作是套在骨架上的，先有骨架才谈得上动作。".to_string())?;
    let files = anim_paths(&con, &mesh_path)
        .iter()
        .filter_map(|p| p.rsplit('/').next().map(|s| s.to_string()))
        .collect::<Vec<_>>();
    if files.is_empty() {
        return Err("这一组旁边没有 ani/ 目录，客户端没给它配动作文件。".to_string());
    }
    // 空 want 或名字对不上时取第一条，别让人面对一个空白页
    let pick = files
        .iter()
        .find(|f| *f == want)
        .cloned()
        .unwrap_or_else(|| files[0].clone());
    let full = anim_paths(&con, &mesh_path)
        .into_iter()
        .find(|p| p.ends_with(&format!("/{pick}")))
        .ok_or_else(|| format!("清单里找不到 {pick} 的完整路径"))?;
    let (h, pak) = locate(&con, &full).ok_or_else(|| format!("{pick} 在容器里没有对应记录"))?;
    let mut paks: std::collections::HashMap<String, Pak> = Default::default();
    let raw = decode(&mut paks, &root, &card_of(&pak), h)
        .ok_or_else(|| format!("{pick} 的字节解不出来（容器读得出记录，解码失败）"))?;
    let a = parse_ani(&raw).ok_or_else(|| format!("{pick} 不按已知的 .ani 布局排布"))?;
    let moving = a
        .tracks
        .iter()
        .filter(|t| track_moves(&t.rotations, &t.positions))
        .count();
    let unnamed = a.tracks.iter().filter(|t| t.bone.is_empty()).count();
    let mut missing = vec![
        "父骨链未解：这里列的是每根骨自己的旋转与位移，摆不出整具骨架怎么动".to_string(),
        "模型还不会跟着动：权重在 .mesh 的影响顶点表里，但父骨链未解，逐骨变换相乘不起来".to_string(),
        format!("帧率刻度 {} 的含义未证（每秒 tick？总时长×40？），界面不换算成秒", a.tick),
    ];
    if unnamed > 0 {
        missing.push(format!(
            "骨名表比轨道少 {unnamed} 条：那 {unnamed} 根骨客户端没给名字，这里留空，不编"
        ));
    }
    Ok(AnimReply {
        file: pick,
        files,
        bones: a.bones,
        frames: a.frames,
        tick: a.tick,
        moving,
        tracks: series(&a),
        missing,
        elapsed_ms: t0.elapsed().as_millis() as u64,
    })
}

#[tauri::command]
pub async fn animation_view(gid: i64, file: String) -> Result<AnimReply, String> {
    tauri::async_runtime::spawn_blocking(move || anim_view_run(gid, &file))
        .await
        .map_err(|e| format!("动作线程没起来：{e}"))?
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 真数据：那只怪的骨架要出得来，且数字与自己解的一致。
    #[test]
    fn 骨架页回包带节点声明数与动作表() {
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let con = open_db(&db).expect("清单");
        let gid: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem = 'w1351_monster_xiyuqiezei'",
                [],
                |r| r.get(0),
            )
            .expect("这只怪应在清单里");
        let rep = skeleton_view_run(gid, "").expect("骨架回包");
        assert!(rep.mesh.ends_with(".mesh"), "骨架该跟着网格：{}", rep.mesh);
        assert_eq!(rep.declared, 46, "头部声明的骨骼数");
        // 骨表按 `.ani` 的轨道名单铺全：声明 46 根一根不少，`.mesh` 里多出来的
        // 框架骨（`origin`/`top` 没有动画轨道）排在后面，所以总数 ≥ 声明数。
        assert!(
            rep.nodes.len() >= rep.declared as usize,
            "骨表 {} 行比声明 {} 根还少，说明有骨没被列出来",
            rep.nodes.len(),
            rep.declared
        );
        assert_eq!(rep.nodes[0].name, "bip01", "第一行该是 .ani 骨序的第一根");
        let 有矩阵 = rep.nodes.iter().filter(|n| n.pos.is_some()).count();
        assert_eq!(有矩阵, 32, "带矩阵的骨数变了要说清为什么");
        assert_eq!(
            rep.nodes.iter().filter(|n| n.source == "mesh").count(),
            2,
            "origin/top 这两根只有 .mesh 记录、没有动画轨道，该标成 mesh"
        );
        assert!(rep
            .nodes
            .iter()
            .filter_map(|n| n.pos)
            .all(|p| p.iter().all(|v| v.is_finite())));
        assert!(rep.nodes.iter().any(|n| n.source == "ani"), "只认名字的骨要能标得出来");
        assert!(!rep.nodes.iter().any(|n| n.name.starts_with("Bip01_")), "挂点表的大写骨名不该在骨表里");
        assert!(!rep.animations.is_empty(), "同组 ani/ 目录该有一批动作");
        assert!(
            rep.animations.iter().all(|a| a.bones == rep.declared),
            "动作轨道数应等于声明骨骼数：{:?}",
            rep.animations.iter().map(|a| (a.file.clone(), a.bones)).collect::<Vec<_>>()
        );
        // 没证的东西必须写在回包里，界面才不用自己编
        assert!(rep.missing.iter().any(|m| m.contains("父骨链")));
        assert!(rep.missing.iter().any(|m| m.contains("权重")));
        // 一组多份网格：选择条要给全，换一份看的是另一份的数据
        assert!(
            rep.meshes.len() >= 2,
            "这只怪至少登记了衣服与手套两份网格，选择条却只有 {:?}",
            rep.meshes
        );
        let yifu = skeleton_view_run(gid, "w1351_monster_xiyuqiezei_yifu_001.mesh").expect("换衣服那份");
        assert_eq!(yifu.mesh, "w1351_monster_xiyuqiezei_yifu_001.mesh", "点了一份却列的另一份");
        assert!(
            yifu.skin_bones >= 20,
            "衣服那份实测 26 根骨带影响顶点表，这里只报 {}",
            yifu.skin_bones
        );
        // 文案要跟着数据走：一份都不带时不许说「权重已经按骨读出（0 根）」
        assert!(
            rep.missing.iter().any(|m| m.contains("没有影响顶点表")),
            "这份网格不带表，未解项要说这份的情况：{:?}",
            rep.missing
        );
        assert!(
            !rep.missing.iter().any(|m| m.contains("(0 根") || m.contains("（0 根")),
            "0 根还写「已按骨读出」是自相矛盾：{:?}",
            rep.missing
        );
        assert!(
            yifu.missing.iter().any(|m| m.contains("26 根骨")),
            "衣服那份该报得出读出了多少根：{:?}",
            yifu.missing
        );
        // 已证的东西要报得出、且自洽。这一页只列组里第一份网格，份与份带不带
        // 影响顶点表不一样（实测：yifu_001 有 26 根、shoutao_001 一根都没有），
        // 所以这里只核自洽性；「26 根 / 权重逐顶点加起来 ≈1」那条量级判据在 core 闸门里。
        assert_eq!(
            rep.skin_bones,
            rep.nodes.iter().filter(|n| n.skin > 0).count(),
            "逐行的影响顶点数与汇总对不上"
        );
        assert_eq!(
            rep.skin_pairs,
            rep.nodes.iter().map(|n| n.skin).sum::<usize>(),
            "（顶点-骨）对总数与逐行求和对不上"
        );
        eprintln!(
            "骨架页：{} · 声明 {} 骨 · 节点 {} 条 · 带权重表 {} 根 / {} 对 · 动作 {} 条（第一条 {} 骨 {} 帧，会动 {} 根）",
            rep.mesh,
            rep.declared,
            rep.nodes.len(),
            rep.skin_bones,
            rep.skin_pairs,
            rep.animations.len(),
            rep.animations[0].bones,
            rep.animations[0].frames,
            rep.animations[0].moving
        );
    }

    /// 真数据：一条动作的全部关键帧要发得全，轨道数等于骨骼数、每条轨道帧数齐。
    #[test]
    fn 动作页回包带全部帧与未解项() {
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let con = open_db(&db).expect("清单");
        let gid: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem = 'w1351_monster_xiyuqiezei'",
                [],
                |r| r.get(0),
            )
            .expect("这只怪应在清单里");
        let rep = anim_view_run(gid, "").expect("空文件名该落到第一条动作");
        assert!(!rep.files.is_empty(), "同组 ani/ 该有一批动作");
        assert_eq!(rep.tracks.len(), rep.bones, "轨道数必须等于骨骼数");
        assert!(rep.frames >= 10, "帧数看着不对：{}", rep.frames);
        for t in rep.tracks.iter() {
            assert_eq!(t.rotations.len(), rep.frames, "{} 的旋转帧数不齐", t.bone);
            assert_eq!(t.positions.len(), rep.frames, "{} 的位移帧数不齐", t.bone);
            assert_eq!(t.scales.len(), rep.frames, "{} 的缩放帧数不齐", t.bone);
        }
        assert!(rep.missing.iter().any(|m| m.contains("父骨链")));
        assert!(rep.missing.iter().any(|m| m.contains("权重")));
        assert!(rep.missing.iter().any(|m| m.contains("帧率刻度")));
        let second = rep
            .files
            .iter()
            .find(|f| *f != &rep.file)
            .cloned()
            .expect("应有第二条");
        let r2 = anim_view_run(gid, &second).expect("第二条动作");
        assert_eq!(r2.file, second, "指定文件名就该给那一条");
        eprintln!(
            "动作页：{} · {} 骨 · {} 帧 · 会动 {} 根 · 同组动作 {} 条 · 用时 {}ms",
            rep.file,
            rep.bones,
            rep.frames,
            rep.moving,
            rep.files.len(),
            rep.elapsed_ms
        );
    }

    /// 没有网格的组要老实说不清，不许给个空壳当成功。
    #[test]
    fn 没有网格的组直接报错而不是空回包() {
        let (root, db) = roots();
        if !db.is_file() {
            eprintln!("跳过：本机没有资源清单");
            return;
        }
        let _ = root;
        let con = open_db(&db).expect("清单");
        // 找一个组内没有 .mesh 的
        let gid: Option<i64> = con
            .query_row(
                "SELECT g.id FROM agroups g WHERE coalesce(g.n_mesh,0) = 0 \
                 AND g.dir NOT LIKE '%source/%' LIMIT 1",
                [],
                |r| r.get(0),
            )
            .ok();
        let Some(gid) = gid else {
            eprintln!("跳过：没找到无网格的组");
            return;
        };
        match skeleton_view_run(gid, "") {
            Ok(r) => {
                assert!(
                    r.nodes.is_empty() && !r.note.is_empty(),
                    "无网格却给了节点：{} / {}",
                    r.mesh,
                    r.nodes.len()
                );
            }
            Err(e) => assert!(!e.is_empty(), "报错不能是空串"),
        }
    }
}
