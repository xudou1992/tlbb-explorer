//! uvfit — 离线 UV 试贴评分器（贴图恢复系统 v1 · 步骤③④的判别核心）。
//!
//! 输入：一个带 UV 的 .mesh + 按**特征先验**（非证据）筛出的匿名贴图池。
//! 输出：每个候选的「岛内外方差比」得分 + Top-N 合成图（UV 岛边叠在贴图上），
//!       给人工目检和覆盖表用。**得分是特征指标，不是归属结论**——归属只有
//!       人工确认（🟢）才算数，这里的一切都是 🟡。
//!
//! 只读纪律：db 只读、pak 只读、只写 --out 目录。
//!
//! 本体已抽进 lib（`preview::uvfit`），这里是薄壳：批量版
//! `bin/uvfit_batch.rs` 共用同一评分核心。CLI 参数、stdout 输出与
//! --emit-cache 的 JSON 结构保持与 lib 化之前逐字一致——它是现有
//! 3 个候选缓存的生产者，格式漂移会破坏工作台的 UI 契约。
//!
//! 用法：
//! ```text
//! uvfit --root D:/TLGL --db D:/TLGL/.scratch/resources.db \
//!       --mesh w1351_monster_xiyuqiezei_yifu_001.mesh --top 10 --out D:/TLGL/.scratch/uvfit_out
//! ```

use std::path::PathBuf;

use rusqlite::OpenFlags;
use tlbb_core::preview::uvfit::{
    build_mask, covered, decode_pool, mesh_hash, open_paks, query_pool, score_pool, GRID,
};
use tlbb_core::preview::{parse_geometry, png_bytes};

fn main() {
    let mut root = PathBuf::from("D:/TLGL");
    let mut db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let mut mesh = String::new();
    let mut out = PathBuf::from("D:/TLGL/.scratch/uvfit_out");
    let mut top = 10usize;
    let mut limit = usize::MAX;
    let mut emit_cache: Option<PathBuf> = None;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--root" => root = PathBuf::from(args.next().unwrap_or_default()),
            "--db" => db = PathBuf::from(args.next().unwrap_or_default()),
            "--mesh" => mesh = args.next().unwrap_or_default(),
            "--out" => out = PathBuf::from(args.next().unwrap_or_default()),
            "--top" => top = args.next().and_then(|v| v.parse().ok()).unwrap_or(10),
            "--limit" => limit = args.next().and_then(|v| v.parse().ok()).unwrap_or(usize::MAX),
            "--emit-cache" => emit_cache = Some(PathBuf::from(args.next().unwrap_or_default())),
            other => eprintln!("未知参数 {other}"),
        }
    }
    if mesh.is_empty() {
        eprintln!("用法：uvfit --root … --db … --mesh <name> [--top N] [--limit N] --out …");
        std::process::exit(2);
    }
    let t0 = std::time::Instant::now();
    let set = open_paks(&root);
    println!("打开 {} 个 pak，索引 {} 条", set.paks.len(), set.by_hash.len());

    let con = rusqlite::Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("db 打不开");
    let mesh_hash = mesh_hash(&con, &mesh).expect("网格找不到");
    let raw = set.fetch(mesh_hash).expect("网格字节取不到");
    let geo = parse_geometry(&raw).expect("网格几何解析失败");
    println!(
        "网格 {}：顶点 {} · 面 {} · UV {}",
        mesh,
        geo.vertex_count,
        geo.face_count,
        if geo.uvs.is_empty() { "无" } else { "有" }
    );
    if geo.uvs.is_empty() {
        std::process::exit(3);
    }

    // UV 栅格化：岛内 = 1。
    let (mask, tris) = build_mask(&geo.uvs, &geo.indices);
    let cov = covered(&mask);
    println!("UV 栅格化：{tris} 个三角形，覆盖 {}/{}
（{:.1}%）", cov, GRID * GRID, 100.0 * cov as f64 / (GRID * GRID) as f64);

    // 候选池：角色贴图先验（宽高 ≥512、RGBA32/BC3、mip ≥4）。先验只是筛选器，
    // 不是证据——证据在后面的指标里。解码后的 256² 亮度池留在内存，
    // 评分时逐张取用（与旧版「边解码边评」数值完全一致）。
    let pool_rows = query_pool(&con, limit);
    println!("候选池 {} 张（先验：≥512² RGBA32/BC3 mips≥4）", pool_rows.len());
    let pool = decode_pool(&pool_rows, &set.paks, &set.by_hash, &mut |done, total| {
        eprintln!("  已评 {} / {}", done, total);
    });

    let results = score_pool(&mask, &pool);
    println!(
        "评分完成 {} 张，用时 {:.1}s",
        results.len(),
        t0.elapsed().as_secs_f64()
    );

    std::fs::create_dir_all(&out).ok();
    // 合成图：前 top 名，UV 岛边画红线叠在贴图上。
    for (rank, cand) in results.iter().take(top).enumerate() {
        // 降采样亮度直接取自内存池（同一 f32 序列，PNG 逐位不变）。
        let Some(tex) = pool.iter().find(|p| p.hash == cand.hash) else {
            continue;
        };
        let img = overlay_edges(&tex.lum, &mask);
        let file = out.join(format!(
            "rank{:02}_score{:.0}_{}.png",
            rank + 1,
            cand.score * 100.0,
            cand.hash
        ));
        match png_bytes(GRID as u16, GRID as u16, &img, true) {
            Ok(png) => {
                std::fs::write(&file, png).ok();
                println!("  #{} {} → {}", rank + 1, cand.summary(), file.display());
            }
            Err(e) => eprintln!("  PNG 失败：{e}"),
        }
    }
    // 全量 JSON（给覆盖表/前端用）。
    let json = format!(
        "{{\"mesh\":\"{mesh}\",\"pool\":{},\"coverage\":{:.4},\"results\":[{}]}}\n",
        pool_rows.len(),
        cov as f64 / (GRID * GRID) as f64,
        results
            .iter()
            .map(|c| c.summary())
            .collect::<Vec<_>>()
            .join(",")
    );
    std::fs::write(out.join("uvfit_result.json"), json).ok();
    println!("结果 → {}", out.join("uvfit_result.json").display());

    // --emit-cache：给工作台用的候选缓存（前 top 名带 256² PNG data URL，
    // 供「套上看看」直接包到模型上）。放 .scratch/texture_candidates/<mesh>.json。
    if let Some(cache) = emit_cache {
        let mut items = String::new();
        for cand in results.iter().take(top) {
            // 缓存 PNG 用全分辨率原图（不是 256² 降采样）——工作台前端
            // 自己缩放，这里不给它二次压缩的图。
            let Some(bytes) = set.fetch(u64::from_str_radix(&cand.hash, 16).unwrap_or(0)) else {
                continue;
            };
            let png = match tlbb_core::jmt1::decode(&bytes)
                .map(|t| png_bytes(t.width, t.height, &t.rgba, true))
            {
                Ok(Ok(p)) => b64(&p),
                _ => continue,
            };
            items.push_str(&format!(
                "{{{},\"png\":\"data:image/png;base64,{png}\"}},",
                cand.summary().trim_start_matches('{').trim_end_matches('}')
            ));
        }
        let cache_json = format!(
            "{{\"mesh\":\"{mesh}\",\"pool\":{},\"coverage\":{:.4},\"candidates\":[{}]}}\n",
            pool_rows.len(),
            cov as f64 / (GRID * GRID) as f64,
            items.trim_end_matches(',')
        );
        if let Some(dir) = cache.parent() {
            std::fs::create_dir_all(dir).ok();
        }
        std::fs::write(&cache, cache_json).ok();
        println!("候选缓存 → {}", cache.display());
    }
}

