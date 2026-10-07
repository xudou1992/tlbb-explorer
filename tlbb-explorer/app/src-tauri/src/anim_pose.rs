//! 动画播放上屏（v0.5.0）的后端一半：把一条 `.ani` 的第 `frame` 帧蒙皮顶点
//! 摆好发出去。前端拿到 `positions` 直接替换灰模的位置缓冲——与 `mesh_data`
//! 的灰模**同空间同序**（同一份网格字节、同一个 `parse_geometry`），所以
//! frame=0 的回包必须逐顶点回到灰模（闸门钉住）。
//!
//! 播放锚是裁决过的口径：**每条动作自己的第 0 帧世界矩阵的逆**，不是 `.mesh`
//! 的 bind。静止渲染维持 bind 不动；两者不同源（frame0≠bind，中位 |Δt| 1.92、
//! 角差 115.9°）。证据与四种锚 × 15 条动作的比对表在
//! `.scratch/ani_axis/锚点判定_20261007.md`（15/15 条动作全胜绑定锚、无一例外）。
//! 复合数学在 core 的 [`tlbb_core::preview::pose::reanchored_palette`]，本命令
//! 只做定位与装配，不手写矩阵复合。
//!
//! 实现纪律照抄既有命令：`spawn_blocking` + 只读（清单只读、容器只读），
//! 错误一律人话 String，对不上的数据如实报错、不硬摆。

use std::sync::Arc;

use serde::Serialize;
use tauri::State;
use tlbb_core::jpak::Pak;
use tlbb_core::preview::pose::{bind_worlds, posed_vertices, reanchored_palette};
use tlbb_core::preview::{
    parse_ani, parse_geometry, parse_hierarchy, parse_nodes, Anim, MeshGeometry, Node,
    SkeletonHierarchy,
};

use crate::data::AppData;
use crate::inspector::{inspect, roots};
use crate::mesh_bones::mesh_bytes;
use crate::skeleton::{anim_paths, card_of, decode, locate, mesh_paths, open_db};

/// 整组部件里**一件**摆好后的顶点（复合的账：36% 的 .mesh 是多件套，共用一副
/// 骨架，单件看不出是什么）。`mesh` 是客户端原文完整路径。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AnimPosePart {
    pub mesh: String,
    pub vertex_count: usize,
    /// 摆好后的顶点，与该件 `mesh_data` 的 positions 同空间同序。
    pub positions: Vec<[f32; 3]>,
}

/// 回包用 camelCase，与 `mesh_data` / 骨架页同一套约定。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AnimPoseReply {
    /// 实际用的网格路径（客户端原文）。mesh 参数为空时是这组的第一份，
    /// 前端据此显示与切换。整组路径下 = parts[0] 的网格（兼容现状）。
    pub mesh: String,
    /// 动作文件名（.ani，客户端原文）。
    pub anim: String,
    /// 夹取后的当前帧（0..=frames-1，越界不 panic）。
    pub frame: usize,
    /// 该动作总帧数。
    pub frames: usize,
    pub vertex_count: usize,
    /// 摆好后的顶点，与 `mesh_data` 的 positions 同空间同序。
    /// 整组路径下 = parts[0] 的顶点（兼容现状）。
    pub positions: Vec<[f32; 3]>,
    /// 人话注记（固定三条：锚口径、帧率未证、朝向未证；整组路径下追加
    /// 「这件不变形」一类的部件实况）。
    pub notes: Vec<String>,
    /// 整组部件一起摆的回包。单件路径（parts 参数缺省 / 一个都没命中）不带
    /// 这个字段——序列化时整个消失，前端按字段在不在分辨两条路。
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parts: Option<Vec<AnimPosePart>>,
}

