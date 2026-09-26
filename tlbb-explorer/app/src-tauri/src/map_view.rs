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
//!
//! 俯视缩略图走 `map_footprint`：同一套装配、同一套计数，只是几何缓冲不打包
//! （`buffer` 为空串）。列表 300 张图若逐个拉全量回包，光 base64 就把首屏拖死；
//! 计数若另写一份，列表上的数和点进去的数迟早对不上。

use std::collections::HashMap;
use std::sync::Arc;

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
    /// 指回 [`MapScene::grid_files`]：这条摆位记录出自哪个格子文件。
    pub grid_index: usize,
    /// 该格子文件里的第几条记录（从 0 起）。与 `grid_index` 一起才回得去那一条。
    pub record_index: usize,
}

/// 非网格名字按扩展名聚合的一行。
#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExtCount {
    pub ext: String,
    pub records: usize,
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
    /// 叫 `某某.mesh`、但客户端里查不到这个文件：这是真缺。
    pub missing_meshes: usize,
    /// 名字带的扩展名不是 `.mesh`（实测大理这张图是 10 条 `.pu` 特效）。
    /// **这类不是缺**：文件在客户端里真实存在，只是这一版只摆网格、不画特效。
    pub not_mesh: usize,
    /// 名字既不像文件名、也不像路径（32 位大写十六进制那种）：不猜它是什么。
    pub odd_names: usize,
    /// 清单说有、容器里取不出字节：读取失败，不能算「没有这个物件」。
    pub unreadable_meshes: usize,
    pub empty_named: usize,
    /// 目录查询本身失败的次数（SQL 抖动/锁被占）。这类失败绝不能混进
    /// missing_meshes——那会把一次查询事故显示成「客户端里没有这个文件」，
    /// 正是 `try_q` 注释里立下的红线要防的事。
    pub catalog_errors: usize,
    /// 去重后真正要画的网格数。
    pub unique_meshes: usize,
    pub meshes: Vec<MeshData>,
    pub instances: Vec<MapInstance>,
    /// 交出过实例的格子文件名原文（`85_3_118.scene` 那种），按 `MapInstance.grid_index` 索引。
    /// 加它的唯一理由：点中一个物件要能回查到「哪个文件的第几条」，
    /// 否则「带来源证据」只是句空话——朝向与坐标这一步全靠这种回查。
    pub grid_files: Vec<String>,
    pub grid_reasons: Vec<GridReason>,
    /// 真缺的那些名字原样列举到封顶为止，超了就只报个数——不去猜它该用哪个模型。
    pub missing_sample: Vec<String>,
    pub missing_truncated: bool,
    /// 不是网格的名字按扩展名聚合（`.pu` 10 条这种），因为它们各有各的说法。
    pub other_ext: Vec<ExtCount>,
}

/// 名字属于哪一类：只看扩展名，不看它"应该"是什么。
/// `.mesh` 才是这一版画得了的东西；带别的扩展名说明客户端里本来就有那个文件
/// （`.pu` 特效实测就在 `data/effect/pu_scene/`），说成「没有这个文件」是谎话。
fn kind_of(name: &str) -> (String, bool) {
    let Some((_, ext)) = name.rsplit_once('.') else {
        return (String::new(), false);
    };
    let e = ext.to_ascii_lowercase();
    if e == "mesh" {
        return ("mesh".to_string(), true);
    }
    // 扩展名是 1~6 个字母数字才算"这是个文件名"；否则算认不出来的怪名字。
    let plausible = e.len() <= 6 && e.chars().all(|c| c.is_ascii_alphanumeric());
    // 第二个返回值是 is_mesh，只有 `.mesh` 才是 true —— 走到这里必然不是网格，
    // 别把 plausible 当它返回：那样会把 .pu 特效算成「客户端里没有这个文件」。
    (if plausible { e } else { String::new() }, false)
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

/// 地图清单唯一的实现。命令层和 `--maps` 无窗口验收都走这里：
/// 清单若另写一份，测到的就不是用户点进去看到的那一份。
pub fn list_of(app: &AppData, limit: usize) -> Result<Vec<MapRow>, String> {
    let rows = app.try_q(|c| c.map_dirs(limit.clamp(1, 500)))?;
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

// 命令一律 async + spawn_blocking：sync 命令在主线程跑，解析大图那几百毫秒会把
// 整个窗口冻住，缩略图懒加载还会并发打进来。另外，`State<'_, AppData>` 取不到
// 被 manage 的 `Arc<AppData>`（tauri 按 TypeId 精确匹配），真窗口里一调就
// panic——自测台走假后端，此前从没测到这一层，改参数类型才炸出来。
#[tauri::command]
pub async fn map_list(
    app: State<'_, Arc<AppData>>,
    limit: usize,
) -> Result<Vec<MapRow>, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || list_of(&app, limit))
        .await
        .map_err(|e| e.to_string())?
}

#[tauri::command]
pub async fn map_scene(app: State<'_, Arc<AppData>>, id: String) -> Result<MapScene, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || scene_of(&app, &id))
        .await
        .map_err(|e| e.to_string())?
}

