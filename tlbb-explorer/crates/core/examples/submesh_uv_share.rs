//! 「多段共用一张颜色图」是不是站得住：看共用基础层的那些子网格，UV 岛是否互不重叠。
//!
//! 起因（2026-10-27）：普查 1,200 份里 1,069 份「颜色贴图数 == 子网格段数」，剩下的不等；
//! 其中「颜色少于段数」的份，现在的画法是让基础层铺前几段——这是推断，界面只敢写「顺序未验证」。
//! 这里找一个能算的旁证：**图集共用**站得住的形状是各段 UV 落在不同格子上（互不重叠）；
//! 若两段 UV 大面积重叠，共用一张图就可疑（更像配错）。
//!
//! 只读：db、pak 全部只读打开，不落资源字节。
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --example submesh_uv_share -- --limit 300 --show 8
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jbcf;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{build_mask, parse_mesh, GRID};

fn tail(p: &str) -> String {
    p.rsplit(['/', '\\'])
        .next()
        .unwrap_or(p)
        .to_ascii_lowercase()
}

fn stem_of(p: &str) -> String {
    let t = tail(p);
    match t.rsplit_once('.') {
        Some((s, _)) => s.to_string(),
        None => t,
    }
}

struct Store {
    root: PathBuf,
    paks: HashMap<String, Pak>,
}

impl Store {
    fn bytes(&mut self, pak_name: &str, hash: u64) -> Option<Vec<u8>> {
        if !self.paks.contains_key(pak_name) {
            let p = Pak::open(self.root.join(format!("{pak_name}.pak"))).ok()?;
            self.paks.insert(pak_name.to_string(), p);
        }
        let p = self.paks.get(pak_name)?;
        let rec = p.records().find(|r| r.hash == hash && r.stored > 0)?;
        payload::decode(p, &rec).ok().map(|x| x.bytes)
    }
}

/// 一张 GRID×GRID 的覆盖图里，两块的交集占小块的比例。
fn overlap(a: &[u8], b: &[u8]) -> f32 {
    let mut both = 0usize;
    let mut nb = 0usize;
    for i in 0..a.len().min(b.len()) {
        let bb = b[i] != 0;
        if bb {
            nb += 1;
            if a[i] != 0 {
                both += 1;
            }
        }
    }
    if nb == 0 {
        return 0.0;
    }
    both as f32 / nb as f32
}