/// 动作定位与解码：同组 `<目录>/ani/*.ani` 里按文件名找；空名字落到第一条
/// （动作页同款）。返回（动作名、解析后的动作）。单件与整组两条路径共用
/// 这一个入口，报错口径与拆出来之前逐字一致。
fn pick_anim(
    con: &rusqlite::Connection,
    paks: &mut std::collections::HashMap<String, Pak>,
    root: &std::path::Path,
    mesh_path: &str,
    want_anim: &str,
) -> Result<(String, Anim), String> {
    let files = anim_paths(con, mesh_path);
    let want = want_anim.trim();
    let picked = if want.is_empty() {
        files.first().cloned()
    } else {
        files
            .iter()
            .find(|p| p.ends_with(&format!("/{want}")))
            .cloned()
    }
    .ok_or_else(|| {
        if want.is_empty() {
            "这一组旁边没有 ani/ 目录，客户端没给它配动作文件。".to_string()
        } else {
            format!("这一组的动作目录里没有 {want}，换一条试试（同组动作以 ani/ 目录登记的为准）。")
        }
    })?;
    let anim_name = picked.rsplit('/').next().unwrap_or(want).to_string();
    let (ah, pak) =
        locate(con, &picked).ok_or_else(|| format!("{anim_name} 在容器里没有对应记录。"))?;
    let ani_raw = decode(paks, root, &card_of(&pak), ah)
        .ok_or_else(|| format!("{anim_name} 的字节解不出来（容器读得出记录，解码失败）。"))?;
    let a = parse_ani(&ani_raw)
        .ok_or_else(|| format!("{anim_name} 不按已知的 .ani 布局排布，读不出关键帧。"))?;
    Ok((anim_name, a))
}

/// 同名骨 bind 世界位姿的容差：整组各件各自带一份骨架文件，同一副骨架的两份
/// 拷贝在存储精度内应当一字不差；1e-3 已经宽过 f32 存储误差几个量级，再宽就
/// 是真的两副骨架了。
const PART_BIND_TOLERANCE: f32 = 1e-3;

/// 跨部件自检（运行时）：整组必须共用同一副骨架才拼得起来——
/// ① 各件 `parse_hierarchy` 骨数一致；② 同名骨 `bind_worlds` 求出的世界位姿
/// 一致（≤ [`PART_BIND_TOLERANCE`]）。对不上回人话，调用方直接报错，不硬摆。
/// 输入是 (件名, 骨架) 的切片；空表 / 单件没有可比对象，直接放行。
fn parts_skeleton_mismatch(parts: &[(&str, &SkeletonHierarchy)]) -> Option<String> {
    let Some((first_name, first)) = parts.first() else {
        return None;
    };
    let first_worlds = bind_worlds(first);
    for (name, h) in parts.iter().skip(1) {
        if h.bones.len() != first.bones.len() {
            return Some(format!(
                "这几件网格的骨架对不上，拼不了一起：骨数不一样（{first_name} {} 根，{name} {} 根）。",
                first.bones.len(),
                h.bones.len()
            ));
        }
        let worlds = bind_worlds(h);
        for (i, b) in first.bones.iter().enumerate() {
            let Some(j) = h.bones.iter().position(|x| x.name == b.name) else {
                return Some(format!(
                    "这几件网格的骨架对不上，拼不了一起：{first_name} 里的骨「{}」在 {name} 里没有同名骨。",
                    b.name
                ));
            };
            let d = worlds[j]
                .iter()
                .zip(first_worlds[i].iter())
                .map(|(a, b)| (a - b).abs())
                .fold(0f32, f32::max);
            if d > PART_BIND_TOLERANCE {
                return Some(format!(
                    "这几件网格的骨架对不上，拼不了一起：同名骨「{}」的绑定姿态差了 {d:.4}（{first_name} 与 {name}）。不硬摆。",
                    b.name
                ));
            }
        }
    }
    None
}

/// 整组路径里一件的准备材料：字节解好、骨架与几何解好，蒙皮等动作回包一起摆。
struct PartPrep {
    /// 客户端原文完整路径（回包用这个）。
    actual: String,
    /// 尾名（错误消息与「不变形」注记里点名用）。
    tail: String,
    hier: SkeletonHierarchy,
    geom: MeshGeometry,
    nodes: Vec<Node>,
}

impl PartPrep {
    /// 这件有没有影响顶点表。一件都没有 = 顶点全绑在根骨上，摆姿势时原地
    /// 不动——界面必须如实标注「这件不变形」，不能让人以为它跟着动了。
    fn deforms(&self) -> bool {
        self.nodes.iter().any(|n| n.skin.is_some())
    }
}

