//! 灰模上的绑定姿态骨头连线。
//!
//! 只画 `.mesh` 自己的 bind，不读 `.ani` 的轨道。存储的 96B 是世界绑定矩阵的逆
//! （2026-10-06 翻案，见 `pose::bind_worlds`）：骨位是求逆之后第 4 行的平移，
//! 不是存储矩阵的末行——末行那套会把骨架放平在地上。
//!
//! 没有 96B 记录的骨（主样本 16 根：spine1/neck/head/手臂/手指/thigh/bone10 系与
//! 根 `000`）过去保持断点。现在从同组第一条 `.ani` 的**骨架静态区**反解补上
//! （`preview::rest::rebuild_bind_positions`，2026-10-07 解穿；口径：反解是
//! **推导值**，运行时对有记录的骨逐骨自检、命中率 ≥2/3 才采用，另有镜像/解剖
//! 逐骨对账，不过的骨回 `None`）。取不到 `.ani`、静态区解不出或自检不过时
//! 维持旧行为（断线），不是错误：静态网格本来就没有骨架。
//! `parse_hierarchy` 解不出时回空线，不是错误。

use std::sync::Arc;

use serde::Serialize;
use tauri::State;
use tlbb_core::preview::pose::{bind_worlds, mat_inverse_affine};
use tlbb_core::preview::rest::{rebuild_bind_positions, RestRebuild};
use tlbb_core::preview::{parse_ani, parse_hierarchy, rest_poses, SkeletonHierarchy};

use crate::data::{unhex, AppData};

/// 回包与 `mesh_data` 一样用 camelCase。`lines` 两两成对，每对是父骨点、子骨点。
/// `names` 与线段平行，`[父名, 子名]`；没有线段时省略。
/// `restFilled` 是位置来自静态区反解的骨数（推导值；0 = 全部来自存储记录）。
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MeshBoneLines {
    pub lines: Vec<[[f32; 3]; 2]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub names: Option<Vec<[String; 2]>>,
    #[serde(skip_serializing_if = "is_zero")]
    pub rest_filled: usize,
}

fn is_zero(v: &usize) -> bool {
    *v == 0
}

/// 按名字或编号取出网格原文。查找顺序与 `AppData::mesh_geometry` 一致
/// （先编号，没有再按路径、补 `.mesh`），这里要的是字节本身，好交给
/// `parse_hierarchy`，所以不走几何解析。`anim_pose` 摆姿势也要同一份字节，
/// 复用这一个定位，别让两条命令各自猜路径。
pub(crate) fn mesh_bytes(
    app: &AppData,
    requested: &str,
    hash: Option<&str>,
) -> Result<(String, Vec<u8>), String> {
    let input = requested.trim();
    let label = if input.is_empty() { "这个网格" } else { input };
    let key = match hash.map(str::trim).filter(|s| !s.is_empty()).and_then(unhex) {
        Some(h) => h,
        None => {
            let mut candidates = vec![label.to_string()];
            if !label.to_ascii_lowercase().ends_with(".mesh") {
                candidates.push(format!("{label}.mesh"));
            }
            let mut found = None;
            for path in &candidates {
                // `mesh_geometry` 用的 `q` 把查询失败吞成 Default，接着试下一条。
                // `q` 是私有的，这里用 `try_q`，失败同样当成这条路径没有命中。
                match app.try_q(|c| c.hash_by_path(path)) {
                    Ok(Some(h)) => {
                        found = Some(h);
                        break;
                    }
                    Ok(None) | Err(_) => {}
                }
            }
            found.ok_or_else(|| format!("资源清单里没有找到网格文件：{label}"))?
        }
    };
    let asset = app
        .asset(key)
        .ok_or_else(|| format!("资源清单里没有找到网格内容：{label}"))?;
    let path = asset.path.clone().unwrap_or_else(|| label.to_string());
    let raw = app
        .read(key)
        .ok_or_else(|| format!("无法从客户端容器读取网格：{path}"))?;
    Ok((path, raw))
}

/// 求逆后的世界矩阵第 4 行（行主序下标 12..14）才是骨位。非有限值不采用，
/// 免得一条 NaN 让整包序列化失败、好线段也画不出来。
fn bind_position(world: &[f32; 16]) -> Option<[f32; 3]> {
    let p = [world[12], world[13], world[14]];
    if p.iter().copied().all(f32::is_finite) {
        Some(p)
    } else {
        None
    }
}