fn main() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    let mut limit = 300usize;
    let mut show = 8usize;
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--limit" => limit = args.next().unwrap_or_default().parse().unwrap_or(limit),
            "--show" => show = args.next().unwrap_or_default().parse().unwrap_or(show),
            other => eprintln!("未知参数 {other}"),
        }
    }

    let con = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("资源清单打不开");

    let mut mesh_by_stem: HashMap<String, (u64, String)> = HashMap::new();
    let mut mtl_rows: Vec<(u64, String, String)> = Vec::new();
    {
        let mut st = con
            .prepare("SELECT hash, coalesce(pak,''), coalesce(path,'') FROM resources WHERE name LIKE '%.mesh' AND coalesce(pak,'') <> ''")
            .unwrap();
        for row in st
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .unwrap()
            .flatten()
        {
            if let Ok(h) = u64::from_str_radix(&row.0, 16) {
                mesh_by_stem
                    .entry(stem_of(if row.2.is_empty() { &row.0 } else { &row.2 }))
                    .or_insert((h, row.1));
            }
        }
    }
    {
        let mut st = con
            .prepare("SELECT hash, coalesce(pak,''), coalesce(path,'') FROM resources WHERE name LIKE '%.mtl' AND coalesce(pak,'') <> '' ORDER BY coalesce(path,'')")
            .unwrap();
        for row in st
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .unwrap()
            .flatten()
        {
            if let Ok(h) = u64::from_str_radix(&row.0, 16) {
                mtl_rows.push((h, row.1, row.2));
            }
        }
    }

    let mut store = Store {
        root: root.clone(),
        paks: HashMap::new(),
    };

    let mut scanned = 0usize;
    let mut shared_models = 0usize;
    let mut disjoint = 0usize;
    let mut slight = 0usize;
    let mut heavy = 0usize;
    let mut heavy_dup = 0usize;
    let mut printed = 0usize;
    let mut worst: Vec<(f32, String)> = Vec::new();

    for (hash, pak, path) in mtl_rows {
        if scanned >= limit {
            break;
        }
        let name = if path.is_empty() {
            format!("{hash:016x}")
        } else {
            path.clone()
        };
        let key = stem_of(&name);
        let Some((mhash, mpak)) = mesh_by_stem.get(&key).cloned() else {
            continue;
        };
        let Some(mtl_raw) = store.bytes(&pak, hash) else {
            continue;
        };
        let Ok(j) = jbcf::parse(&mtl_raw) else {
            continue;
        };
        let Some(mesh_raw) = store.bytes(&mpak, mhash) else {
            continue;
        };
        let Ok(layout) = parse_mesh(&mesh_raw) else {
            continue;
        };
        scanned += 1;

        let low = |s: &str| s.to_ascii_lowercase();
        let mut colors = 0usize;
        for s in &j.strings {
            if jbcf::role(&s.text) == jbcf::Role::Texture
                && !low(&s.text).contains("_pbr")
                && !low(&s.text).contains("mask")
            {
                colors += 1;
            }
        }
        let counts = &layout.face_counts;
        let nsub = counts.len();
        if colors == 0 || colors >= nsub || nsub < 2 {
            continue;
        }
        // 基础层要铺的段数：与后端 plan_placements 同口径（额外层先占尾部段）。
        let overlays = colors - 1;
        let base_count = nsub - overlays.min(nsub.saturating_sub(1));
        if base_count < 2 {
            continue;
        }
        let uvs = &layout.geometry.uvs;
        if uvs.is_empty() {
            continue;
        }
        let idx = &layout.geometry.indices;
        // 每段一张覆盖图
        let mut masks: Vec<Vec<u8>> = Vec::new();
        let mut at = 0usize;
        for &c in counts.iter() {
            let (s, e) = (at * 3, (at + c as usize) * 3);
            if e > idx.len() {
                masks.clear();
                break;
            }
            let (m, _) = build_mask(uvs, &idx[s..e]);
            masks.push(m);
            at += c as usize;
        }
        if masks.len() != nsub {
            continue;
        }
        shared_models += 1;
        // 与第 0 段重叠最厉害的那一段
        let mut worst_ov = 0.0f32;
        for k in 1..base_count {
            worst_ov = worst_ov.max(overlap(&masks[0], &masks[k]));
        }
        // 「完全重叠」的进一步问：这几段是不是**几何重复层**（各自三角形的 UV 逐位相同）？
        // 是的话共用一张图就不是推断，而是必然（同一块面画两遍，客户端也是这么绑的）。
        let mut dup = false;
        if worst_ov >= 0.99 {
            let uv_of = |si: usize| -> Vec<[f32; 2]> {
                let start: usize = counts[..si].iter().map(|&x| x as usize).sum();
                let end = start + counts[si] as usize;
                idx[start * 3..end * 3]
                    .iter()
                    .filter_map(|&v| uvs.get(v as usize).copied())
                    .collect()
            };
            let mut sets: Vec<Vec<[f32; 2]>> = Vec::new();
            for k in 0..base_count {
                let mut v = uv_of(k);
                v.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
                sets.push(v);
            }
            dup = sets[1..].iter().all(|s| *s == sets[0]);
        }
        if worst_ov < 0.01 {
            disjoint += 1;
        } else if worst_ov < 0.25 {
            slight += 1;
        } else {
            heavy += 1;
            if dup {
                heavy_dup += 1;
            }
        }
        worst.push((
            worst_ov,
            format!("{} 段={nsub} 颜色={colors} 共用段≈{base_count}{}", tail(&name), if dup { " 重复层" } else { "" }),
        ));
        if worst_ov >= 0.25 && printed < show {
            println!(
                "重叠多：{} 段={nsub} 颜色={colors} 基础铺 {base_count} 段，最大重叠 {:.1}%",
                tail(&name),
                worst_ov * 100.0
            );
            printed += 1;
        }
    }

    worst.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    println!("—— 共用一张基础色的份，按重叠最狠排序（前 8）——");
    for (ov, tag) in worst.iter().take(8) {
        println!("  {:.1}%  {tag}", ov * 100.0);
    }
    println!("---");
    println!("解出「颜色少于段数」的份：{shared_models}/{scanned}");
    println!("  基础层与第 1 段起各段 UV **几乎不重叠**（<1%）：{disjoint}/{shared_models}");
    println!("  轻度重叠（1~25%）：{slight}");
    println!("  重叠 ≥25%：{heavy}（其中「几何重复层」UV 逐位相同 {heavy_dup}）");
    println!("  覆盖率网格 {GRID}×{GRID}");
}