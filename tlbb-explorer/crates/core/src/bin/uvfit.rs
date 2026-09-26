//! uvfit — 离线 UV 试贴评分器（贴图恢复系统 v1 · 步骤③④的判别核心）。
//!
//! 输入：一个带 UV 的 .mesh + 按**特征先验**（非证据）筛出的匿名贴图池。
//! 输出：每个候选的「岛内外方差比」得分 + Top-N 合成图（UV 岛边叠在贴图上），
//!       给人工目检和覆盖表用。**得分是特征指标，不是归属结论**——归属只有
//!       人工确认（🟢）才算数，这里的一切都是 🟡。
//!
//! 只读纪律：db 只读、pak 只读、只写 --out 目录。
//!
//! 用法：
//! ```text
//! uvfit --root D:/TLGL --db D:/TLGL/.scratch/resources.db \
//!       --mesh w1351_monster_xiyuqiezei_yifu_001.mesh --top 10 --out D:/TLGL/.scratch/uvfit_out
//! ```

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use rusqlite::OpenFlags;
use tlbb_core::jpak::{Pak, Record};
use tlbb_core::payload;
use tlbb_core::preview::{parse_geometry, png_bytes};

const GRID: usize = 256;

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
    let (paks, by_hash) = open_paks(&root);
    println!("打开 {} 个 pak，索引 {} 条", paks.len(), by_hash.len());

    let con = rusqlite::Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("db 打不开");
    let mesh_hash: u64 = con
        .query_row(
            "select hash from resources where lower(path) like '%/' || lower(?1) limit 1",
            [&mesh],
            |r| {
                let s: String = r.get(0)?;
                Ok(u64::from_str_radix(&s, 16).unwrap_or(0))
            },
        )
        .expect("网格找不到");
    let raw = fetch(&paks, &by_hash, mesh_hash).expect("网格字节取不到");
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

    // UV 栅格化：岛内 = 1。三角形用包围盒 + 重心坐标填充。
    let mut mask = vec![0u8; GRID * GRID];
    let mut tris = 0usize;
    for t in geo.indices.chunks_exact(3) {
        let (ia, ib, ic) = (t[0] as usize, t[1] as usize, t[2] as usize);
        if ia >= geo.uvs.len() || ib >= geo.uvs.len() || ic >= geo.uvs.len() {
            continue;
        }
        let (a, b, c) = (geo.uvs[ia], geo.uvs[ib], geo.uvs[ic]);
        rasterize(&mut mask, a, b, c);
        tris += 1;
    }
    let cov = mask.iter().filter(|&&m| m == 1).count();
    println!("UV 栅格化：{tris} 个三角形，覆盖 {}/{}
（{:.1}%）", cov, GRID * GRID, 100.0 * cov as f64 / (GRID * GRID) as f64);

    // 候选池：角色贴图先验（宽高 ≥512、RGBA32/BC3、mip ≥4）。先验只是筛选器，
    // 不是证据——证据在后面的指标里。
    let pool: Vec<(u64, u16, u16, String, u32)> = {
        let mut stmt = con
            .prepare(
                "select hash, width, height, codec, mips from resources
                 where type='texture' and path is null and width>=512 and height>=512
                   and codec in ('RGBA32','BC3') and mips>=4 order by original desc",
            )
            .unwrap();
        let rows = stmt
            .query_map([], |r| {
                let h: String = r.get(0)?;
                Ok((
                    u64::from_str_radix(&h, 16).unwrap_or(0),
                    r.get::<_, i64>(1)? as u16,
                    r.get::<_, i64>(2)? as u16,
                    r.get::<_, String>(3)?,
                    r.get::<_, i64>(4)? as u32,
                ))
            })
            .unwrap();
        rows.flatten().take(limit).collect()
    };
    println!("候选池 {} 张（先验：≥512² RGBA32/BC3 mips≥4）", pool.len());

    let mut results: Vec<Cand> = Vec::new();
    for (i, (hash, w, h, codec, mips)) in pool.iter().enumerate() {
        let Some(bytes) = fetch(&paks, &by_hash, *hash) else { continue };
        let Ok(tex) = tlbb_core::jmt1::decode(&bytes) else { continue };
        if tex.rgba.len() < tex.width as usize * tex.height as usize * 4 {
            continue;
        }
        let small = downsample(&tex.rgba, tex.width as usize, tex.height as usize);
        let (ivar, ovar) = island_variance(&small, &mask);
        if ivar <= 0.0 {
            continue;
        }
        results.push(Cand {
            hash: format!("{hash:016x}"),
            w: *w,
            h: *h,
            codec: codec.clone(),
            mips: *mips,
            inside_var: ivar,
            outside_var: ovar,
            score: ivar / (ovar + 4.0),
        });
        if (i + 1) % 200 == 0 {
            eprintln!("  已评 {} / {}", i + 1, pool.len());
        }
    }
    results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap());
    println!(
        "评分完成 {} 张，用时 {:.1}s",
        results.len(),
        t0.elapsed().as_secs_f64()
    );

    std::fs::create_dir_all(&out).ok();
    // 合成图：前 top 名，UV 岛边画红线叠在贴图上。
    for (rank, cand) in results.iter().take(top).enumerate() {
        let Some(bytes) =
            fetch(&paks, &by_hash, u64::from_str_radix(&cand.hash, 16).unwrap_or(0))
        else {
            continue;
        };
        let Ok(tex) = tlbb_core::jmt1::decode(&bytes) else { continue };
        let small = downsample(&tex.rgba, tex.width as usize, tex.height as usize);
        let img = overlay_edges(&small, &mask);
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
        pool.len(),
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
            let Some(bytes) =
                fetch(&paks, &by_hash, u64::from_str_radix(&cand.hash, 16).unwrap_or(0))
            else {
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
            pool.len(),
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

struct Cand {
    hash: String,
    w: u16,
    h: u16,
    codec: String,
    mips: u32,
    inside_var: f64,
    outside_var: f64,
    score: f64,
}

impl Cand {
    fn summary(&self) -> String {
        format!(
            "{{\"hash\":\"{}\",\"w\":{},\"h\":{},\"codec\":\"{}\",\"mips\":{},\"insideVar\":{:.1},\"outsideVar\":{:.1},\"score\":{:.3}}}",
            self.hash, self.w, self.h, self.codec, self.mips, self.inside_var, self.outside_var, self.score
        )
    }
}

fn open_paks(root: &Path) -> (HashMap<String, Pak>, HashMap<u64, (String, Record)>) {
    let mut paks = HashMap::new();
    let mut by_hash: HashMap<u64, (String, Record)> = HashMap::new();
    let Ok(rd) = std::fs::read_dir(root) else {
        return (paks, by_hash);
    };
    for e in rd.flatten() {
        let p = e.path();
        let is_pak = p
            .extension()
            .map(|x| x.eq_ignore_ascii_case("pak"))
            .unwrap_or(false);
        if !is_pak {
            continue;
        }
        let name = p.file_stem().unwrap_or_default().to_string_lossy().into_owned();
        let Ok(pak) = Pak::open(&p) else { continue };
        for rec in pak.records() {
            if rec.original > 0 {
                by_hash.entry(rec.hash).or_insert((name.clone(), rec));
            }
        }
        paks.insert(name, pak);
    }
    (paks, by_hash)
}

fn fetch(
    paks: &HashMap<String, Pak>,
    by_hash: &HashMap<u64, (String, Record)>,
    hash: u64,
) -> Option<Vec<u8>> {
    let (name, rec) = by_hash.get(&hash)?;
    let pak = paks.get(name)?;
    payload::decode(pak, rec).ok().map(|d| d.bytes)
}

fn rasterize(mask: &mut [u8], a: [f32; 2], b: [f32; 2], c: [f32; 2]) {
    let g = GRID as f32;
    let (ax, ay) = (a[0] * g, a[1] * g);
    let (bx, by) = (b[0] * g, b[1] * g);
    let (cx, cy) = (c[0] * g, c[1] * g);
    let minx = ax.min(bx).min(cx).floor().max(0.0) as i32;
    let maxx = ax.max(bx).max(cx).ceil().min(g - 1.0) as i32;
    let miny = ay.min(by).min(cy).floor().max(0.0) as i32;
    let maxy = ay.max(by).max(cy).ceil().min(g - 1.0) as i32;
    let det = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax);
    if det.abs() < 1e-9 {
        return;
    }
    for y in miny..=maxy {
        for x in minx..=maxx {
            let (px, py) = (x as f32 + 0.5, y as f32 + 0.5);
            let w1 = ((px - ax) * (cy - ay) - (py - ay) * (cx - ax)) / det;
            let w2 = ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) / det;
            let w0 = 1.0 - w1 - w2;
            if w0 >= -0.001 && w1 >= -0.001 && w2 >= -0.001 {
                mask[(y * GRID as i32 + x) as usize] = 1;
            }
        }
    }
}

