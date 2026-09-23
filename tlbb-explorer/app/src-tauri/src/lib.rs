//! The IPC surface of the workbench. Commands are thin: they read the shared state,
//! hand back a view model, and never let the frontend ask for a path or a byte range —
//! the shell decides what to read, and only ever read-only.

mod data;
mod inspector;
mod mdl_view;
mod model;
mod mesh_view;
mod present;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{Emitter, Manager, State};

use data::AppData;
use model::{CitedByView, Detail, Filter, Image, Page, RefView, Stats};

/// The shipped client and the catalog it was indexed into. Overridable so the tool can
/// be pointed at another install; both are opened read-only.
fn roots() -> (PathBuf, PathBuf) {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    (root, db)
}

/// 左栏筛选后的卡片列表。
#[tauri::command]
async fn list_groups(app: State<'_, Arc<AppData>>, filter: Option<Filter>) -> Result<Page, String> {
    let app = Arc::clone(&app);
    let filter = filter.unwrap_or_default();
    tauri::async_runtime::spawn_blocking(move || app.page(&filter))
        .await
        .map_err(|e| e.to_string())
}

/// 中文检索：把输入转成拼音拼法再比对，前端不重做这一步。
#[tauri::command]
async fn search(
    app: State<'_, Arc<AppData>>,
    query: String,
    limit: Option<usize>,
) -> Result<Page, String> {
    let app = Arc::clone(&app);
    let filter = Filter {
        query: Some(query),
        limit: Some(limit.unwrap_or(150)),
        ..Default::default()
    };
    tauri::async_runtime::spawn_blocking(move || app.page(&filter))
        .await
        .map_err(|e| e.to_string())
}

/// 右栏证据链。
#[tauri::command]
async fn card_detail(app: State<'_, Arc<AppData>>, gid: i64) -> Result<Detail, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || {
        app.detail(gid)
            .ok_or_else(|| "这条记录还在读取中，稍等一下".to_string())
    })
    .await
    .map_err(|e| e.to_string())?
}

/// 指定资源的现场解码结果（PNG/WebP 字节）。解不出来就返回空，绝不画一张假的。
#[tauri::command]
async fn preview(app: State<'_, Arc<AppData>>, hash: String) -> Result<Option<Image>, String> {
    let app = Arc::clone(&app);
    let hash = data::unhex(&hash).ok_or_else(|| "编号格式不对".to_string())?;
    tauri::async_runtime::spawn_blocking(move || app.image_of(hash))
        .await
        .map_err(|e| e.to_string())
}

