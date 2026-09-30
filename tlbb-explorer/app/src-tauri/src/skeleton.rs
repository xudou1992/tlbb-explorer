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
//! 没证的东西一律写进 `missing`，不猜：父骨链未解（所以画不出骨架连线，只有点），
//! 蒙皮权重不在这份文件里（所以模型本身动不了），帧率刻度的含义未证。

use rusqlite::{Connection, OpenFlags};
use serde::Serialize;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{bone_count, parse_ani, parse_nodes};

use crate::inspector::{inspect, roots};

#[derive(Serialize)]
pub struct BoneRow {
    /// 客户端原文骨名，不翻译不编造。
    pub name: String,
    /// 绑定位移（模型坐标）：矩阵末行 (tx,ty,tz)。
    pub pos: [f32; 3],
    /// 基向量长度（等比缩放）；1.0 附近是正常单位。
    pub scale: f32,
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
    /// `.mesh` 头部声明的骨骼根数。
    pub declared: usize,
    pub nodes: Vec<BoneRow>,
    pub animations: Vec<AnimRow>,
    /// 一份文件里没认出节点记录时给的原因，人话。
    pub note: String,
    pub missing: Vec<String>,
    pub elapsed_ms: u64,
}

/// 容器名归一：清单里 `pak` 存裸名（`data`），开文件要 `data.pak`。
fn card_of(pak: &str) -> String {
    if pak.ends_with(".pak") {
        pak.to_string()
    } else {
        format!("{pak}.pak")
    }
}

fn open_db(db: &std::path::Path) -> Result<Connection, String> {
    Connection::open_with_flags(db, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX)
        .map_err(|e| format!("资源清单打不开：{e}"))
}

/// 按完整路径取一条资源的 (hash, 容器)。
fn locate(con: &Connection, path: &str) -> Option<(u64, String)> {
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
fn anim_paths(con: &Connection, mesh_path: &str) -> Vec<String> {
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

fn decode(paks: &mut std::collections::HashMap<String, Pak>, root: &std::path::Path, card: &str, hash: u64) -> Option<Vec<u8>> {
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

pub fn skeleton_view_run(gid: i64) -> Result<SkeletonReply, String> {
    let t0 = std::time::Instant::now();
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_db(&db)?;
    // 组里那份网格：优先用 inspect 已经算好的成员（它认过角色），退化到目录里最大的 .mesh
    let insp = inspect(gid)?;
    let mesh_path = insp
        .members
        .iter()
        .find(|m| m.role == "mesh")
        .and_then(|m| m.path.clone())
        .or_else(|| {
            con.query_row(
                "SELECT coalesce(path,'') FROM resources WHERE ext='.mesh' AND dir LIKE ?1 \
                 ORDER BY stored DESC LIMIT 1",
                [format!("%{}%", insp.dir)],
                |r| r.get::<_, String>(0),
            )
            .ok()
        })
        .ok_or_else(|| "这一组里没有网格文件，骨架跟着网格走，没有网格就没有骨架。".to_string())?;

    let mut paks: std::collections::HashMap<String, Pak> = Default::default();
    let mut nodes = Vec::new();
    let mut declared = 0usize;
    let mut note = String::new();
    if let Some((h, pak)) = locate(&con, &mesh_path) {
        if let Some(raw) = decode(&mut paks, &root, &card_of(&pak), h) {
            declared = bone_count(&raw).unwrap_or(0);
            let got = parse_nodes(&raw);
            nodes = got
                .iter()
                .map(|nd| BoneRow {
                    name: nd.name.clone(),
                    pos: [nd.bind[12], nd.bind[13], nd.bind[14]],
                    scale: (nd.bind[0] * nd.bind[0] + nd.bind[1] * nd.bind[1] + nd.bind[2] * nd.bind[2])
                        .sqrt(),
                })
                .collect();
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
    for p in anim_paths(&con, &mesh_path) {
        let name = p.rsplit('/').next().unwrap_or("").to_string();
        let Some((h, pak)) = locate(&con, &p) else { continue };
        let Some(raw) = decode(&mut paks, &root, &card_of(&pak), h) else { continue };
        let Some(a) = parse_ani(&raw) else { continue };
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

    let mut missing = vec![
        "父骨链未解：只知道每根骨在模型里的位置，不知道谁挂谁，所以这里画不出骨架连线，只能列点".to_string(),
        "蒙皮权重不在这份文件里：顶点跟着哪几根骨、各占多少，客户端没写在 .mesh/.ske/.mdl".to_string(),
    ];
    if !animations.is_empty() {
        missing.push("帧率刻度（样本恒 40.0）到底是每秒 tick 还是别的，未证——所以不换算成秒".to_string());
    }
    if declared > nodes.len() {
        missing.push(format!(
            "声明 {declared} 根骨，这里只认出 {} 条节点记录：剩下的骨名字后面不跟矩阵，为什么没跟还没查出来",
            nodes.len()
        ));
    }

    Ok(SkeletonReply {
        mesh: mesh_path.rsplit('/').next().unwrap_or("").to_string(),
        declared,
        nodes,
        animations,
        note,
        missing,
        elapsed_ms: t0.elapsed().as_millis() as u64,
    })
}

#[tauri::command]
pub async fn skeleton_view(gid: i64) -> Result<SkeletonReply, String> {
    tauri::async_runtime::spawn_blocking(move || skeleton_view_run(gid))
        .await
        .map_err(|e| format!("骨架线程没起来：{e}"))?
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
        let rep = skeleton_view_run(gid).expect("骨架回包");
        assert!(rep.mesh.ends_with(".mesh"), "骨架该跟着网格：{}", rep.mesh);
        assert_eq!(rep.declared, 46, "头部声明的骨骼数");
        assert!(rep.nodes.len() >= 30, "只认出 {} 条节点", rep.nodes.len());
        assert_eq!(rep.nodes[0].name, "origin");
        assert!(rep.nodes.iter().all(|n| n.pos.iter().all(|v| v.is_finite())));
        assert!(!rep.animations.is_empty(), "同组 ani/ 目录该有一批动作");
        assert!(
            rep.animations.iter().all(|a| a.bones == rep.declared),
            "动作轨道数应等于声明骨骼数：{:?}",
            rep.animations.iter().map(|a| (a.file.clone(), a.bones)).collect::<Vec<_>>()
        );
        // 没证的东西必须写在回包里，界面才不用自己编
        assert!(rep.missing.iter().any(|m| m.contains("父骨链")));
        assert!(rep.missing.iter().any(|m| m.contains("权重")));
        eprintln!(
            "骨架页：{} · 声明 {} 骨 · 节点 {} 条 · 动作 {} 条（第一条 {} 骨 {} 帧，会动 {} 根）",
            rep.mesh,
            rep.declared,
            rep.nodes.len(),
            rep.animations.len(),
            rep.animations[0].bones,
            rep.animations[0].frames,
            rep.animations[0].moving
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
        match skeleton_view_run(gid) {
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