/// 盒式降采样到 GRID×GRID 的亮度（0..255）。
fn downsample(rgba: &[u8], w: usize, h: usize) -> Vec<f32> {
    let mut out = vec![0f32; GRID * GRID];
    for gy in 0..GRID {
        let y0 = gy * h / GRID;
        let y1 = ((gy + 1) * h / GRID).max(y0 + 1);
        for gx in 0..GRID {
            let x0 = gx * w / GRID;
            let x1 = ((gx + 1) * w / GRID).max(x0 + 1);
            let mut acc = 0f64;
            let mut n = 0u64;
            let step = ((x1 - x0) * (y1 - y0) / 16).max(1);
            let mut k = 0usize;
            for y in y0..y1 {
                for x in x0..x1 {
                    if k % step == 0 {
                        let o = (y * w + x) * 4;
                        if o + 2 < rgba.len() {
                            acc += 0.299 * rgba[o] as f64 + 0.587 * rgba[o + 1] as f64
                                + 0.114 * rgba[o + 2] as f64;
                            n += 1;
                        }
                    }
                    k += 1;
                }
            }
            out[gy * GRID + gx] = if n > 0 { (acc / n as f64) as f32 } else { 0.0 };
        }
    }
    out
}

/// 岛内 / 岛外亮度方差。真被画过的贴图：岛内是绘画细节（高方差），
/// 岛外是溢色垫底（低方差）；错贴图的岛外多半还是别人的绘画内容。
fn island_variance(lum: &[f32], mask: &[u8]) -> (f64, f64) {
    let mut si = (0f64, 0f64, 0u64);
    let mut so = (0f64, 0f64, 0u64);
    for (i, &m) in mask.iter().enumerate() {
        let v = lum[i] as f64;
        if m == 1 {
            si.0 += v;
            si.1 += v * v;
            si.2 += 1;
        } else {
            so.0 += v;
            so.1 += v * v;
            so.2 += 1;
        }
    }
    let var = |s: (f64, f64, u64)| {
        if s.2 < 2 {
            0.0
        } else {
            let mean = s.0 / s.2 as f64;
            (s.1 / s.2 as f64) - mean * mean
        }
    };
    (var(si), var(so))
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