/// 俯视缩略图专用：回包结构与 `map_scene` 逐字段一致，只是每个网格 `buffer` 为空。
#[tauri::command]
pub async fn map_footprint(
    app: State<'_, Arc<AppData>>,
    id: String,
) -> Result<MapScene, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || footprint_of(&app, &id))
        .await
        .map_err(|e| e.to_string())?
}

/// 装配一张图的全部工作。命令层只负责把 `State` 解开。
///
/// 之所以单独是个普通函数：`--map <ID>` 要能**无窗口跑同一条路径**做验收。
/// 验收如果去跑另一份"给测试看的"实现，测到了也不代表用户看到的那条链是对的。
pub fn scene_of(app: &AppData, raw_id: &str) -> Result<MapScene, String> {
    assemble(app, raw_id, true)
}

/// `map_footprint` 的实现：同一套装配，`with_geometry=false` 时每个网格只留
/// 包围盒、不打包 base64。缩略图只需要「物件摆在哪、占多大」，不需要顶点流。
pub fn footprint_of(app: &AppData, raw_id: &str) -> Result<MapScene, String> {
    assemble(app, raw_id, false)
}

fn assemble(app: &AppData, raw_id: &str, with_geometry: bool) -> Result<MapScene, String> {
    let id = raw_id.trim().to_string();
    if id.is_empty() || id.contains('/') || id.contains('\\') || id.contains("..") {
        return Err("地图 ID 要么是客户端原文那个名字，要么不查".into());
    }
    let dir = format!("mobile_maps/{id}");
    let grids = app.try_q(|c| c.scene_grids(&dir))?;
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
        missing_meshes: 0,
        not_mesh: 0,
        odd_names: 0,
        unreadable_meshes: 0,
        empty_named: 0,
        catalog_errors: 0,
        unique_meshes: 0,
        meshes: Vec::new(),
        instances: Vec::new(),
        grid_files: Vec::new(),
        grid_reasons: Vec::new(),
        missing_sample: Vec::new(),
        missing_truncated: false,
        other_ext: Vec::new(),
    };
    // 网格哈希 → 池下标；同一个网格被 500 个格子引用，也只解码一次。
    let mut pool: HashMap<u64, usize> = HashMap::new();
    // 裸名 → 哈希：一张图里同名物件极多，别每条记录都去问一次 SQLite。
    let mut named: HashMap<String, Option<u64>> = HashMap::new();
    let mut reasons: HashMap<String, (usize, Vec<String>)> = HashMap::new();

    for (hash, grid_name) in grids {
        let Some(raw) = app.read(hash) else {
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
        // 这个格子第一次交出可画的实例时才登记文件名，grid_index 与 grid_files 才对得上。
        let mut gi: Option<usize> = None;
        for (record_index, inst) in grid.instances.into_iter().enumerate() {
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
                None => match app.try_q(|c| c.hash_by_name_in(SOURCE_DIR, &inst.name)) {
                    Ok(h) => {
                        named.insert(inst.name.clone(), h);
                        h
                    }
                    Err(e) => {
                        // 查询失败 ≠ 客户端没有：如实计数并按原因聚合，
                        // 不许把一次 SQL 事故洗成「missing_meshes」那样的数据结论。
                        out.catalog_errors += 1;
                        note(&mut reasons, &format!("目录查询失败：{e}"), &inst.name);
                        continue;
                    }
                },
            };
            let Some(key) = hit else {
                let (ext, is_mesh) = kind_of(&inst.name);
                if is_mesh {
                    out.missing_meshes += 1;
                    if out.missing_sample.len() < 60 {
                        out.missing_sample.push(inst.name.clone());
                    } else {
                        out.missing_truncated = true;
                    }
                } else if ext.is_empty() {
                    out.odd_names += 1;
                } else {
                    out.not_mesh += 1;
                    match out.other_ext.iter_mut().find(|x| x.ext == ext) {
                        Some(x) => x.records += 1,
                        None => out.other_ext.push(ExtCount { ext: ext.to_string(), records: 1 }),
                    }
                }
                continue;
            };
            let idx = match pool.get(&key) {
                Some(i) => *i,
                None => {
                    let Some(bytes) = app.read(key) else {
                        // 清单说有、容器取不出来：这是读取失败，不能算"没有这个物件"。
                        out.unreadable_meshes += 1;
                        continue;
                    };
                    match parse_geometry(&bytes) {
                        Ok(g) => {
                            let path = format!("{SOURCE_DIR}/{}", inst.name);
                            out.meshes.push(if with_geometry {
                                MeshData::from((path, g))
                            } else {
                                MeshData::outline(path, &g)
                            });
                            let i = out.meshes.len() - 1;
                            pool.insert(key, i);
                            i
                        }
                        Err(_) => {
                            out.unreadable_meshes += 1;
                            continue;
                        }
                    }
                }
            };
            out.resolved += 1;
            let grid_index = match gi {
                Some(i) => i,
                None => {
                    out.grid_files.push(grid_name.clone());
                    let i = out.grid_files.len() - 1;
                    gi = Some(i);
                    i
                }
            };
            out.instances.push(MapInstance {
                mesh_index: idx,
                matrix: inst.matrix,
                grid_index,
                record_index,
            });
        }
    }

    out.unique_meshes = out.meshes.len();
    out.other_ext.sort_by(|a, b| b.records.cmp(&a.records));
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