/// 手写 base64（离线环境不加依赖）。
fn b64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for c in data.chunks(3) {
        let b = [c[0], *c.get(1).unwrap_or(&0), *c.get(2).unwrap_or(&0)];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if c.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if c.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    out
}

/// UV 岛边缘画红线叠在贴图上（目检用）。
fn overlay_edges(lum_unused: &[f32], mask: &[u8]) -> Vec<u8> {
    let _ = lum_unused;
    let mut img = vec![0u8; GRID * GRID * 4];
    for y in 0..GRID {
        for x in 0..GRID {
            let i = y * GRID + x;
            let (r, g, b) = (lum_unused[i] as u8, lum_unused[i] as u8, lum_unused[i] as u8);
            img[i * 4] = r;
            img[i * 4 + 1] = g;
            img[i * 4 + 2] = b;
            img[i * 4 + 3] = 255;
        }
    }
    let edge = |x: i32, y: i32| {
        if x <= 0 || y <= 0 || x >= GRID as i32 - 1 || y >= GRID as i32 - 1 {
            return false;
        }
        let c = mask[y as usize * GRID + x as usize] == 1;
        let n = |dx: i32, dy: i32| mask[(y + dy) as usize * GRID + (x + dx) as usize] == 1;
        c && !(n(1, 0) && n(-1, 0) && n(0, 1) && n(0, -1))
    };
    for y in 0..GRID as i32 {
        for x in 0..GRID as i32 {
            if edge(x, y) {
                let i = (y as usize * GRID + x as usize) * 4;
                img[i] = 255;
                img[i + 1] = 0;
                img[i + 2] = 0;
            }
        }
    }
    img
}