/// 存储矩阵 → 真实骨位：求逆后取第 4 行。`bind_worlds` 对带 96B 记录的骨用的
/// 正是这一条数学（世界 = 存储值的逆），骨架页表格与这里共用同一份实现，
/// 保证表格里的数字与 3D 连线的端点同源。求逆失败（数据坏了）回 `None`，不编坐标。
pub(crate) fn bind_position_of_stored(stored: &[f32; 16]) -> Option<[f32; 3]> {
    bind_position(&mat_inverse_affine(stored)?)
}

/// 骨架树上每根骨的骨位：有自己 96B 记录的骨给 `Some`（求逆后的真实骨位），
/// 没有的给 `None`——`bind_worlds` 对那种骨填的是父骨世界的占位，拿来当
/// 骨位就是把缺 bind 的骨画成贴在父骨上。
pub(crate) fn bind_positions(h: &SkeletonHierarchy) -> Vec<Option<[f32; 3]>> {
    let worlds = bind_worlds(h);
    h.bones
        .iter()
        .zip(worlds)
        .map(|(bone, world)| {
            if bone.bind.is_none() {
                None
            } else {
                bind_position(&world)
            }
        })
        .collect()
}

/// 纯存储口径（无静态区反解）。生产路径经 [`lines_from_raw_with_ani`]；
/// 测试用它钉「反解只添不改」的基线。
#[cfg(test)]
fn lines_from_raw(raw: &[u8]) -> MeshBoneLines {
    lines_from_raw_with_ani(raw, None)
}

/// 纯存储口径的骨架版（测试用）。
#[cfg(test)]
fn lines_from_hierarchy(h: &SkeletonHierarchy) -> MeshBoneLines {
    lines_from_hierarchy_with_rest(h, None)
}

/// 骨线装配：位置来自存储记录 + （可选）静态区反解。反解只补「本来是 None」的骨，
/// 有 96B 记录的骨一律维持存储口径（两处坐标同源的既有闸门不受影响）。
fn lines_from_hierarchy_with_rest(
    h: &SkeletonHierarchy,
    rest: Option<&RestRebuild>,
) -> MeshBoneLines {
    let mut pos = bind_positions(h);
    let mut filled = 0usize;
    if let Some(rb) = rest {
        for (i, p) in rb.positions.iter().enumerate() {
            let Some(slot) = pos.get_mut(i) else { continue };
            if slot.is_none() {
                *slot = *p;
                if p.is_some() {
                    filled += 1;
                }
            }
        }
    }
    let mut lines = Vec::new();
    let mut names = Vec::new();
    for (i, bone) in h.bones.iter().enumerate() {
        let Some(parent) = bone.parent else { continue };
        if parent >= pos.len() || parent == i {
            continue;
        }
        let (Some(a), Some(b)) = (pos[parent], pos[i]) else {
            continue;
        };
        lines.push([a, b]);
        names.push([h.bones[parent].name.clone(), bone.name.clone()]);
    }
    MeshBoneLines {
        lines,
        names: if names.is_empty() { None } else { Some(names) },
        rest_filled: filled,
    }
}

/// 同组第一条 `.ani` 的字节（静态区跨动作共享，任取一条）：`<网格目录>/ani/`，
/// 按名排序取一，与骨架页动作表的取法同源。取不到（这组没配动作、清单查不到、
/// 解码失败）回 `None`——骨线退回纯存储口径，不算错。
fn ani_bytes_for_mesh(app: &AppData, mesh_path: &str) -> Option<Vec<u8>> {
    let dir = match mesh_path.rfind('/') {
        Some(i) => format!("{}/ani", &mesh_path[..i]),
        None => return None,
    };
    let (hash, _name) = app.try_q(|c| c.first_ani_in(&dir)).ok()??;
    app.read(hash)
}

fn lines_from_raw_with_ani(raw: &[u8], ani: Option<&[u8]>) -> MeshBoneLines {
    let Some(h) = parse_hierarchy(raw) else {
        return MeshBoneLines { lines: Vec::new(), names: None, rest_filled: 0 };
    };
    let rest = ani.and_then(|a| {
        let anim = parse_ani(a)?;
        let rests = rest_poses(a)?;
        rebuild_bind_positions(&h, &anim, &rests)
    });
    lines_from_hierarchy_with_rest(&h, rest.as_ref())
}

