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
use tlbb_core::preview::pose::{posed_vertices, reanchored_palette};
use tlbb_core::preview::{parse_ani, parse_geometry, parse_hierarchy, parse_nodes};

use crate::data::AppData;
use crate::inspector::{inspect, roots};
use crate::mesh_bones::mesh_bytes;
use crate::skeleton::{anim_paths, card_of, decode, locate, mesh_paths, open_db};

/// 回包用 camelCase，与 `mesh_data` / 骨架页同一套约定。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AnimPoseReply {
    /// 实际用的网格路径（客户端原文）。mesh 参数为空时是这组的第一份，
    /// 前端据此显示与切换。
    pub mesh: String,
    /// 动作文件名（.ani，客户端原文）。
    pub anim: String,
    /// 夹取后的当前帧（0..=frames-1，越界不 panic）。
    pub frame: usize,
    /// 该动作总帧数。
    pub frames: usize,
    pub vertex_count: usize,
    /// 摆好后的顶点，与 `mesh_data` 的 positions 同空间同序。
    pub positions: Vec<[f32; 3]>,
    /// 人话注记（固定三条：锚口径、帧率未证、朝向未证）。
    pub notes: Vec<String>,
}

/// `anim_pose` 命令的实现。普通函数是为了测试与将来的 `--probe` 段能无窗口
/// 走同一条路（骨架页 `skeleton_view_run` 的同款理由）。
pub fn anim_pose_run(
    app: &AppData,
    gid: i64,
    anim: &str,
    mesh: Option<&str>,
    frame: u32,
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

    // 动作：同组 `<目录>/ani/*.ani` 里按文件名找；空名字落到第一条（动作页同款）。
    let files = anim_paths(&con, &mesh_path);
    let want_anim = anim.trim();
    let picked = if want_anim.is_empty() {
        files.first().cloned()
    } else {
        files
            .iter()
            .find(|p| p.ends_with(&format!("/{want_anim}")))
            .cloned()
    }
    .ok_or_else(|| {
        if want_anim.is_empty() {
            "这一组旁边没有 ani/ 目录，客户端没给它配动作文件。".to_string()
        } else {
            format!("这一组的动作目录里没有 {want_anim}，换一条试试（同组动作以 ani/ 目录登记的为准）。")
        }
    })?;
    let anim_name = picked.rsplit('/').next().unwrap_or(want_anim).to_string();
    let (ah, pak) =
        locate(&con, &picked).ok_or_else(|| format!("{anim_name} 在容器里没有对应记录。"))?;
    let mut paks: std::collections::HashMap<String, Pak> = Default::default();
    let ani_raw = decode(&mut paks, &root, &card_of(&pak), ah)
        .ok_or_else(|| format!("{anim_name} 的字节解不出来（容器读得出记录，解码失败）。"))?;
    let a = parse_ani(&ani_raw)
        .ok_or_else(|| format!("{anim_name} 不按已知的 .ani 布局排布，读不出关键帧。"))?;

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
    })
}

#[tauri::command]
pub async fn anim_pose(
    app: State<'_, Arc<AppData>>,
    gid: i64,
    anim: String,
    mesh: Option<String>,
    frame: u32,
) -> Result<AnimPoseReply, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || {
        anim_pose_run(&app, gid, &anim, mesh.as_deref(), frame)
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

        let rep = anim_pose_run(&app, gid, &idle, None, 0).expect("第 0 帧姿势");
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
        let m = anim_pose_run(&app, gid, &idle, None, mid as u32).expect("中间帧姿势");
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
        let over = anim_pose_run(&app, gid, &idle, None, 99_999).expect("越界帧要夹住");
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
        let err = anim_pose_run(&app, gid, "不存在的动作.ani", None, 0).unwrap_err();
        assert!(!err.is_empty(), "报错不能是空串");
        assert!(err.contains("不存在的动作.ani"), "报错要带上找不到的名字：{err}");
    }
}
