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
    attach_bone_skin, parse_ani, parse_geometry, parse_hierarchy, parse_nodes, Anim, MeshGeometry,
    Node, SkeletonHierarchy,
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

/// 当前帧的骨头锚点（与 `positions` 同一空间），给画布叠加骨线用。
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AnimPoseBone {
    pub name: String,
    /// 父骨在同一个数组里的下标；根骨为空。
    pub parent: Option<usize>,
    pub pos: [f32; 3],
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
    /// 当前帧逐骨位置（与 positions 同空间），动作页「画布叠加骨架线」用。
    pub bones: Vec<AnimPoseBone>,
}

/// 当前帧的骨锚点：**绑定原点 × 该骨的蒙皮调色板**——和顶点走同一个变换，
/// 这样骨线才和画面里的身体对得上（直接用 `pose_frame` 的世界平移不在同一空间）。
/// 只发真有轨道的骨；父下标重映射到过滤后的数组。
fn anim_bones_of(h: &SkeletonHierarchy, a: &Anim, frame: usize) -> Vec<AnimPoseBone> {
    let Some(palette) = reanchored_palette(h, a, frame) else {
        return Vec::new();
    };
    let bind = bind_worlds(h);
    if palette.len() != h.bones.len() || bind.len() != h.bones.len() {
        return Vec::new();
    }
    let tracked: std::collections::HashSet<&str> =
        a.tracks.iter().map(|t| t.bone.as_str()).collect();
    let mut remap = vec![None; h.bones.len()];
    let mut kept = 0usize;
    for (i, b) in h.bones.iter().enumerate() {
        if tracked.contains(b.name.as_str()) {
            remap[i] = Some(kept);
            kept += 1;
        }
    }
    h.bones
        .iter()
        .enumerate()
        .filter_map(|(i, b)| {
            let _ = remap[i]?;
            let bm = &bind[i];
            let m = &palette[i];
            let (px, py, pz) = (bm[12], bm[13], bm[14]);
            let pos = [
                px * m[0] + py * m[4] + pz * m[8] + m[12],
                px * m[1] + py * m[5] + pz * m[9] + m[13],
                px * m[2] + py * m[6] + pz * m[10] + m[14],
            ];
            if !pos.iter().all(|v| v.is_finite()) {
                return None;
            }
            Some(AnimPoseBone {
                name: b.name.clone(),
                parent: b.parent.and_then(|p| remap.get(p).copied().flatten()),
                pos,
            })
        })
        .collect()
}

/// 动作定位与解码：同组 `<目录>/ani/*.ani` 里按文件名找；空名字落到第一条
/// （动作页同款）。返回（动作名、解析后的动作）。单件与整组两条路径共用
/// 这一个入口，报错口径与拆出来之前逐字一致。
fn pick_anim(
    con: &rusqlite::Connection,
    paks: &mut std::collections::HashMap<String, Pak>,
    root: &std::path::Path,
    mesh_paths: &[String],
    want_anim: &str,
) -> Result<(String, Anim), String> {
    // 逐份网格各自的目录都找一遍：混了别只怪衣服的组，动作可能挂在任何一份旁边
    // （长臂猿组的猿身动作在猿身目录下，衣服动作在 eyubanghunhun 目录下）。
    // 顺序 = 传入顺序，先到先得；同一份路径被点名两次只算一次。
    let mut files: Vec<String> = Vec::new();
    let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
    for m in mesh_paths {
        for p in anim_paths(con, m) {
            if seen.insert(p.clone()) {
                files.push(p);
            }
        }
    }
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
    let a = parse_ani(&ani_raw).ok_or_else(|| ani_layout_why(&anim_name, &ani_raw))?;
    Ok((anim_name, a))
}