/// `anim_pose` 命令的实现。普通函数是为了测试与将来的 `--probe` 段能无窗口
/// 走同一条路（骨架页 `skeleton_view_run` 的同款理由）。
///
/// `parts` 是整组部件一起摆的名单（部件文件名，匹配规则同 `mesh` 参数：按
/// `/` 切尾名对组内名单匹配）。命中 ≥1 件时逐件取字节、跨部件自检骨架、
/// 每件各自蒙皮，回包带 `parts`；命中 0 个或 None 时走单件老路，回包不带
/// `parts` 字段——现状行为一字不动。
pub fn anim_pose_run(
    app: &AppData,
    gid: i64,
    anim: &str,
    mesh: Option<&str>,
    frame: u32,
    parts: Option<&[String]>,
) -> Result<AnimPoseReply, String> {
    let (root, db) = roots();
    if !db.exists() {
        return Err(format!("找不到资源清单文件：{}", db.display()));
    }
    let con = open_db(&db)?;
    let insp = inspect(gid)?;
    // 网格选择与骨架页同款：只认组内登记的那几份（hub 排第一），名字对不上
    // 回到第一份——参数空/None 时就是第一份。
    let hub: String = con
        .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
            r.get(0)
        })
        .unwrap_or_default();
    let paths = mesh_paths(&con, gid, &hub, &insp.dir);
    if paths.is_empty() {
        return Err("这一组里没有网格文件，动作没有可蒙皮的载体，摆不了姿势。".to_string());
    }
    // 部件名单 → 组内路径。同一件点名两次只算一次；没点中的名字悄悄跳过
    // （清单里没有的东西不能编），全没点中才回落单件。
    let mut hit_paths: Vec<String> = Vec::new();
    for want in parts.into_iter().flatten() {
        let want = want.trim();
        if want.is_empty() {
            continue;
        }
        if let Some(p) = paths
            .iter()
            .find(|p| p.rsplit('/').next().unwrap_or("") == want)
        {
            if !hit_paths.contains(p) {
                hit_paths.push(p.clone());
            }
        }
    }

    if hit_paths.is_empty() {
        // ---- 单件老路（现状）----
        let mesh_path = match mesh.map(str::trim).filter(|s| !s.is_empty()) {
            None => paths[0].clone(),
            Some(want) => paths
                .iter()
                .find(|p| p.rsplit('/').next().unwrap_or("") == want)
                .cloned()
                .unwrap_or_else(|| paths[0].clone()),
        };
        let (mesh_actual, raw) = mesh_bytes(app, &mesh_path, None)?;

        // 管线（契约顺序）：骨架 → 网格几何 → 动作 → 调色板 → 蒙皮。
        // 每一步对不上都用人话说清楚，不吞错、不硬摆。
        let hier = parse_hierarchy(&raw)
            .ok_or_else(|| "这份网格没读出骨头谁挂谁，摆不了姿势（父骨链是蒙皮的前提）。".to_string())?;
        let geom = parse_geometry(&raw).map_err(|e| format!("网格几何解析失败：{e}"))?;

        let mut paks: std::collections::HashMap<String, Pak> = Default::default();
        let (anim_name, a) = pick_anim(&con, &mut paks, &root, &mesh_path, anim)?;

        // 帧号夹进 0..=frames-1：滑杆越界是前端的事，后端不许 panic。
        let frames = a.frames;
        let frame = (frame as usize).min(frames - 1);

        let palette = reanchored_palette(&hier, &a, frame)
            .ok_or_else(|| "骨架与动作对不上（骨数不一致），调不出蒙皮调色板。".to_string())?;
        let nodes = parse_nodes(&raw);
        let posed = posed_vertices(&hier, &palette, &nodes, &geom.positions).ok_or_else(|| {
            "蒙皮没摆成：影响顶点表和骨架对不上（骨名对不上或顶点号越界），不硬摆。".to_string()
        })?;

        Ok(AnimPoseReply {
            mesh: mesh_actual,
            anim: anim_name,
            frame,
            frames,
            vertex_count: geom.positions.len(),
            positions: posed,
            notes: vec![
                "预览以这条动作的第 0 帧为基准锚定；静止显示用的是网格里的绑定姿态，两者不同源\
                 （证据档案 .scratch/ani_axis/锚点判定_20261007.md：15/15 条动作全胜绑定锚）"
                    .to_string(),
                "帧率刻度的含义未证，播放速度只是逐帧推进的参考值".to_string(),
                "运动的绝对朝向未证：锚定保证动作连贯，不保证与游戏画面逐帧对齐".to_string(),
            ],
            parts: None,
        })
    } else {
        // ---- 整组部件路径（复合的账的最后一层）----
        // 每件独立取字节、解骨架与几何；全部就位后先做跨部件骨架自检，
        // 过了才谈得上一起摆——骨架对不上的两件摆出来就是撕成两半。
        let mut preps: Vec<PartPrep> = Vec::with_capacity(hit_paths.len());
        for path in &hit_paths {
            let (actual, raw) = mesh_bytes(app, path, None)?;
            let tail = actual.rsplit('/').next().unwrap_or(path).to_string();
            let hier = parse_hierarchy(&raw).ok_or_else(|| {
                format!("这几件网格拼不了一起：{tail} 没读出骨头谁挂谁（父骨链是蒙皮的前提）。")
            })?;
            let geom =
                parse_geometry(&raw).map_err(|e| format!("{tail} 的网格几何解析失败：{e}"))?;
            let nodes = parse_nodes(&raw);
            preps.push(PartPrep { actual, tail, hier, geom, nodes });
        }
        let refs: Vec<(&str, &SkeletonHierarchy)> =
            preps.iter().map(|p| (p.tail.as_str(), &p.hier)).collect();
        if let Some(msg) = parts_skeleton_mismatch(&refs) {
            return Err(msg);
        }

        // 动作整组共用一副：同目录 ani/，按第一件定位，解析一次。
        let mut paks: std::collections::HashMap<String, Pak> = Default::default();
        let (anim_name, a) = pick_anim(&con, &mut paks, &root, &hit_paths[0], anim)?;
        let frames = a.frames;
        let frame = (frame as usize).min(frames - 1);

        // 每件各自蒙皮：调色板按这件自己的骨架取（自检已保证骨数与同名骨
        // 位姿一致，逐件算比共用第一件的骨架更不容易被一份坏数据带走）。
        let mut out: Vec<AnimPosePart> = Vec::with_capacity(preps.len());
        let mut notes = vec![
            "预览以这条动作的第 0 帧为基准锚定；静止显示用的是网格里的绑定姿态，两者不同源\
             （证据档案 .scratch/ani_axis/锚点判定_20261007.md：15/15 条动作全胜绑定锚）"
                .to_string(),
            "帧率刻度的含义未证，播放速度只是逐帧推进的参考值".to_string(),
            "运动的绝对朝向未证：锚定保证动作连贯，不保证与游戏画面逐帧对齐".to_string(),
        ];
        for p in &preps {
            let palette = reanchored_palette(&p.hier, &a, frame).ok_or_else(|| {
                format!(
                    "{} 的骨架与动作对不上（骨数不一致），调不出蒙皮调色板。",
                    p.tail
                )
            })?;
            let posed = posed_vertices(&p.hier, &palette, &p.nodes, &p.geom.positions)
                .ok_or_else(|| {
                    format!(
                        "{} 的蒙皮没摆成：影响顶点表和骨架对不上（骨名对不上或顶点号越界），不硬摆。",
                        p.tail
                    )
                })?;
            if !p.deforms() {
                notes.push(format!(
                    "{} 没有影响顶点表（顶点全绑在根骨上），这件不变形",
                    p.tail
                ));
            }
            out.push(AnimPosePart {
                mesh: p.actual.clone(),
                vertex_count: p.geom.positions.len(),
                positions: posed,
            });
        }
        // 顶层字段 = parts[0]：只认「回包没有 parts 字段」的旧前端照样能摆第一件。
        let first = &out[0];
        Ok(AnimPoseReply {
            mesh: first.mesh.clone(),
            anim: anim_name,
            frame,
            frames,
            vertex_count: first.vertex_count,
            positions: first.positions.clone(),
            notes,
            parts: Some(out),
        })
    }
}