/// 整组里第一张真能解出来的图。
#[tauri::command]
async fn group_preview(app: State<'_, Arc<AppData>>, gid: i64) -> Result<Option<Image>, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || app.group_image(gid))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
async fn stats(app: State<'_, Arc<AppData>>) -> Result<Stats, String> {
    let app = Arc::clone(&app);
    tauri::async_runtime::spawn_blocking(move || app.stats())
        .await
        .map_err(|e| e.to_string())
}

/// 引用图谱健康度：总引用、已解析、悬空清单。数字全部来自 `Catalog`，不由前端或脚本自算。
#[tauri::command]
async fn ref_health(
    app: State<'_, Arc<AppData>>,
    dangling_limit: Option<usize>,
) -> Result<RefView, String> {
    let app = Arc::clone(&app);
    let limit = dangling_limit.unwrap_or(60).clamp(1, 500);
    tauri::async_runtime::spawn_blocking(move || app.ref_view(limit))
        .await
        .map_err(|e| e.to_string())
}

/// 谁的文件内容里提到了这个资源。`key` 可以是 16 位编号，也可以是客户端原文名——
/// 悬空名字没有编号，只有按名反查这一条路。注意是「提到」，不是「共享」。
#[tauri::command]
async fn cited_by(
    app: State<'_, Arc<AppData>>,
    key: String,
    limit: Option<usize>,
) -> Result<CitedByView, String> {
    let app = Arc::clone(&app);
    let limit = limit.unwrap_or(120).clamp(1, 500);
    tauri::async_runtime::spawn_blocking(move || app.cited_by(&key, limit))
        .await
        .map_err(|e| e.to_string())
}

pub fn run() {
    let (root, db) = roots();
    let app = match AppData::open(&root, &db) {
        Ok(a) => a,
        Err(e) => fatal(&e),
    };
    app.warm();

    tauri::Builder::default()
        .manage(Arc::clone(&app))
        .setup(move |handle| {
            let app = Arc::clone(handle.state::<Arc<AppData>>().inner());
            let sink = handle.app_handle().clone();
            let total = app.triage().0;
            std::thread::spawn(move || loop {
                let done = app.ready();
                let _ = sink.emit(
                    "reading",
                    serde_json::json!({ "scanned": app.scanned(), "total": total, "ready": done }),
                );
                if done {
                    break;
                }
                std::thread::sleep(std::time::Duration::from_millis(700));
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            list_groups,
            search,
            card_detail,
            preview,
            group_preview,
            stats,
            ref_health,
            cited_by,
            mdl_view::mdl_compose,
            inspector::asset_list,
            inspector::asset_inspect,
            mesh_view::mesh_data
        ])
        .run(tauri::generate_context!())
        .expect("工作台窗口未能启动");
}

/// A missing install should say so in the log rather than open an empty window.
fn fatal(msg: &str) -> ! {
    eprintln!("启动失败：{msg}");
    eprintln!("（可用环境变量 TLBB_ROOT / TLBB_DB 指定客户端与清单位置）");
    std::process::exit(2);
}

/// Read-only self-check: exercises the whole pipeline without a webview so the shell can
/// be verified in a headless run. `tlbb-shell --probe [中文词]`
pub fn probe(word: Option<String>) {
    let (root, db) = roots();
    let app = match AppData::open(&root, &db) {
        Ok(a) => a,
        Err(e) => fatal(&e),
    };
    let (groups, containers, records) = app.triage();
    println!("资源组 {groups} · 数据容器 {containers} 个 · 索引条目 {records} 条");
    let t = std::time::Instant::now();
    app.warm();
    while !app.ready() {
        std::thread::sleep(std::time::Duration::from_millis(200));
        if t.elapsed().as_secs() > 1 {
            print!("\r  已读取 {}/{} …      ", app.scanned(), groups);
            use std::io::Write;
            let _ = std::io::stdout().flush();
        }
    }
    println!("\n全部读取耗时 {:.1}s", t.elapsed().as_secs_f64());
    let s = app.stats();
    println!(
        "统计：带贴图线索 {} · 主体可读回 {} · 名称可定位 {}/{}",
        s.image_candidates, s.decoded, s.located_refs, s.total_refs
    );
    for g in s.grades.iter() {
        println!("  等级 {}（{}）：{}", g.value, g.label, g.count);
    }
    // Citation health. Printed from the same view the panel will render, so the panel
    // and this line can never disagree.
    let rv = app.ref_view(12);
    println!(
        "\n引用健康度：总引用 {} · 已解析 {} ({}%) · 悬空名字 {} · 有引用资产 {}/{}",
        rv.refs_total, rv.refs_resolved, rv.resolved_pct, rv.dangling_names,
        rv.assets_citing_resolved, rv.assets_citing
    );
    for e in rv.by_ext.iter() {
        println!(
            "   {:>8} 合计 {:>6} 已解析 {:>6} ({}%) 悬空名字 {}",
            e.kind, e.total, e.resolved, e.resolved_pct, e.dangling_names
        );
    }
    println!("  引用最多（已解析）：");
    for c in rv.top_cited.iter() {
        println!("   {} {} {citations}", c.name, c.kind, citations = c.citations);
    }
    println!("  TOP 悬空：");
    for d in rv.top_dangling.iter().take(6) {
        println!("   {} {} {citations}", d.name, d.kind, citations = d.citations);
    }
    let tops = app.top_cited(6);
    if let Some((h, name, _)) = tops.first() {
        let by = app.cited_by(&format!("{h:016x}"), 6);
        println!(
            "  反查 {name} → {} 条 (截断 {})：",
            by.citations.len(),
            by.truncated
        );
        for c in by.citations.iter() {
            println!("     {} {}", c.kind, c.from_path);
        }
    }
    let mut queries = word.iter().map(|s| s.as_str()).collect::<Vec<_>>();
    queries.extend(["曹霜", "宠物", "boss"]);
    for q in queries {
        let page = app.page(&Filter {
            query: Some(q.into()),
            limit: Some(5),
            ..Default::default()
        });
        println!(
            "查询「{q}」→ {} 命中（候选拼写 {:?}）",
            page.total, page.query_words
        );
        for c in &page.items {
            println!(
                "   {} · {} · {} · 等级 {} · 标签 {:?} · 引用 {}/{}",
                c.gid, c.name, c.scenario, c.grade, c.tags, c.located_total, c.ref_total
            );
            if let Some(d) = app.detail(c.gid) {
                println!("      缺口 {:?} | 名称来源 {}", d.gaps, d.name_source);
                for r in d.refs.iter().take(3) {
                    println!("      引用 {} {} {}", r.kind, r.name, r.status);
                }
                let img = c
                    .preview_hash
                    .as_deref()
                    .and_then(data::unhex)
                    .and_then(|h| app.image_of(h))
                    .map(|i| format!("{}x{} {}", i.width, i.height, i.format))
                    .unwrap_or_else(|| "无".into());
                println!("      技术：{} 图：{}", d.tech.id, img);
            }
        }
    }

    // ---- M1 验收：模型组成 Inspector（无头可核，带计时） ----
    // 调两次：首次含容器索引冷缓存，二次是用户真实体验的热路径——
    // 「打开一个资源 <1 秒」验收的是第二次。
    println!("\n模型组成（M1 验收）· w1351_monster_xiyuqiezei");
    for round in 1..=2 {
        let t0 = std::time::Instant::now();
        let tag = if round == 1 { "首次" } else { "再次" };
        match mdl_view::mdl_compose_run("w1351_monster_xiyuqiezei") {
        Ok(r) => {
            println!(
                "  模型名   {}",
                if r.name.is_empty() { "<未读到>" } else { &r.name }
            );
            for s in &r.skeletons {
                println!("  骨架     {} → {}", s.name, s.path.as_deref().unwrap_or("缺"));
            }
            for b in &r.bodies {
                println!("  部件 [{}]", if b.label.is_empty() { "-" } else { &b.label });
                println!(
                    "    网格   {} → {}",
                    b.mesh.name,
                    b.mesh.path.as_deref().unwrap_or("缺")
                );
                println!(
                    "    材质   {} → {}",
                    b.material.name,
                    b.material.path.as_deref().unwrap_or("缺")
                );
                for t in &b.texture_slots {
                    let where_at = t
                        .path
                        .as_deref()
                        .unwrap_or(if t.resolved { "（定位到无名实体）" } else { "缺" });
                    println!("      槽位 {} {} → {}", t.role, t.name, where_at);
                }
            }
            println!(
                "  动作     {} 个：{}",
                r.animations.len(),
                r.animations
                    .iter()
                    .map(|a| a.name.as_str())
                    .collect::<Vec<_>>()
                    .join(" ")
            );
            let dangling: usize = r
                .bodies
                .iter()
                .map(|b| b.texture_slots.iter().filter(|t| !t.resolved).count())
                .sum();
            if dangling > 0 {
                println!(
                    "  缺失说明：{dangling} 个槽位只有名字、没有 hash 映射——\
                     客户端发布时未保存模型贴图的路径，这是客户端的设计，不是解析失败。"
                );
            }
        }
        Err(e) => println!("  ✗ {e}"),
        }
        println!("  [{tag}] 耗时 {:.0}ms", t0.elapsed().as_secs_f64() * 1000.0);
    }

    // ---- M2-2 验收：网格几何 → 前端 3D 预览实际收到的数据 ----
    // 缓冲区字节数就是 IPC 实际负载（base64 后再 ×4/3），用它判断「大模型会不会卡」。
    println!("\n网格几何（M2-2 验收）");
    if let Ok(r) = mdl_view::mdl_compose_run("w1351_monster_xiyuqiezei") {
        for b in &r.bodies {
            let name = if b.mesh.name.is_empty() { "-" } else { &b.mesh.name };
            match app.mesh_geometry(name, b.mesh.hash.as_deref()) {
                Ok((path, g)) => report_mesh(&path, &g),
                Err(e) => println!("  ✗ {name} → {e}"),
            }
        }
    } else {
        println!("  ✗ 模型组成没解出来，跳过网格按钮这一路");
    }
    // 清单路径这一路（CLI/手工输入文件名走的是它）。
    for path in [
        "data/effect/effectmodel/w1351_model_plane_c007.mesh",
        "data/effect/effectmodel/test_jianzhen.mesh",
    ] {
        match app.mesh_geometry(path, None) {
            Ok((p, g)) => report_mesh(&p, &g),
            Err(e) => println!("  ✗ {path} → {e}"),
        }
    }

    // ---- UI 回包体检：把前端真正会收到的东西原样落盘 ----
    // 自测台以前喂的是编出来的漂亮数据，结果首屏一墙 hash 没验出来。
    // 这几个 JSON 就是真实回包，回放它们才算验到界面。
    println!("\nUI 回包体检（落盘给自测台回放）");
    let dir = root.join(".scratch/ui_check");
    let _ = std::fs::create_dir_all(&dir);
    if let Ok(s) = serde_json::to_string(&app.stats()) {
        let _ = std::fs::write(dir.join("stats.json"), s);
    }
    // 库状态浮层 + 「谁提到了它」也要真实回包，否则这两块在自测台里是瞎的。
    let rv = app.ref_view(40);
    if let Ok(s) = serde_json::to_string(&rv) {
        let _ = std::fs::write(dir.join("ref_health.json"), s);
    }
    if let Some(d) = rv.top_dangling.first() {
        let cb = app.cited_by(&d.name, 60);
        if let Ok(s) = serde_json::to_string(&serde_json::json!({ "key": d.name, "view": cb })) {
            let _ = std::fs::write(dir.join("cited_by.json"), s);
        }
    }
    // 按 gid 命名，自测台才能"点到哪条取哪条"，而不是只认这三条。
    let mut replay: Vec<serde_json::Value> = Vec::new();
    let mut dump = |tag: &str, card: &model::Card| {
        let gid = card.gid;
        if let Ok(v) = serde_json::to_value(card) {
            replay.push(v);
        }
        match inspector::inspect(gid) {
            Ok(r) => {
                let n_mesh = r
                    .mdl
                    .as_ref()
                    .map(|m| m.bodies.iter().filter(|b| b.mesh.hash.is_some()).count())
                    .unwrap_or(0);
                let n_pv = r
                    .previews
                    .as_ref()
                    .map(|p| p.items.iter().filter(|i| i.ok).count())
                    .unwrap_or(0);
                println!(
                    "  {tag} gid {gid} · {} · 成员 {} · 网格可预览 {n_mesh} · 出图 {n_pv} · 缺 {} · 还能看 {:?}",
                    r.what,
                    r.members.len(),
                    r.missing.len(),
                    r.can_do
                );
                if let Ok(s) = serde_json::to_string(&r) {
                    let _ = std::fs::write(dir.join(format!("inspect_{gid}.json")), s);
                }
                if let Some(d) = app.detail(gid) {
                    if let Ok(s) = serde_json::to_string(&d) {
                        let _ = std::fs::write(dir.join(format!("detail_{gid}.json")), s);
                    }
                }
            }
            Err(e) => println!("  ✗ {tag} gid {gid} inspect 失败：{e}"),
        }
    };
    for word in [
        "w1351_monster_xiyuqiezei",
        "w1351_nv_s_yifu_bingcha",
        "w1351_pets_bingcan_b2",
    ] {
        let page = app.page(&Filter {
            query: Some(word.into()),
            limit: Some(1),
            ..Default::default()
        });
        match page.items.first() {
            Some(c) => dump("有名字", c),
            None => println!("  ✗ {word}：搜不到（命中 {}）", page.total),
        }
    }
    // 未命名组也得有一条真实回包：它的详情页正是"什么都看不到"的那种。
    let unnamed = app.page(&Filter {
        named: Some(false),
        limit: Some(1),
        ..Default::default()
    });
    if let Some(c) = unnamed.items.first() {
        dump("未命名", c);
    }
    // 自测台靠这份清单把"有真实回包的条目"排到列表最前面。
    if let Ok(s) = serde_json::to_string(&replay) {
        let _ = std::fs::write(dir.join("replay.json"), s);
    }
    // 真实顶点缓冲：拿验收怪物的第一个网格，按前端收到的同一形态落盘。
    if let Ok(r) = mdl_view::mdl_compose_run("w1351_monster_xiyuqiezei") {
        for b in r.bodies.iter().filter(|b| b.mesh.hash.is_some()).take(1) {
            match app.mesh_geometry(&b.mesh.name, b.mesh.hash.as_deref()) {
                Ok(g) => {
                    let m: mesh_view::MeshData = g.into();
                    let f = dir.join("mesh_real.json");
                    if let Ok(s) = serde_json::to_string(&m) {
                        let _ = std::fs::write(&f, s);
                        println!(
                            "  真实网格 → {} · 顶点 {} · 面 {} · 法线 {} · base64 {}KB",
                            f.display(),
                            m.vertex_count,
                            m.face_count,
                            m.has_normals,
                            m.buffer.len() / 1024
                        );
                    }
                }
                Err(e) => println!("  ✗ 真实网格取数据失败：{e}"),
            }
        }
    }
    // 首屏到底长什么样：把默认列表前两屏原样落盘，顺手把标题念出来——
    // 一屏编号在这种输出里藏不住。
    for (tag, want, file) in [("有名字的", Some(true), "page_named.json"), ("未命名", Some(false), "page_unnamed.json")] {
        let page = app.page(&Filter {
            named: want,
            limit: Some(400),
            ..Default::default()
        });
        let head: Vec<String> = page.items.iter().take(4).map(|c| c.name.clone()).collect();
        let hexy = page
            .items
            .iter()
            .filter(|c| !c.named)
            .count();
        println!("  {tag}默认列表 {} 条 · 无名 {} 条 · 前 4 条 {:?}", page.total, hexy, head);
        if let Ok(s) = serde_json::to_string(&page) {
            let _ = std::fs::write(dir.join(file), s);
        }
    }
}

/// 一行网格体检：顶点/面/法线/UV/负载字节/耗时。
fn report_mesh(path: &str, g: &tlbb_core::preview::MeshGeometry) {
    let bytes = g.positions.len() * 12
        + g.normals.len() * 12
        + g.uvs.len() * 8
        + g.indices.len() * 2;
    println!(
        "  {} · 顶点 {} · 面 {} · 法线 {} · UV {} · 负载 {:.0}KB · 未解中间 {}B 尾部 {}B",
        path.rsplit('/').next().unwrap_or(path),
        g.vertex_count,
        g.face_count,
        if g.normals.is_empty() { "无(前端自算)" } else { "有" },
        if g.uvs.is_empty() { "无" } else { "有" },
        bytes as f64 * 4.0 / 3.0 / 1024.0,
        g.middle_bytes,
        g.trailing_bytes,
    );
}