/// `.ani` 解不出时给用户看的原因。头部能读就报骨数/帧数/差多少字节——
/// 「不按已知布局」这五个字等于什么都没说，而头部那几个数在这一族里是可信的
/// （57 骨 × 50 帧 × 32B = 91,200 字节 > 整份 27,584 ⇒ 关键帧块必然是另一种布局）。
pub(crate) fn ani_layout_why(name: &str, raw: &[u8]) -> String {
    // 0x8C 的容器标签：MIN3 = 每根骨只存真的在动的通道那一族（全库 22.4% 的动作）。
    // 说清是那一族、影响多大，比单写「不是已知布局」有用得多。
    let tag = raw
        .get(0x8c..0x90)
        .map(|s| String::from_utf8_lossy(s).into_owned())
        .unwrap_or_default();
    match tlbb_core::preview::parse_ani_header(raw) {
        Some(h) => {
            let head = format!(
                "{name}：头部 {} 骨 · {} 帧 · 帧率 {:.0}",
                h.bones, h.frames, h.tick
            );
            if tag == "MIN3" {
                // 结构摘要能算出来就把「这条动作有哪些通道」摆清楚（数都是逐骨复算过、收在文件尾的），
                // 算不出来（长度对不上）就退回原来的说法，不硬报。
                let detail = match tlbb_core::preview::ani_min3_summary(raw) {
                    Some(s) => format!(
                        "：{} 根骨里 {} 根带压缩旋转、{} 根带位移、{} 根带缩放",
                        s.bones, s.compressed_rotations, s.with_positions, s.with_scales
                    ),
                    None => String::new(),
                };
                format!(
                    "{head}。这条是 MIN3 容器：每根骨只存真在动的通道（整份 {} 字节，通吃式 32B/帧要 {} 字节）{detail}——这一族的布局与 6 字节压缩旋转都已解出（全库 2522/2522 份逐骨复算正好收在文件尾），这份却仍走不通 ⇒ 它不是同一套通道存法，读不出逐帧数据。同模型里 MIN2 的动作不受影响。",
                    h.bytes,
                    h.block_need()
                )
            } else {
                format!(
                    "{head}，但关键帧块不是已知的 32B/帧 布局（整份 {} 字节，按 32B/帧需要 {} 字节）⇒ 这一版解不出逐帧数据。",
                    h.bytes,
                    h.block_need()
                )
            }
        }
        None => format!("{name} 连头部都不是已知的 .ani 版式（信封/骨骼数/帧数对不上），读不出关键帧。"),
    }
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
    let mut paths = mesh_paths(&con, gid, &hub, &insp.dir);
    // 组里没有网格成员时：网格可能在容器里、只是清单没登记名字（如部分 NPC/怪物组）。
    // 同茎兄弟 + 路径哈希核得上就用它——路径给「动作目录」推导用，读取仍按哈希。
    let mut sib_hash: Option<String> = None;
    if paths.is_empty() {
        let stem: String = con
            .query_row("SELECT coalesce(stem,'') FROM agroups WHERE id = ?1", [gid], |r| r.get(0))
            .unwrap_or_default();
        match crate::inspector::sibling_mesh_for_group(&con, &insp.members, &stem) {
            Some((_name, hash, cand)) => {
                sib_hash = Some(hash);
                paths = vec![cand];
            }
            None => {
                return Err(
                    "这一组里没有网格文件，动作没有可蒙皮的载体，摆不了姿势。".to_string()
                )
            }
        }
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
        let (mesh_actual, raw) = mesh_bytes(app, &mesh_path, sib_hash.as_deref())?;

        // 管线（契约顺序）：骨架 → 网格几何 → 动作 → 调色板 → 蒙皮。
        // 每一步对不上都用人话说清楚，不吞错、不硬摆。
        let hier = parse_hierarchy(&raw)
            .ok_or_else(|| "这份网格没读出骨头谁挂谁，摆不了姿势（父骨链是蒙皮的前提）。".to_string())?;
        let geom = parse_geometry(&raw).map_err(|e| format!("网格几何解析失败：{e}"))?;

        let mut paks: std::collections::HashMap<String, Pak> = Default::default();
        let (anim_name, a) = pick_anim(&con, &mut paks, &root, std::slice::from_ref(&mesh_path), anim)?;

        // 帧号夹进 0..=frames-1：滑杆越界是前端的事，后端不许 panic。
        let frames = a.frames;
        let frame = (frame as usize).min(frames - 1);

        let palette = reanchored_palette(&hier, &a, frame)
            .ok_or_else(|| "调不出蒙皮调色板：有骨的姿态矩阵不可逆（缩放接近 0 或为零），这一份摆不了。".to_string())?;
        let nodes = attach_bone_skin(&hier, &parse_nodes(&raw), &raw);
        let posed = posed_vertices(&hier, &palette, &nodes, &geom.positions).ok_or_else(|| {
            "蒙皮没摆成：影响顶点表和骨架对不上（骨名对不上或顶点号越界），不硬摆。".to_string()
        })?;

        let bones = anim_bones_of(&hier, &a, frame);
        Ok(AnimPoseReply {
            mesh: mesh_actual,
            anim: anim_name,
            frame,
            frames,
            vertex_count: geom.positions.len(),
            positions: posed,
            bones,
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
        // 每件独立取字节、解骨架与几何。
        let mut preps: Vec<PartPrep> = Vec::with_capacity(hit_paths.len());
        for path in &hit_paths {
            let (actual, raw) = mesh_bytes(app, path, None)?;
            let tail = actual.rsplit('/').next().unwrap_or(path).to_string();
            let hier = parse_hierarchy(&raw).ok_or_else(|| {
                format!("这几件网格拼不了一起：{tail} 没读出骨头谁挂谁（父骨链是蒙皮的前提）。")
            })?;
            let geom =
                parse_geometry(&raw).map_err(|e| format!("{tail} 的网格几何解析失败：{e}"))?;
            let nodes = attach_bone_skin(&hier, &parse_nodes(&raw), &raw);
            preps.push(PartPrep { actual, tail, hier, geom, nodes });
        }

        // 动作整组共用一副：同目录 ani/，按第一件定位，解析一次。
        let mut paks: std::collections::HashMap<String, Pak> = Default::default();
        let (anim_name, a) = pick_anim(&con, &mut paks, &root, &hit_paths, anim)?;
        let frames = a.frames;
        let frame = (frame as usize).min(frames - 1);

        // 同一个目录里混着别只怪的衣服是常事（长臂猿组就同时躺着 32 根的 bip02
        // 衣/手套和 29 根的 bip01 猿身）。先按「这条动作的骨名」筛一遍：骨数相同、
        // 且动作里每个有名字的轨道在这件的骨架上都有同名骨，才摆得动。
        // 筛剩的再互相对账——跨件自检从「整组必须一副」改成「要一起摆的必须一副」。
        let fits = |p: &&PartPrep| -> bool {
            p.hier.bones.len() == a.tracks.len()
                && a.tracks.iter().all(|t| {
                    t.bone.is_empty() || p.hier.bones.iter().any(|b| b.name == t.bone)
                })
        };
        let kept: Vec<&PartPrep> = preps.iter().filter(fits).collect();
        let skipped: Vec<&PartPrep> = preps.iter().filter(|p| !fits(p)).collect();
        if kept.is_empty() {
            let mine = preps
                .iter()
                .map(|p| format!("{} {} 根", p.tail, p.hier.bones.len()))
                .collect::<Vec<_>>()
                .join("、");
            return Err(format!(
                "这一帧没摆出来：这条动作是 {} 根骨头的骨架，组里的网格没有一副对得上（{}）。换一条同骨架的动作才摆得动。",
                a.tracks.len(),
                mine
            ));
        }
        let refs: Vec<(&str, &SkeletonHierarchy)> =
            kept.iter().map(|p| (p.tail.as_str(), &p.hier)).collect();
        if let Some(msg) = parts_skeleton_mismatch(&refs) {
            return Err(msg);
        }


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
        for p in &kept {
            let palette = reanchored_palette(&p.hier, &a, frame).ok_or_else(|| {
                format!(
                    "{} 调不出蒙皮调色板：有骨的姿态矩阵不可逆（缩放接近 0 或为零），这一份摆不了。",
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
        if !skipped.is_empty() {
            let who = skipped
                .iter()
                .map(|p| format!("{}（{} 根）", p.tail, p.hier.bones.len()))
                .collect::<Vec<_>>()
                .join("、");
            notes.push(format!(
                "这一组里混着不止一副骨架：这条动作是 {} 根的，摆不动 {who}——要换自己那副骨架的动作才动",
                a.tracks.len()
            ));
        }
        let bones = anim_bones_of(&kept[0].hier, &a, frame);
        // 顶层字段 = parts[0]：只认「回包没有 parts 字段」的旧前端照样能摆第一件。
        let first = &out[0];
        Ok(AnimPoseReply {
            mesh: first.mesh.clone(),
            anim: anim_name,
            frame,
            frames,
            vertex_count: first.vertex_count,
            positions: first.positions.clone(),
            bones,
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

    /// MIN3 那一族的失败话术：要说清「是 MIN3、每骨只存动了的通道、影响不到 MIN2」，
    /// 不能只写「不是已知布局」——用户与下一班都靠这句话判断要不要再查。
    #[test]
    fn 解不出的话术要认出_min3_并说清影响面() {
        let mut raw = vec![0u8; 4096];
        raw[0..10].copy_from_slice(b"Copyright\x00");
        raw[0x40..0x44].copy_from_slice(b"ani\x00");
        raw[0xba..0xbc].copy_from_slice(&57u16.to_le_bytes());
        raw[0xbe..0xc0].copy_from_slice(&57u16.to_le_bytes());
        raw[0xc2..0xc4].copy_from_slice(&50u16.to_le_bytes());
        raw[0xc6..0xca].copy_from_slice(&40.0f32.to_le_bytes());
        raw[0x8c..0x90].copy_from_slice(b"MIN3");
        let why = ani_layout_why("x.ani", &raw);
        assert!(why.contains("MIN3"), "要点名容器：{why}");
        assert!(why.contains("每根骨只存真在动的通道"), "要说清这一族的形状：{why}");
        assert!(why.contains("MIN2 的动作不受影响"), "要给影响面：{why}");
        assert!(why.contains("57 骨") && why.contains("50 帧"), "头部数字要在：{why}");
        // 6 字节压缩旋转 2026-10-27 已从客户端读出来解掉，话术不能再说明码没解
        assert!(
            !why.contains("编码未解") && !why.contains("还没解"),
            "压缩旋转已解出，不许再报『没解』：{why}"
        );

        // 非 MIN3 的份仍走原来那句（别把 MIN3 的说法套到别的版本上）
        raw[0x8c..0x90].copy_from_slice(b"MIN2");
        let why2 = ani_layout_why("y.ani", &raw);
        assert!(!why2.contains("MIN3"), "{why2}");
        assert!(why2.contains("32B/帧"), "{why2}");

        // 两处计数不等的份（客户端允许，实测 longgui_b0_idle01 = 67/65）也要报得出头部数字，
        // 不能因为我们的 MIN2 闸门而退化成「连头部都不是已知版式」。
        raw[0x8c..0x90].copy_from_slice(b"MIN3");
        raw[0xbe..0xc0].copy_from_slice(&65u16.to_le_bytes());
        let why3 = ani_layout_why("z.ani", &raw);
        assert!(why3.contains("57 骨"), "{why3}");
        assert!(why3.contains("MIN3"), "{why3}");
    }

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
        // 注记必须与实测一致：一件标不标「不变形」，取决于它的节点里有没有影响顶点表。
        // 原先这里写死「手套 0 根带表骨」——10-29 变长权重表按骨名补表之后，这只怪的手套
        // 实测 bone09 带 1 张表、42 个顶点整件刚性跟随，写死的前提就烂了；改成盯一致性，
        // 数据再漂也只是换分支。
        let mut checked = 0usize;
        for p in out.iter() {
            let (_, raw) = mesh_bytes(&app, &p.mesh, None).expect("该件字节");
            let hier = parse_hierarchy(&raw).expect("该件骨架");
            let nodes = attach_bone_skin(&hier, &parse_nodes(&raw), &raw);
            let tail = p.mesh.rsplit('/').next().unwrap_or("").to_string();
            let has_table = nodes.iter().any(|n| n.skin.is_some());
            let noted = rep
                .notes
                .iter()
                .any(|n| n.contains(&tail) && n.contains("不变形"));
            assert_eq!(
                has_table, !noted,
                "{tail} 实测带表={has_table}，「不变形」注记却是 {noted}：{:?}",
                rep.notes
            );
            checked += 1;
        }
        assert!(checked >= 2, "整组注记至少核对两件，实际 {checked}");
        // 只有一张表且盖住全部顶点 ⇒ 这件整件刚性跟着那根骨走：中间帧也不许把边拉开。
        // 挂错骨、锚错空间都会在这里露出来（frame0 恒等式盯不住，那一帧本来就是恒等）。
        let mut rigid_checked = 0usize;
        for p in mout.iter() {
            let (_, raw) = mesh_bytes(&app, &p.mesh, None).expect("该件字节");
            let hier = parse_hierarchy(&raw).expect("该件骨架");
            let nodes = attach_bone_skin(&hier, &parse_nodes(&raw), &raw);
            let tables: Vec<&Node> = nodes.iter().filter(|n| n.skin.is_some()).collect();
            if tables.len() != 1 || tables[0].skin.as_ref().unwrap().vertices.len() < p.vertex_count {
                continue;
            }
            let geom = parse_geometry(&raw).expect("该件几何");
            let s = tlbb_core::preview::pose::edge_stretch(&geom.positions, &p.positions, &geom.indices);
            assert!(
                s.max_ratio <= 1.02 && s.over15 == 0,
                "{} 整件挂一根骨（{} 个顶点同表），第 {} 帧边长却变了：最大 {:.3} 倍、超 1.5 倍 {} 条",
                p.mesh,
                s.edges,
                m.frame,
                s.max_ratio,
                s.over15
            );
            rigid_checked += 1;
        }
        assert!(rigid_checked >= 1, "这组里该有一件整件刚性跟一根骨的，实际 {rigid_checked}");
        eprintln!(
            "整组：{} 件 · 注记核对 {checked} 件 · 刚性件 {rigid_checked} 件",
            out.len()
        );
    }

    /// 组里混着**两副骨架**时，动作页要按这条动作的骨名自动挑件，而不是整组报错。
    ///
    /// 真样品 `w1351_npc_changbiyuan`：同一个目录里躺着 32 根 bip02 的
    /// `w1351_monster_eyubanghunhun` 衣服 + 手套，和 29 根 bip01 的白猿本体。
    /// 旧口径先写「整组一起摆：3 件，共用一副骨架」，再被跨件自检逐帧推翻，
    /// 画布上还留着摆不动的那几件静态部件——看上去就是模型炸了。
    #[test]
    fn 混两副骨架的组按动作自动挑件() {
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let app = AppData::open(&root, &db).expect("工作台数据");
        let con = open_db(&db).expect("清单");
        let gid: i64 = con
            .query_row(
                "SELECT id FROM agroups WHERE stem = 'w1351_npc_changbiyuan'",
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
        let meshes = mesh_paths(&con, gid, &hub, &insp.dir);
        assert!(
            meshes.len() >= 3,
            "这组该同时登记了衣服/手套/猿身三份网格，实测 {}",
            meshes.len()
        );
        let tails: Vec<String> = meshes
            .iter()
            .map(|p| p.rsplit('/').next().unwrap_or("").to_string())
            .collect();
        let anim_named = |needle: &str, from: &str| -> String {
            anim_paths(&con, from)
                .into_iter()
                .map(|p| p.rsplit('/').next().unwrap_or("").to_string())
                .find(|f| f.contains(needle))
                .unwrap_or_else(|| panic!("{from} 这条路径下应有名字含 {needle} 的动作"))
        };
        let tails_of = |out: &[AnimPosePart]| -> Vec<String> {
            out.iter()
                .map(|p| p.mesh.rsplit('/').next().unwrap_or("").to_string())
                .collect()
        };

        // 32 根那条（衣服自己的骨架）：摆回衣 + 手套，猿身摆不动但要点名说明
        // 动作清单是按「那份网格自己所在的目录」取的，所以两件各要各的：
        // 衣服在 eyubanghunhun 的目录下，猿身在 w1351_npc_attack_gaoshanbaiyuan01 下。
        let bandit_mesh = meshes
            .iter()
            .find(|p| p.contains("eyubanghunhun"))
            .expect("组里应有那件别人的衣服");
        let ape_mesh = meshes
            .iter()
            .find(|p| p.contains("gaoshanbaiyuan"))
            .expect("组里应有白猿本体");
        let bandit = anim_named("eyubanghunhun_idle01", bandit_mesh);
        let rep = anim_pose_run(&app, gid, &bandit, None, 10, Some(&tails))
            .expect("32 根的动作应摆得动同骨架的衣服");
        let out = rep.parts.as_ref().expect("整组路径回包必须带 parts 字段");
        assert_eq!(out.len(), 2, "只该摆回两件同骨架的：{:?}", tails_of(out));
        assert!(
            out.iter().all(|p| p.mesh.contains("eyubanghunhun")),
            "回来的两件应是衣服/手套：{:?}",
            tails_of(out)
        );
        assert!(
            rep.notes.iter().any(|n| n.contains("摆不动")),
            "少摆的那件要说明原因：{:?}",
            rep.notes
        );

        // 29 根那条（白猿的骨架）：摆回猿身，衣服摆不动
        let ape = anim_named("gaoshanbaiyuan01_idle01", ape_mesh);
        let rep2 = anim_pose_run(&app, gid, &ape, None, 10, Some(&tails))
            .expect("29 根的动作应摆得动白猿本体");
        let out2 = rep2.parts.as_ref().expect("整组路径回包必须带 parts 字段");
        assert_eq!(out2.len(), 1, "只该摆回猿身：{:?}", tails_of(out2));
        assert!(
            out2[0].mesh.contains("gaoshanbaiyuan"),
            "回来的应是白猿本体：{:?}",
            tails_of(out2)
        );
        assert!(
            rep2.notes.iter().any(|n| n.contains("摆不动")),
            "衣服摆不动要说明：{:?}",
            rep2.notes
        );
        // 注记不许预先断言「共用一副骨架」——那是筛完才成立的话
        assert!(
            !rep.notes.iter().any(|n| n.contains("共用一副骨架")),
            "注记不许出现未经检查的断言：{:?}",
            rep.notes
        );
        eprintln!(
            "混骨架自动挑件：{} → {} 件 · {} → {} 件",
            bandit,
            out.len(),
            ape,
            out2.len()
        );
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

    /// 尾部文件名兜底（2026-10-07 验收现场抓的 bug）：骨架页 `meshes` 字段给的是
    /// 尾部名，动作页整组装载拿它调 `mesh_data`——精确路径匹配全落空，整组摆不了。
    /// 修后：尾部名解析与全路径解析必须是同一份几何；查不到的错误话术不变。
    #[test]
    fn 尾部文件名与全路径解析到同一份网格() {
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
        let full = mesh_paths(&con, gid, &hub, &insp.dir)
            .into_iter()
            .find(|p| p.ends_with("yifu_001.mesh"))
            .expect("这份网格应在组里");
        let tail = full.rsplit('/').next().unwrap_or("").to_string();
        assert!(tail.contains('.'));
        assert!(!tail.contains('/'));

        let (p_full, g_full) = app.mesh_geometry(&full, None).expect("全路径");
        let (p_tail, g_tail) = app.mesh_geometry(&tail, None).expect("尾部名兜底");
        assert_eq!(p_full, p_tail, "两种入参解析到同一条路径");
        assert_eq!(g_full.vertex_count, g_tail.vertex_count, "同一份几何");
        assert_eq!(g_full.positions, g_tail.positions, "顶点一字不差");

        // 带路径分隔符的入参不走兜底：找不到就直说找不到。
        let bad = app.mesh_geometry("data/没有这份.mesh", None);
        let msg = bad.expect_err("假路径要报错");
        assert!(msg.contains("没有找到网格文件"), "{msg}");
        assert!(!msg.contains("同名多处"), "全路径失败不该提尾部名兜底：{msg}");
    }

    /// 三百组动作体检（`#[ignore]`，显式跑：`cargo test --release -- --ignored --nocapture`）。
    ///
    /// 读 `.scratch/sweep_gids300.txt`（固定种子挑出的 300 个组号），逐组走**界面同款**那条路：
    /// 组内第一份网格 → 同目录默认动作（idle01 优先）→ `anim_pose_run` 第 0 帧与第 8 帧。
    /// 报三件事：摆不出来的组（带原话报错）、出现非有限顶点的组、零尺寸包围盒。
    ///
    /// 为什么值得单独一条：部件筛选、锚、调色板这些改动，几条单测盯不住——报错话术或分支
    /// 改坏，界面上就是几十个组同时变灰。上一班基线（2026-10-30）是 297/300 正常、
    /// 3 组「网格没读出父骨链」明确报错。
    #[test]
    #[ignore = "300 组真数据体检，显式跑：cargo test --release -- --ignored --nocapture"]
    fn 三百组动作体检_默认动作两帧都不许坏() {
        let (root, db) = roots();
        let gids_path = root.join(".scratch/sweep_gids300.txt");
        if !root.join("data.pak").is_file() || !db.is_file() || !gids_path.is_file() {
            eprintln!("跳过：本机没有客户端、资源清单或 gid 名单");
            return;
        }
        let gids: Vec<i64> = std::fs::read_to_string(&gids_path)
            .expect("名单读不出来")
            .split(|c: char| c == ',' || c.is_whitespace())
            .filter_map(|s| s.parse::<i64>().ok())
            .collect();
        assert!(!gids.is_empty(), "名单是空的？");
        let app = AppData::open(&root, &db).expect("工作台数据");
        let con = open_db(&db).expect("清单");
        let mut hub_of: std::collections::HashMap<i64, String> = Default::default();
        {
            let mut st = con.prepare("SELECT id, coalesce(hub_path,'') FROM agroups").expect("agroups");
            for r in st.query_map([], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?))).expect("查 hub")
            {
                if let Ok((i, p)) = r {
                    hub_of.insert(i, p);
                }
            }
        }
        let (mut ok, mut nan, mut zero) = (0usize, 0usize, 0usize);
        let mut errs: Vec<(i64, String)> = Vec::new();
        let mut no_anim: Vec<i64> = Vec::new();
        for gid in &gids {
            let insp = match inspect(*gid) {
                Ok(v) => v,
                Err(e) => {
                    errs.push((*gid, format!("组详情：{e}")));
                    continue;
                }
            };
            let hub = hub_of.get(gid).cloned().unwrap_or_default();
            let meshes = mesh_paths(&con, *gid, &hub, &insp.dir);
            let Some(first) = meshes.first() else {
                errs.push((*gid, "组内没有登记网格".to_string()));
                continue;
            };
            let anim = match anim_paths(&con, first).first().cloned() {
                Some(p) => p.rsplit('/').next().unwrap_or("").to_string(),
                None => {
                    no_anim.push(*gid);
                    continue;
                }
            };
            let mut bad = false;
            for frame in [0u32, 8] {
                match anim_pose_run(&app, *gid, &anim, None, frame, None) {
                    Ok(rep) => {
                        if !rep.positions.iter().all(|v| v.iter().all(|x| x.is_finite())) {
                            nan += 1;
                            bad = true;
                        }
                        let (lo, hi) = rep.positions.iter().fold(
                            ([f32::MAX; 3], [f32::MIN; 3]),
                            |(mut lo, mut hi), p| {
                                for k in 0..3 {
                                    lo[k] = lo[k].min(p[k]);
                                    hi[k] = hi[k].max(p[k]);
                                }
                                (lo, hi)
                            },
                        );
                        let vol: f32 = (0..3).map(|k| (hi[k] - lo[k]).max(0.0)).product();
                        if rep.positions.is_empty() || vol <= 1e-9 {
                            zero += 1;
                            bad = true;
                        }
                    }
                    Err(e) => {
                        errs.push((*gid, format!("第 {frame} 帧：{e}")));
                        bad = true;
                        break;
                    }
                }
            }
            if !bad {
                ok += 1;
            }
        }
        println!(
            "三百组体检：{} 组正常 / {} 组点名 · 旁边没动作 {} 组 · 非有限数 {nan} 次 · 零尺寸 {zero} 次",
            ok,
            errs.len(),
            no_anim.len()
        );
        for (g, e) in errs.iter().take(12) {
            println!("  gid {g}: {}", e.chars().take(130).collect::<String>());
        }
        assert_eq!(nan, 0, "不该出现非有限顶点：{nan} 次");
        assert_eq!(zero, 0, "不该出现零尺寸包围盒：{zero} 次");
        assert!(
            errs.len() <= 3,
            "明确报错的组不该超过 3 个（2026-10-30 基线 3/300）：{errs:?}"
        );
    }

    /// 全库「真能出图」普查（`#[ignore]`，显式跑）。页脚和筛选都缺这个数。
    ///
    /// 两条边必须**分开数**，混起来就是上一版页脚那个错（只数了第一条，却写成
    /// 「贴图名能对上文件」，读起来像全库只有 25 组能看图）：
    /// ① 清单把贴图登记成这一组的成员（`preview_candidates` 非空）；
    /// ② 材质里写了贴图名、清单没登记路径，但客户端 `convert/*` 转换路径能解出来
    ///    （`auto_texture_hash` 只做名字→哈希，不解像素，所以全库跑得动）。
    #[test]
    #[ignore = "全库普查，显式跑：cargo test --release -- --ignored --nocapture 全库真能出图"]
    fn 全库真能出图的组数普查() {
        use tlbb_core::pathmap::PathMap;
        let (root, db) = roots();
        if !root.join("data.pak").is_file() || !db.is_file() {
            eprintln!("跳过：本机没有客户端或资源清单");
            return;
        }
        let pm = PathMap::load(&root).expect("路径表读不出来");
        let app = AppData::open(&root, &db).expect("工作台数据");
        if app.scanned() == 0 {
            eprintln!("跳过：预热缓存不在（lite 是空的），普查要先有一次完整预热");
            return;
        }
        let con = open_db(&db).expect("清单");
        let gids: Vec<i64> = {
            let mut st = con.prepare("SELECT id FROM agroups ORDER BY id").expect("agroups");
            st.query_map([], |r| r.get::<_, i64>(0))
                .expect("查组号")
                .flatten()
                .collect()
        };
        let (mut member_edge, mut bridge_edge, mut either) = (0usize, 0usize, 0usize);
        let (mut names, mut names_resolved) = (0usize, 0usize);
        for gid in &gids {
            let Some(l) = app.lite_of(*gid) else { continue };
            let has_member = !l.preview_candidates.is_empty();
            let mut resolved_here = 0usize;
            for r in &l.refs {
                if !tlbb_core::catalog::labels::is_texture_name(&r.name) || r.located {
                    continue;
                }
                names += 1;
                if crate::texture_override::auto_texture_hash(&pm, &con, &r.name).is_some() {
                    resolved_here += 1;
                }
            }
            names_resolved += resolved_here;
            if has_member {
                member_edge += 1;
            }
            if resolved_here > 0 {
                bridge_edge += 1;
            }
            if has_member || resolved_here > 0 {
                either += 1;
            }
        }
        println!(
            "全库 {} 组：清单登记了贴图成员 {member_edge} 组 · 转换路径可解 {bridge_edge} 组 · 两条至少一条 {either} 组",
            gids.len()
        );
        println!("没有登记路径的贴图名 {names} 个，其中按 convert/* 转换路径可解 {names_resolved} 个");
        // 「对得上文件」不等于「解得出像素」——抽样把这一层也量掉，别在界面上报过头话。
        // 固定步长取样（每 40 个取 1），不靠随机数，重跑必得同一个数。
        let mut tried = 0usize;
        let mut decoded_ok = 0usize;
        let mut i = 0usize;
        'sample: for gid in &gids {
            let Some(l) = app.lite_of(*gid) else { continue };
            for r in &l.refs {
                if !tlbb_core::catalog::labels::is_texture_name(&r.name) || r.located {
                    continue;
                }
                let Some((hash, _)) = crate::texture_override::auto_texture_hash(&pm, &con, &r.name)
                else {
                    continue;
                };
                if i % 40 != 0 {
                    i += 1;
                    continue;
                }
                i += 1;
                let Ok(h) = u64::from_str_radix(&hash, 16) else { continue };
                tried += 1;
                if crate::texture_override::decode_candidate_png(&root, &db, h).is_ok() {
                    decoded_ok += 1;
                }
                if tried >= 400 {
                    break 'sample;
                }
            }
        }
        println!(
            "抽样 {tried} 张「对得上文件」的贴图：真解得出像素 {decoded_ok} 张 = {:.1}%",
            decoded_ok as f64 * 100.0 / tried.max(1) as f64
        );
        // 报告页的表是**按不同名字数**的（.tga 那行写「对不上的名字 8,672」），
        // 上面那两个并集数按组数、口径不一样，不能直接搬过去。这里按同名口径再量一遍。
        let mut dangling: std::collections::HashMap<String, String> = Default::default();
        for gid in &gids {
            let Some(l) = app.lite_of(*gid) else { continue };
            for r in &l.refs {
                if !r.located {
                    dangling.entry(r.name.clone()).or_insert_with(|| r.kind.clone());
                }
            }
        }
        let mut per_ext: std::collections::BTreeMap<String, (usize, usize)> = Default::default();
        for (name, kind) in &dangling {
            let hit = tlbb_core::catalog::labels::is_texture_name(name)
                && crate::texture_override::auto_texture_hash(&pm, &con, name).is_some();
            let e = per_ext.entry(kind.clone()).or_default();
            e.0 += 1;
            if hit {
                e.1 += 1;
            }
        }
        let mut solvable_total = 0usize;
        println!("按不同名字数（与报告页同口径）：类型 对不上名字数 其中可按 convert/* 对上");
        for (k, (n, s)) in &per_ext {
            solvable_total += s;
            if *s > 0 || *n > 200 {
                println!("  {k}: {n} 个名字 · 可解 {s}");
            }
        }
        println!(
            "全库对不上的名字 {} 个，其中可按客户端转换路径对上文件 {solvable_total} 个 = {:.1}%",
            dangling.len(),
            solvable_total as f64 * 100.0 / dangling.len().max(1) as f64
        );
        assert!(either >= member_edge, "并集不该小于单条边");
        assert!(gids.len() > 10_000, "名单不该只有几千组：{}", gids.len());
    }
}
