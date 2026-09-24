//! 地图链路：一张图的格子 → 摆位记录 → 物件几何，一次回包全给了。
//!
//! 为什么不照单模型那样逐个 `mesh_data`：一张图的唯一网格实测约 214 个，
//! 逐个请求就是 214 次 IPC 往返，首图加载被往返拖死（前端 `base64Bytes` 解
//! 6.2MB 只要 22ms，瓶颈从来不是解码）。所以这里把去重后的几何池和实例表打
//! 成一份，实例表用的就是前端 `expandInstances` 已经吃的那个形状
//! （`{ meshIndex, matrix: [f32;16] }`），不新造第二套契约。
//!
//! 矩阵排布：**`matrix` 是 `.scene` 记录里那 16 个 f32 的原样直读**，即 GL 布局
//! （平移在 `[12..14]`）。这里不转置、前端不转置、进 GL 不转置——多转一次会把
//! 平移搬走，整图物件叠在世界原点且不报错。理由见 `preview::scene` 模块文档。

use std::collections::HashMap;

use serde::Serialize;
use tauri::State;
use tlbb_core::preview::{parse_geometry, parse_scene, SceneError};

use crate::data::AppData;
use crate::mesh_view::MeshData;

/// 物件几何所在的虚拟目录。格子里存的是**带扩展名的裸名**（如
/// `w1351_dl_bajiao_001.mesh`），而 `hash_by_path` 要整路径，直接喂必查空，
/// 所以只能按 `dir + name` 查。
const SOURCE_DIR: &str = "mobile_maps_source";

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MapRow {
    /// 客户端原文地图 ID（`w1351_ll_dl_002`）。**没有中文名可显示**：
    /// 全库 `agroup_names` 含中文的只有 10 条且 0 条是地图名，编一个就是造假。
    pub id: String,
    /// 该目录下 `.scene` 格子文件的个数（分母就是这个数，不是"客户端承认的地图全集"）。
    pub grids: usize,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MapInstance {
    /// 指回 [`MapScene::meshes`] 的下标。
    pub mesh_index: usize,
    /// `.scene` 记录原样直读的 16 个 f32（GL 布局，平移在 [12..14]）。
    pub matrix: [f32; 16],
}

/// 一个格子文件为什么没交出实例——按类型聚合，不逐条铺（一张图可能上千格）。
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GridReason {
    pub reason: String,
    pub grids: usize,
    /// 最多三个格子文件名，让人能自己去翻那一个；不是逐条清单。
    pub sample: Vec<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MapScene {
    pub id: String,
    /// 目录下的格子文件数（分母）。
    pub grids: usize,
    /// 只有 4 字节的空格子：这格本来就没摆东西，不是读失败。
    pub empty_grids: usize,
    /// 读不通的格子数（版权头容器、水面参数等**不是物件表**的东西）。
    pub unreadable_grids: usize,
    /// 走通了多少条摆位记录。**不是**格子头部声明的条数——声明是上界，
    /// 全库复算 `n > declared` 0 例、`n < declared` 3,620 例，拿它显示会偏大。
    pub records: usize,
    /// 名字能在几何池里找到实体的条数。
    pub resolved: usize,
    /// 对不上名字、以及名字为空的条数（这两类界面要分开说，别混成一个「缺」）。
    pub unmatched: usize,
    pub empty_named: usize,
    /// 去重后真正要画的网格数。
    pub unique_meshes: usize,
    pub meshes: Vec<MeshData>,
    pub instances: Vec<MapInstance>,
    pub grid_reasons: Vec<GridReason>,
    /// 对不上名字的原样列举到封顶为止，超了就只报个数——不去猜它该用哪个模型。
    pub unmatched_sample: Vec<String>,
    pub unmatched_truncated: bool,
}

fn why(e: &SceneError) -> String {
    match e {
        SceneError::TooShort => "只有 4 字节：这格没摆东西".into(),
        SceneError::UnknownVersion(t) => format!("版本号 {t} 不在已知集合"),
        SceneError::LayoutUndetermined { failed_at } => {
            format!("按 12 字节头 + 步长走不通（第 {failed_at} 条起），这不是物件清单")
        }
    }
}

/// 按原因聚合：一张图可能上千格都栽在同一处，逐条铺会把界面埋掉。
/// 但每类留三个格子名，否则"有 295 个格子不是物件表"这种话没法复查。
fn note(map: &mut HashMap<String, (usize, Vec<String>)>, reason: &str, grid: &str) {
    let e = map.entry(reason.to_string()).or_insert_with(|| (0, Vec::new()));
    e.0 += 1;
    if e.1.len() < 3 {
        e.1.push(grid.to_string());
    }
}

#[tauri::command]
pub fn map_list(state: State<'_, AppData>, limit: usize) -> Result<Vec<MapRow>, String> {
    let rows = state.try_q(|c| c.map_dirs(limit.clamp(1, 500)))?;
    Ok(rows
        .into_iter()
        .filter_map(|(dir, grids)| {
            // 目录形如 `mobile_maps/<ID>`；不是这个形状的不要硬凑一个 ID 出来。
            let id = dir.strip_prefix("mobile_maps/")?;
            Some(MapRow {
                id: id.to_string(),
                grids,
            })
        })
        .collect())
}

#[tauri::command]
pub fn map_scene(state: State<'_, AppData>, id: String) -> Result<MapScene, String> {
    let id = id.trim().to_string();
    if id.is_empty() || id.contains('/') || id.contains('\\') || id.contains("..") {
        return Err("地图 ID 要么是客户端原文那个名字，要么不查".into());
    }
    let dir = format!("mobile_maps/{id}");
    let grids = state.try_q(|c| c.scene_grids(&dir))?;
    if grids.is_empty() {
        return Err(format!(
            "资源清单里 `{dir}` 下没有任何格子文件。没有，不等于这张图是空的——\
             也可能是这张图从来没被解包进来。"
        ));
    }

    let mut out = MapScene {
        id,
        grids: grids.len(),
        empty_grids: 0,
        unreadable_grids: 0,
        records: 0,
        resolved: 0,
        unmatched: 0,
        empty_named: 0,
        unique_meshes: 0,
        meshes: Vec::new(),
        instances: Vec::new(),
        grid_reasons: Vec::new(),
        unmatched_sample: Vec::new(),
        unmatched_truncated: false,
    };
    // 网格哈希 → 池下标；同一个网格被 500 个格子引用，也只解码一次。
    let mut pool: HashMap<u64, usize> = HashMap::new();
    // 裸名 → 哈希：一张图里同名物件极多，别每条记录都去问一次 SQLite。
    let mut named: HashMap<String, Option<u64>> = HashMap::new();
    let mut reasons: HashMap<String, (usize, Vec<String>)> = HashMap::new();

    for (hash, grid_name) in grids {
        let Some(raw) = state.read(hash) else {
            note(
                &mut reasons,
                "读不到字节：清单说在这，容器里没取出来",
                &grid_name,
            );
            continue;
        };
        let grid = match parse_scene(&raw) {
            Ok(g) => g,
            Err(e) => {
                let k = why(&e);
                if matches!(e, SceneError::TooShort) {
                    out.empty_grids += 1;
                } else {
                    out.unreadable_grids += 1;
                }
                note(&mut reasons, &k, &grid_name);
                continue;
            }
        };
        for inst in grid.instances {
            out.records += 1;
            if inst.name.trim().is_empty() {
                out.empty_named += 1;
                continue;
            }
            // 先取值再回填：直接在 `match named.get(..)` 的分支里 insert 会撞上借用检查
            // （match 的 scrutinee 借用横跨所有分支）。
            let cached = named.get(&inst.name).copied();
            let hit = match cached {
                Some(h) => h,
                None => {
                    let h = state
                        .try_q(|c| c.hash_by_name_in(SOURCE_DIR, &inst.name))
                        .unwrap_or(None);
                    named.insert(inst.name.clone(), h);
                    h
                }
            };
            let Some(key) = hit else {
                out.unmatched += 1;
                if out.unmatched_sample.len() < 60 {
                    out.unmatched_sample.push(inst.name.clone());
                } else {
                    out.unmatched_truncated = true;
                }
                continue;
            };
            let idx = match pool.get(&key) {
                Some(i) => *i,
                None => {
                    let Some(bytes) = state.read(key) else {
                        // 清单说有、容器取不出来：这是读取失败，不能算"没有这个物件"。
                        out.unmatched += 1;
                        if out.unmatched_sample.len() < 60 {
                            out.unmatched_sample.push(format!("{}（取不到字节）", inst.name));
                        } else {
                            out.unmatched_truncated = true;
                        }
                        continue;
                    };
                    match parse_geometry(&bytes) {
                        Ok(g) => {
                            let path = format!("{SOURCE_DIR}/{}", inst.name);
                            out.meshes.push(MeshData::from((path, g)));
                            let i = out.meshes.len() - 1;
                            pool.insert(key, i);
                            i
                        }
                        Err(e) => {
                            out.unmatched += 1;
                            if out.unmatched_sample.len() < 60 {
                                out.unmatched_sample.push(format!("{}（{e}）", inst.name));
                            } else {
                                out.unmatched_truncated = true;
                            }
                            continue;
                        }
                    }
                }
            };
            out.resolved += 1;
            out.instances.push(MapInstance {
                mesh_index: idx,
                matrix: inst.matrix,
            });
        }
    }

    out.unique_meshes = out.meshes.len();
    let mut v: Vec<GridReason> = reasons
        .into_iter()
        .map(|(reason, (grids, sample))| GridReason {
            reason,
            grids,
            sample,
        })
        .collect();
    v.sort_by(|a, b| b.grids.cmp(&a.grids).then(a.reason.cmp(&b.reason)));
    out.grid_reasons = v;
    Ok(out)
}
