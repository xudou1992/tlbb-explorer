//! `uvmap` —— 把一只网格的 **UV 岛分布**画成 PNG（只读）。
//!
//! 为什么要：贴图候选的分数是「岛内方差 / (岛外方差 + 4)」，而「岛外没像素」这种
//! 情况光看数字说不清。这张图把已经算过的 mask 直接给人看——白的是有 UV 覆盖的格子，
//! 暗的是岛外。它不参与任何评分，也不新造任何判断。
//!
//! ```text
//! uvmap --root=D:/TLGL/.scratch/out --db=D:/TLGL/.scratch/resources.db \
//!       --name=w1351_boss_mengmei_yifu_001 --name=chuansong001
//! ```

use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::preview::{
    build_mask, covered, mask_png, mesh_hash, open_paks, parse_geometry, GRID,
};

fn arg(argv: &[String], name: &str) -> Option<String> {
    let want = format!("--{name}=");
    argv.iter()
        .skip(1)
        .find_map(|a| a.strip_prefix(&want))
        .map(|s| s.trim_matches('"').to_string())
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let root = PathBuf::from(arg(&argv, "root").unwrap_or_else(|| ".scratch/out".into()));
    let db = PathBuf::from(
        arg(&argv, "db").unwrap_or_else(|| ".scratch/resources.db".into()),
    );
    let out = PathBuf::from(arg(&argv, "out").unwrap_or_else(|| ".scratch/uvmap".into()));
    let names: Vec<String> = argv
        .iter()
        .skip(1)
        .filter_map(|a| a.strip_prefix("--name="))
        .map(|s| s.trim_matches('"').to_string())
        .collect();
    if names.is_empty() {
        eprintln!("用法：uvmap --root=<pak 目录> --db=<清单> --name=<网格名> [--name=...]");
        return;
    }
    std::fs::create_dir_all(&out).ok();
    let con = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("资源清单打不开");
    let set = open_paks(&root);
    for n in names {
        let file = if n.ends_with(".mesh") { n.clone() } else { format!("{n}.mesh") };
        let stem = file.trim_end_matches(".mesh").to_string();
        let Some(hash) = mesh_hash(&con, &file) else {
            println!("{stem}: 清单里找不到这份网格");
            continue;
        };
        let Some(bytes) = set.fetch(hash) else {
            println!("{stem}: pak 里取不到字节");
            continue;
        };
        let Ok(geo) = parse_geometry(&bytes) else {
            println!("{stem}: 几何解析失败");
            continue;
        };
        if geo.uvs.is_empty() {
            println!("{stem}: 这份网格没有 UV（所以候选榜本来就不该有它）");
            continue;
        }
        let (mask, tris) = build_mask(&geo.uvs, &geo.indices);
        let cov = covered(&mask) as f64 / (GRID * GRID) as f64;
        match mask_png(&mask) {
            Ok(png) => {
                let p = out.join(format!("{stem}.png"));
                match std::fs::write(&p, &png) {
                    Ok(_) => println!(
                        "{stem}: 覆盖率 {:.3} · {} 面 · 岛内格子 {} → {}",
                        cov,
                        tris,
                        covered(&mask),
                        p.display()
                    ),
                    Err(e) => println!("{stem}: 写文件失败 {e}"),
                }
            }
            Err(e) => println!("{stem}: 画图失败 {e}"),
        }
    }
}