#[tauri::command]
pub async fn anim_pose(
    app: State<'_, Arc<AppData>>,
    gid: i64,
    anim: String,
    mesh: Option<String>,
    frame: u32,
    parts: Option<Vec<String>>,
) -> Result<AnimPoseReply, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || {
        anim_pose_run(&app, gid, &anim, mesh.as_deref(), frame, parts.as_deref())
    })
    .await
    .map_err(|e| format!("动画姿势线程没起来：{e}"))?
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 真数据集成：idle01 的 frame=0 回包必须与 `mesh_geometry`（前端灰模的
    /// 数据源）同空间同序——差 < 1e-4；中间帧全有限；越界帧夹到最后一帧。
    /// gid 的找法照 `skeleton.rs` 的测试。
    #[test]
    fn 动作姿势回包与灰模同源且中间帧全有限() {
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let app = AppData::open(&root, &db).expect("工作台数据");
        let con = open_db(&db).expect("清单");
        let gid: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem = 'w1351_monster_xiyuqiezei'",
                [],
                |r| r.get(0),
            )
            .expect("这只怪应在清单里");
        // 动作名是客户端原文（带怪名前缀，如 w1351_monster_xiyuqiezei_idle01.ani），
        // 从清单按骨架页同款查询取真名，不手编。
        let hub: String = con
            .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
                r.get(0)
            })
            .unwrap_or_default();
        let insp = inspect(gid).expect("组详情");
        let group_meshes = mesh_paths(&con, gid, &hub, &insp.dir);
        let idle = anim_paths(&con, &group_meshes[0])
            .into_iter()
            .map(|p| p.rsplit('/').next().unwrap_or("").to_string())
            .find(|f| f.contains("idle01"))
            .expect("这只怪该有 idle01 这条动作");

        let rep = anim_pose_run(&app, gid, &idle, None, 0, None).expect("第 0 帧姿势");
        assert!(rep.parts.is_none(), "单件路径回包不带 parts 字段");
        assert!(rep.frames > 0, "总帧数该是正数：{}", rep.frames);
        assert_eq!(rep.frame, 0);
        assert_eq!(rep.anim, idle, "回包带实际用的动作名");
        assert_eq!(rep.positions.len(), rep.vertex_count, "顶点数与数组长度一致");
        assert_eq!(rep.notes.len(), 3, "固定三条注记：锚口径 / 帧率未证 / 朝向未证");
        assert!(rep.mesh.ends_with(".mesh"), "网格路径是客户端原文：{}", rep.mesh);

        // frame=0 恒等式在 IPC 这一层再收一次口：positions 与 mesh_data 的
        // 数据源（app.mesh_geometry → parse_geometry）逐顶点差 < 1e-4。
        let (path, g) = app.mesh_geometry(&rep.mesh, None).expect("灰模几何");
        assert_eq!(path, rep.mesh, "回包的网格就是 mesh_geometry 认的那份");
        assert_eq!(g.positions.len(), rep.positions.len());
        let mut worst = 0f32;
        for (a, b) in rep.positions.iter().zip(g.positions.iter()) {
            let d = (a[0] - b[0])
                .abs()
                .max((a[1] - b[1]).abs())
                .max((a[2] - b[2]).abs());
            worst = worst.max(d);
        }
        assert!(
            worst < 1e-4,
            "frame=0 与灰模不同源：最大差 {worst:.2e}（同一份字节同一个解析器，不该有差）"
        );

        // 中间帧：全有限、帧号与总帧数自洽
        let mid = rep.frames / 2;
        let m = anim_pose_run(&app, gid, &idle, None, mid as u32, None).expect("中间帧姿势");
        assert_eq!(m.frame, mid, "中间帧号原样带回");
        assert_eq!(m.frames, rep.frames);
        assert_eq!(m.vertex_count, rep.vertex_count);
        assert!(
            m.positions.iter().all(|p| p.iter().all(|v| v.is_finite())),
            "中间帧顶点必须全有限"
        );
        assert!(
            m.positions.iter().enumerate().all(|(i, p)| {
                let d = (p[0] - g.positions[i][0]).powi(2)
                    + (p[1] - g.positions[i][1]).powi(2)
                    + (p[2] - g.positions[i][2]).powi(2);
                d.is_finite()
            }),
            "中间帧的位移量也要可算"
        );

        // 越界帧夹到最后一帧，不许 panic
        let over = anim_pose_run(&app, gid, &idle, None, 99_999, None).expect("越界帧要夹住");
        assert_eq!(over.frame, rep.frames - 1);

        // 组内换网格也要走得通（骨架页选择条里的另一份），回包如实带路径
        assert!(group_meshes.len() >= 2, "这只怪至少登记了两份网格");
        let other = group_meshes
            .iter()
            .find(|p| p.rsplit('/').next() != Some(rep.mesh.rsplit('/').next().unwrap_or("")))
            .expect("应有另一份网格");
        let rep2 = anim_pose_run(
            &app,
            gid,
            &idle,
            Some(other.rsplit('/').next().unwrap_or("")),
            0,
            None,
        )
        .expect("换一份网格摆姿势");
        assert_eq!(rep2.mesh, *other, "指定哪份就用哪份，回包带实际路径");
        assert_eq!(rep2.positions.len(), rep2.vertex_count);

        // 带真蒙皮的那份（yifu_001，781 顶点、26 根带表骨）在 frame=0 也必须
        // 逐顶点回到灰模——shoutao 没有影响表，它的恒等是平凡的，盯不住锚。
        if rep2.mesh.contains("yifu_001") {
            let (_, g2) = app.mesh_geometry(&rep2.mesh, None).expect("yifu 灰模");
            let worst2 = rep2
                .positions
                .iter()
                .zip(g2.positions.iter())
                .map(|(a, b)| {
                    (a[0] - b[0])
                        .abs()
                        .max((a[1] - b[1]).abs())
                        .max((a[2] - b[2]).abs())
                })
                .fold(0f32, f32::max);
            assert!(
                worst2 < 1e-4,
                "蒙皮网格 frame=0 与灰模不同源：最大差 {worst2:.2e}"
            );
            eprintln!("yifu_001 frame0 恒等：781 顶点最大差 {worst2:.2e}");
        }

        eprintln!(
            "anim_pose：{} · {} · {}/{} 帧 · 顶点 {} · frame0 与灰模最大差 {worst:.2e}",
            rep.mesh,
            rep.anim,
            rep.frame,
            rep.frames,
            rep.vertex_count
        );
    }

    /// 不存在的动作要用人话报错，不许悄悄换成别的动作还报成功。
    #[test]
    fn 不存在的动作名如实报错() {
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let app = AppData::open(&root, &db).expect("工作台数据");
        let con = open_db(&db).expect("清单");
        let gid: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem = 'w1351_monster_xiyuqiezei'",
                [],
                |r| r.get(0),
            )
            .expect("这只怪应在清单里");
        let err = anim_pose_run(&app, gid, "不存在的动作.ani", None, 0, None).unwrap_err();
        assert!(!err.is_empty(), "报错不能是空串");
        assert!(err.contains("不存在的动作.ani"), "报错要带上找不到的名字：{err}");
    }

    /// 真数据整组：把这只怪登记的**全部**网格当部件一起摆（复合的账：这些件
    /// 共用一副骨架，单件看不出是什么）。钉四件事：
    /// ① 回包形状——parts 与组内登记的网格一一对应，顶层字段 = parts[0]；
    /// ② 跨部件骨架自检真的跑过且通过（骨数一致 + 同名骨 bind 世界位姿一致），
    ///    回包才出得来；
    /// ③ frame0 恒等式对**每一件**成立（与各自灰模数据源逐顶点差 < 1e-4）；
    /// ④ 没有权重表的那件在注记里如实标注「这件不变形」，不冒充跟着动。
    #[test]
    fn 整组部件一起摆_回包形状自检与每件frame0恒等() {
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let app = AppData::open(&root, &db).expect("工作台数据");
        let con = open_db(&db).expect("清单");
        let gid: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem = 'w1351_monster_xiyuqiezei'",
                [],
                |r| r.get(0),
            )
            .expect("这只怪应在清单里");
        let hub: String = con
            .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
                r.get(0)
            })
            .unwrap_or_default();
        let insp = inspect(gid).expect("组详情");
        let group_meshes = mesh_paths(&con, gid, &hub, &insp.dir);
        let idle = anim_paths(&con, &group_meshes[0])
            .into_iter()
            .map(|p| p.rsplit('/').next().unwrap_or("").to_string())
            .find(|f| f.contains("idle01"))
            .expect("这只怪该有 idle01 这条动作");

        // 前端就是这么发的：懒取部件清单全量，按尾名整组发回去
        let parts: Vec<String> = group_meshes
            .iter()
            .map(|p| p.rsplit('/').next().unwrap_or("").to_string())
            .collect();
        let rep = anim_pose_run(&app, gid, &idle, None, 0, Some(&parts))
            .expect("整组第 0 帧姿势（跨部件自检通过才出得来）");
        let out = rep.parts.as_ref().expect("整组路径回包必须带 parts 字段");
        assert_eq!(out.len(), group_meshes.len(), "件数与组内登记的网格数一致");
        assert_eq!(rep.mesh, out[0].mesh, "顶层 mesh = parts[0]");
        assert_eq!(rep.vertex_count, out[0].vertex_count, "顶层顶点数 = parts[0]");
        assert_eq!(rep.positions.len(), out[0].positions.len(), "顶层顶点 = parts[0]");
        assert_eq!(rep.anim, idle);
        assert!(rep.notes.len() >= 3, "固定三条注记必须还在：{:?}", rep.notes);
        // 线格式再钉一次：前端是「按 parts 字段在不在分辨两条路」，Option::is_none
        // 不等于字段不在 JSON 里——skip_serializing_if 掉了这里就先红。
        let wire = serde_json::to_value(&rep).expect("回包可序列化");
        let parts_wire = wire
            .get("parts")
            .expect("整组回包序列化后必须带 parts 字段")
            .as_array()
            .expect("parts 是数组")
            .clone();
        assert_eq!(parts_wire.len(), group_meshes.len(), "线上的件数也要对");
        let first_wire = &parts_wire[0];
        for key in ["mesh", "vertexCount", "positions"] {
            assert!(
                first_wire.get(key).is_some(),
                "parts 元素要带 camelCase 字段 {key}：{first_wire}"
            );
        }
        assert!(
            first_wire.get("vertex_count").is_none(),
            "不许冒出 snake_case 字段：{first_wire}"
        );
        for (i, p) in out.iter().enumerate() {
            assert_eq!(p.mesh, group_meshes[i], "回包顺序 = 请求顺序，路径是客户端原文");
            assert_eq!(p.positions.len(), p.vertex_count, "每件顶点数与数组长度一致");
            assert!(
                p.positions.iter().all(|v| v.iter().all(|x| x.is_finite())),
                "整组顶点全有限"
            );
            // frame0 恒等式对每一件成立：与该件灰模（mesh_geometry，前端静止
            // 渲染的数据源）逐顶点差 < 1e-4。蒙皮件（衣服 781 顶点、26 根带表
            // 骨）这条盯的是锚；无表件（手套）恒等是平凡的。
            let (_, g) = app.mesh_geometry(&p.mesh, None).expect("该件灰模几何");
            assert_eq!(g.positions.len(), p.positions.len());
            let worst = p
                .positions
                .iter()
                .zip(g.positions.iter())
                .map(|(a, b)| {
                    (a[0] - b[0])
                        .abs()
                        .max((a[1] - b[1]).abs())
                        .max((a[2] - b[2]).abs())
                })
                .fold(0f32, f32::max);
            assert!(
                worst <= 1e-5,
                "件 {} frame0 与灰模不同源：最大差 {worst:.2e}（锚定口径下第 0 帧就是绑定姿态，\
                 只该剩 f32 复合的浮点尾数）",
                p.mesh
            );
            eprintln!("整组件 {}：{} · {} 顶点 · frame0 恒等最大差 {worst:.2e}", i + 1, p.mesh, p.vertex_count);
        }
        // 中间帧整组走得通，件数不随帧变、顶点全有限
        let mid = rep.frames / 2;
        let m = anim_pose_run(&app, gid, &idle, None, mid as u32, Some(&parts))
            .expect("整组中间帧");
        let mout = m.parts.as_ref().expect("中间帧也带 parts");
        assert_eq!(mout.len(), out.len(), "件数不随帧变");
        assert!(mout
            .iter()
            .all(|p| p.positions.iter().all(|v| v.iter().all(|x| x.is_finite()))));
        // 没权重表的那件要点名（这只怪的手套实测 0 根带表骨）
        assert!(
            rep.notes.iter().any(|n| n.contains("不变形")),
            "没权重表的件要如实标注：{:?}",
            rep.notes
        );
        eprintln!("整组：{} 件 · 注记 {:?}", out.len(), rep.notes);
    }

    /// parts 名单一个都没命中（含空名单）：维持现状单网格路径，回包**不带**
    /// parts 字段，摆的顶点与不带 parts 参数的调用一字不差。
    #[test]
    fn 部件名单全没命中回落单件不带parts字段() {
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let app = AppData::open(&root, &db).expect("工作台数据");
        let con = open_db(&db).expect("清单");
        let gid: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem = 'w1351_monster_xiyuqiezei'",
                [],
                |r| r.get(0),
            )
            .expect("这只怪应在清单里");
        let hub: String = con
            .query_row("SELECT coalesce(hub_path,'') FROM agroups WHERE id = ?1", [gid], |r| {
                r.get(0)
            })
            .unwrap_or_default();
        let insp = inspect(gid).expect("组详情");
        let group_meshes = mesh_paths(&con, gid, &hub, &insp.dir);
        let idle = anim_paths(&con, &group_meshes[0])
            .into_iter()
            .map(|p| p.rsplit('/').next().unwrap_or("").to_string())
            .find(|f| f.contains("idle01"))
            .expect("这只怪该有 idle01 这条动作");

        let single = anim_pose_run(&app, gid, &idle, None, 0, None).expect("单件");
        let none_hit = anim_pose_run(
            &app,
            gid,
            &idle,
            None,
            0,
            Some(&["不存在的部件.mesh".to_string()]),
        )
        .expect("名单全没命中要回落单件，不是报错");
        assert!(none_hit.parts.is_none(), "没命中就不能带 parts 字段");
        // 线格式：skip_serializing_if 要让「parts」整个从 JSON 里消失——
        // 前端按字段在不在分辨两条路，序列化成 null 也算违约。
        let wire = serde_json::to_value(&none_hit).expect("回包可序列化");
        assert!(
            wire.get("parts").is_none(),
            "回落单件时 parts 字段必须整个消失，不能是 null：{}",
            serde_json::to_string(&wire).unwrap_or_default()
        );
        assert_eq!(none_hit.mesh, single.mesh, "回落的是同一份单网格");
        assert_eq!(
            none_hit.positions, single.positions,
            "回落路径摆出的顶点与现状一字不差"
        );
        let empty = anim_pose_run(&app, gid, &idle, None, 0, Some(&[])).expect("空名单同理");
        assert!(empty.parts.is_none(), "空名单也不能带 parts 字段");
    }

    /// 跨部件骨架自检的负向分支（合成数据，不依赖客户端）：骨数不一致、
    /// 同名骨 bind 世界位姿超差、同名骨缺失，三种都要用人话说「拼不了一起」；
    /// 同一副骨架的两份拷贝要放行。
    #[test]
    fn 部件骨架对不上要人话报错不硬摆() {
        use tlbb_core::preview::geometry::BoneNode;
        use tlbb_core::preview::pose::mat_identity;

        // 存储值 = 世界绑定矩阵的逆：平移取负，bind_worlds 求逆后回到 tx。
        let 骨 = |name: &str, parent: Option<usize>, tx: f32| BoneNode {
            name: name.to_string(),
            parent,
            bind: {
                let mut m = mat_identity();
                m[12] = -tx;
                Some(m)
            },
            children: Vec::new(),
        };
        let 成对 = |root_tx: f32, child_tx: f32| {
            let mut h = SkeletonHierarchy {
                bones: vec![骨("000", None, root_tx), 骨("bip01", Some(0), child_tx)],
                sockets: Vec::new(),
            };
            h.bones[0].children.push(1);
            h
        };
        let a = 成对(0.0, 0.5);
        let b = 成对(0.0, 0.5);
        assert!(
            parts_skeleton_mismatch(&[("a.mesh", &a), ("b.mesh", &b)]).is_none(),
            "同一副骨架的两份拷贝要放行"
        );
        assert_eq!(parts_skeleton_mismatch(&[]), None, "空表没有可比对象");
        assert_eq!(
            parts_skeleton_mismatch(&[("a.mesh", &a)]),
            None,
            "单件没有可比对象"
        );

        // 骨数不一样
        let c = SkeletonHierarchy { bones: vec![骨("000", None, 0.0)], sockets: Vec::new() };
        let msg = parts_skeleton_mismatch(&[("a.mesh", &a), ("c.mesh", &c)]).unwrap();
        assert!(msg.contains("这几件网格的骨架对不上"), "{msg}");
        assert!(msg.contains("骨数不一样"), "{msg}");

        // 同名骨 bind 世界位姿差 1.0，远超 1e-3 容差
        let d = 成对(0.0, 1.5);
        let msg = parts_skeleton_mismatch(&[("a.mesh", &a), ("d.mesh", &d)]).unwrap();
        assert!(msg.contains("bip01"), "要点名哪根骨：{msg}");
        assert!(msg.contains("绑定姿态"), "{msg}");

        // 名字对不上（骨数一致但缺同名骨）也是对不上
        let mut e = SkeletonHierarchy {
            bones: vec![骨("000", None, 0.0), 骨("root2", Some(0), 0.5)],
            sockets: Vec::new(),
        };
        e.bones[0].children.push(1);
        let msg = parts_skeleton_mismatch(&[("a.mesh", &a), ("e.mesh", &e)]).unwrap();
        assert!(msg.contains("没有同名骨"), "{msg}");
    }
}
