//! 灰模上的绑定姿态骨头连线。
//!
//! 只画 `.mesh` 自己的 bind，不读 `.ani`。存储的 96B 是世界绑定矩阵的逆
//! （2026-10-06 翻案，见 `pose::bind_worlds`）：骨位是求逆之后第 4 行的平移，
//! 不是存储矩阵的末行——末行那套会把骨架放平在地上。
//!
//! 没有 96B 记录的骨 `bind_worlds` 会用父骨世界占位。那是占位不是这根骨的位置，
//! 这里不给它编坐标。一段线要父和子都有自己的 bind 才成立。
//! `parse_hierarchy` 解不出时回空线，不是错误：静态网格本来就没有骨架。

use std::sync::Arc;

use serde::Serialize;
use tauri::State;
use tlbb_core::preview::pose::{bind_worlds, mat_inverse_affine};
use tlbb_core::preview::{parse_hierarchy, SkeletonHierarchy};

use crate::data::{unhex, AppData};

/// 回包与 `mesh_data` 一样用 camelCase。`lines` 两两成对，每对是父骨点、子骨点。
/// `names` 与线段平行，`[父名, 子名]`；没有线段时省略。
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MeshBoneLines {
    pub lines: Vec<[[f32; 3]; 2]>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub names: Option<Vec<[String; 2]>>,
}

/// 按名字或编号取出网格原文。查找顺序与 `AppData::mesh_geometry` 一致
/// （先编号，没有再按路径、补 `.mesh`），这里要的是字节本身，好交给
/// `parse_hierarchy`，所以不走几何解析。
fn mesh_bytes(app: &AppData, requested: &str, hash: Option<&str>) -> Result<(String, Vec<u8>), String> {
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

fn lines_from_hierarchy(h: &SkeletonHierarchy) -> MeshBoneLines {
    let pos = bind_positions(h);
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
    }
}

fn lines_from_raw(raw: &[u8]) -> MeshBoneLines {
    match parse_hierarchy(raw) {
        Some(h) => lines_from_hierarchy(&h),
        None => MeshBoneLines {
            lines: Vec::new(),
            names: None,
        },
    }
}

#[tauri::command]
pub async fn mesh_bone_lines(
    app: State<'_, Arc<AppData>>,
    name: String,
    hash: Option<String>,
) -> Result<MeshBoneLines, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || {
        let (_path, raw) = mesh_bytes(&app, &name, hash.as_deref())?;
        Ok(lines_from_raw(&raw))
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
}