#[tauri::command]
pub async fn mesh_bone_lines(
    app: State<'_, Arc<AppData>>,
    name: String,
    hash: Option<String>,
) -> Result<MeshBoneLines, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || {
        let (path, raw) = mesh_bytes(&app, &name, hash.as_deref())?;
        let ani = ani_bytes_for_mesh(&app, &path);
        Ok(lines_from_raw_with_ani(&raw, ani.as_deref()))
    })
    .await
    .map_err(|e| e.to_string())?
}

#[cfg(test)]
mod tests {
    use super::*;
    use tlbb_core::preview::BoneNode;

    fn translation(x: f32, y: f32, z: f32) -> [f32; 16] {
        let mut m = [0.0; 16];
        m[0] = 1.0;
        m[5] = 1.0;
        m[10] = 1.0;
        m[15] = 1.0;
        m[12] = x;
        m[13] = y;
        m[14] = z;
        m
    }

    fn node(name: &str, parent: Option<usize>, bind: Option<[f32; 16]>, children: &[usize]) -> BoneNode {
        BoneNode {
            name: name.to_string(),
            parent,
            bind,
            children: children.to_vec(),
        }
    }

    fn tree(bones: Vec<BoneNode>) -> SkeletonHierarchy {
        SkeletonHierarchy {
            bones,
            sockets: Vec::new(),
        }
    }

    #[test]
    fn 解不出父骨链时回空线而不是错误() {
        let out = lines_from_raw(&[]);
        assert!(out.lines.is_empty());
        assert!(out.names.is_none());
        let v = serde_json::to_value(&out).unwrap();
        assert_eq!(v["lines"].as_array().unwrap().len(), 0);
        assert!(v.get("names").is_none());
        assert!(lines_from_raw(&[0; 32]).lines.is_empty());
    }

    #[test]
    fn 纯平移的骨位是存储值的逆不是末行() {
        // 存储 (1,2,3) 求逆后世界平移是 (-1,-2,-3)。直接拿末行会得到正号。
        let h = tree(vec![
            node("hip", None, Some(translation(1.0, 2.0, 3.0)), &[1]),
            node("knee", Some(0), Some(translation(0.0, 4.0, 0.0)), &[]),
        ]);
        let out = lines_from_hierarchy(&h);
        assert_eq!(out.lines, vec![[[-1.0, -2.0, -3.0], [0.0, -4.0, 0.0]]]);
        assert_ne!(out.lines[0][0], [1.0, 2.0, 3.0]);
        assert_ne!(out.lines[0][1], [0.0, 4.0, 0.0]);
        assert_eq!(
            out.names,
            Some(vec![["hip".to_string(), "knee".to_string()]])
        );
    }

    #[test]
    fn 带旋转时骨位也不是存储末行() {
        // 绕 Z 转 90° 再平移 (3,4,5)。逆矩阵的平移是 (-4, 3, -5)，
        // 和存储末行 (3,4,5) 不是取个反号就能得到的。
        let stored = [
            0.0, 1.0, 0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 3.0, 4.0, 5.0, 1.0,
        ];
        let h = tree(vec![
            node("hip", None, Some(stored), &[1]),
            node("knee", Some(0), Some(translation(1.0, 0.0, 0.0)), &[]),
        ]);
        let out = lines_from_hierarchy(&h);
        assert_eq!(out.lines.len(), 1);
        assert_eq!(out.lines[0][0], [-4.0, 3.0, -5.0]);
        assert_eq!(out.lines[0][1], [-1.0, 0.0, 0.0]);
        assert_ne!(out.lines[0][0], [3.0, 4.0, 5.0]);
    }

    #[test]
    fn 没有bind的骨断开连线且不把父骨位置借给它() {
        // hip、knee、toe 有 bind，ankle 没有。只该有 hip→knee 一段。
        // 若把 bind_worlds 的父骨占位当成 ankle 的坐标，knee→ankle 和 ankle→toe 都会冒出来。
        let h = tree(vec![
            node("hip", None, Some(translation(1.0, 0.0, 0.0)), &[1]),
            node("knee", Some(0), Some(translation(0.0, 2.0, 0.0)), &[2]),
            node("ankle", Some(1), None, &[3]),
            node("toe", Some(2), Some(translation(0.0, 0.0, 3.0)), &[]),
        ]);
        let out = lines_from_hierarchy(&h);
        assert_eq!(out.lines, vec![[[-1.0, 0.0, 0.0], [0.0, -2.0, 0.0]]]);
        assert_eq!(
            out.names,
            Some(vec![["hip".to_string(), "knee".to_string()]])
        );
    }

    #[test]
    fn 只有根骨或父骨没有bind时不出线() {
        let only_root = tree(vec![node("hip", None, Some(translation(1.0, 0.0, 0.0)), &[])]);
        assert!(lines_from_hierarchy(&only_root).lines.is_empty());
        let child_only = tree(vec![
            node("hip", None, None, &[1]),
            node("knee", Some(0), Some(translation(0.0, 1.0, 0.0)), &[]),
        ]);
        assert!(lines_from_hierarchy(&child_only).lines.is_empty());
        assert!(lines_from_hierarchy(&child_only).names.is_none());
    }

    #[test]
    fn 非有限平移不当成骨位() {
        let mut m = translation(0.0, 1.0, 0.0);
        m[13] = f32::NAN;
        assert!(bind_position(&m).is_none());
        m[13] = f32::INFINITY;
        assert!(bind_position(&m).is_none());
        assert_eq!(bind_position(&translation(1.0, 2.0, 3.0)), Some([1.0, 2.0, 3.0]));
    }

    /// 真数据（主样本 w1351_monster_xiyuqiezei）：静态区反解把骨线从 20 条补到
    /// 44 条，头颈链（spine→spine1→neck→head）与手臂链（clavicle→upperarm→
    /// forearm→hand）不再断；反解补位的骨数如实带在回包里，没有 `.ani` 时
    /// `restFilled` 不出现（0 跳过序列化）。
    #[test]
    fn 真数据_静态区反解补全骨线() {
        const MESH: u64 = 0xbcd65050a62986b7;
        const ANI: u64 = 0x1a2545b8c7c1d09a;
        let root = std::env::var("TLBB_ROOT").unwrap_or_else(|_| "D:/TLGL".to_string());
        let Ok(pak) = tlbb_core::jpak::Pak::open(std::path::Path::new(&root).join("data.pak")) else {
            eprintln!("跳过：本机没有 data.pak");
            return;
        };
        let raw_of = |hash: u64| -> Option<Vec<u8>> {
            let rec = pak.records().find(|r| r.hash == hash && r.stored > 0)?;
            tlbb_core::payload::decode(&pak, &rec).ok().map(|d| d.bytes)
        };
        let (Some(mesh), Some(ani)) = (raw_of(MESH), raw_of(ANI)) else {
            eprintln!("跳过：主样本资源不在容器里");
            return;
        };
        let before = lines_from_raw(&mesh);
        assert_eq!(before.lines.len(), 20, "改前只有记录骨互联");
        assert_eq!(serde_json::to_value(&before).unwrap().get("restFilled"), None);

        let after = lines_from_raw_with_ani(&mesh, Some(&ani));
        assert_eq!(after.lines.len(), 44, "补全后骨线显著增加");
        assert_eq!(after.rest_filled, 15, "反解补上位置的骨数（16 缺 1：footsteps 轨道平移会动）");
        assert_eq!(
            serde_json::to_value(&after).unwrap()["restFilled"],
            serde_json::json!(15),
            "回包要如实带出「这些坐标是反解的」"
        );
        let names = after.names.as_ref().expect("补全后该有线段名");
        let has = |a: &str, b: &str| names.iter().any(|p| p[0] == a && p[1] == b);
        assert!(has("bip01_spine", "bip01_spine1"), "头颈链 spine→spine1");
        assert!(has("bip01_spine1", "bip01_neck"), "头颈链 spine1→neck");
        assert!(has("bip01_neck", "bip01_head"), "头颈链 neck→head");
        assert!(has("bip01_l_clavicle", "bip01_l_upperarm"), "手臂链 clavicle→upperarm");
        assert!(has("bip01_l_upperarm", "bip01_l_forearm"), "手臂链 upperarm→forearm");
        assert!(has("bip01_l_forearm", "bip01_l_hand"), "手臂链 forearm→hand");
        // 有记录骨的线两版一致：存储口径一动不动，反解只添不改
        for pair in before.names.as_ref().expect("改前也有线段名") {
            assert!(
                names.iter().any(|p| p[0] == pair[0] && p[1] == pair[1]),
                "改前的线 {}→{} 在补全后消失了",
                pair[0],
                pair[1]
            );
        }
        assert_eq!(names.len(), before.names.as_ref().unwrap().len() + 24);
    }
}
