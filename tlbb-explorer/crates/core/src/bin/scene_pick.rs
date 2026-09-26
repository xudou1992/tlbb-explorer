//! 抽取三个 `.scene` 样本并**原样导出**字节，供 `preview::scene` 的 `真实样本` 测试。
//!
//! 严格判据（用户给定）：
//!   A. `grid_749.scene`             tag=749, instances>=5, tail_bytes==0, 4KB<=size<=200KB
//!   B. `grid_753_overstated.scene`  tag=753, instances.len() > u32@0
//!   C. `grid_753_with_tail.scene`   tag=753, tail_bytes > 0（尽量大）
//!
//! 用户还给了 fallback：若 B/C 找不到严格个例，则「只要 tag 对、instances>=5」，
//! 并在报告里如实说明。本工具**先按严格判据找**，找不到就记明原因再落 fallback。
//!
//! 只读；产物先落 %TEMP%，由调用方复制到 tests/scene_samples。
//!
//!   cargo run --bin scene_pick

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::catalog::Catalog;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::scene::parse_scene;

#[derive(Clone)]
struct Cand {
    hash: u64,
    path: String,
    pak: String,
    offset: i64,
    rtype: String,
    subtype: String,
    props: String,
    size: usize,
    declared: u32,
    tag: u32,
    stride: usize,
    n: usize,
    tail: usize,
    first_names: Vec<String>,
    first_pos: Vec<[f32; 3]>,
}

fn main() {
    let root = PathBuf::from("D:/TLGL");
    let db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let tmp = std::env::temp_dir().join("tlbb_scene_samples");
    std::fs::create_dir_all(&tmp).expect("mkdir temp");

    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut idx: HashMap<(String, u64), tlbb_core::Record> = HashMap::new();
    let mut files: Vec<_> = std::fs::read_dir(&root)
        .expect("read root")
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "pak").unwrap_or(false))
        .collect();
    files.sort();
    for path in &files {
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        let pak = Pak::open(path).expect("open pak");
        for rec in pak.records() {
            idx.insert((stem.clone(), rec.hash), rec);
        }
        paks.insert(stem, pak);
    }
    let cat = Catalog::open_ro(&db).expect("open catalog");
    let mut rows: Vec<tlbb_core::catalog::Asset> = Vec::new();
    rows.extend(cat.by_type("scene", usize::MAX).unwrap());
    rows.extend(cat.by_type("binary", usize::MAX).unwrap());

    let mut all: Vec<Cand> = Vec::new();
    for asset in &rows {
        if !asset.ext.eq_ignore_ascii_case(".scene") {
            continue;
        }
        let Some(rec) = idx.get(&(asset.pak.clone(), asset.hash)) else { continue };
        if rec.offset as i64 != asset.offset {
            continue;
        }
        let Some(pak) = paks.get(&asset.pak) else { continue };
        let Ok(dec) = payload::decode(pak, rec) else { continue };
        let raw = dec.bytes;
        let Ok(g) = parse_scene(&raw) else { continue };
        all.push(Cand {
            hash: asset.hash,
            path: asset.path.clone().unwrap_or_default(),
            pak: asset.pak.clone(),
            offset: asset.offset,
            rtype: asset.rtype.clone(),
            subtype: asset.subtype.clone(),
            props: asset.props.clone(),
            size: raw.len(),
            declared: g.declared,
            tag: g.tag,
            stride: g.stride,
            n: g.instances.len(),
            tail: g.tail_bytes,
            first_names: g.instances.iter().take(3).map(|i| i.name.clone()).collect(),
            first_pos: g.instances.iter().take(3).map(|i| i.position).collect(),
        });
    }
    eprintln!("decoded+parsed {} .scene rows", all.len());

    // ---------- A: 749, n>=5, tail==0, size 4K..200K ----------
    let a_strict: Vec<&Cand> = all
        .iter()
        .filter(|c| c.tag == 749 && c.n >= 5 && c.tail == 0 && (4096..=200_000).contains(&c.size))
        .collect();
    // 取「大小适中」：最接近 20KB 的那个，保证既有体量又不至于太大
    let a = a_strict
        .iter()
        .min_by_key(|c| (c.size as i64 - 20_000).abs())
        .copied();

    // ---------- B: 753, n > declared ----------
    let b_strict: Vec<&Cand> = all
        .iter()
        .filter(|c| c.tag == 753 && (c.n as i64) > (c.declared as i64))
        .collect();
    let b = b_strict
        .iter()
        .max_by_key(|c| (c.n as i64 - c.declared as i64, c.n))
        .copied();
    // fallback：tag 753 且 n>=5
    let b_fb: Vec<&Cand> = all.iter().filter(|c| c.tag == 753 && c.n >= 5).collect();
    let b_fb_pick = b_fb.iter().min_by_key(|c| (c.size as i64 - 20_000).abs()).copied();
    // ---------- C: 753, tail > 0 ----------
    let c_strict: Vec<&Cand> = all.iter().filter(|c| c.tag == 753 && c.tail > 0).collect();
    let c = c_strict.iter().max_by_key(|x| x.tail).copied();
    // 优先：尾部 >= 300 字节（满足「至少几百字节」可验证），且体积适中（4K..200K），
    // 在此约束下取 n 最大的——n 大才像一份真清单，而不是「刚开个头就走不动」。
    let c_pref: Vec<&&Cand> = c_strict
        .iter()
        .filter(|x| x.tail >= 300 && (4096..=200_000).contains(&x.size))
        .collect();
    let c_pref_pick = c_pref.iter().max_by_key(|x| x.n).copied().copied();
    let c_fb = all.iter().filter(|c| c.tag == 753 && c.n >= 5).min_by_key(|c| (c.size as i64 - 20_000).abs());

    let mut log = Vec::new();
    let mut say = |s: String, log: &mut Vec<String>| {
        println!("{s}");
        log.push(s);
    };

    say(format!("decoded+parsed = {}", all.len()), &mut log);
    say(format!("A strict (749,n>=5,tail==0,4K..200K) hits = {}", a_strict.len()), &mut log);
    say(format!("B strict (753, n > u32@0)              hits = {}", b_strict.len()), &mut log);
    say(format!("C strict (753, tail>0)                 hits = {}", c_strict.len()), &mut log);
    say(format!("B fallback pool (753, n>=5)            hits = {}", b_fb.len()), &mut log);

    let plan: [(&str, Option<&Cand>, &str); 3] = [
        ("grid_749.scene", a, "strict"),
        (
            "grid_753_overstated.scene",
            b.or(b_fb_pick),
            if b.is_some() { "strict" } else { "fallback: 753 无 understated 个例" },
        ),
        (
            "grid_753_with_tail.scene",
            c_pref_pick.or(c).or(c_fb),
            if c.is_some() { "strict(tail>0)" } else { "fallback" },
        ),
    ];

    for (name, pick, how) in plan {
        match pick {
            None => say(format!("\n{name}: NOT FOUND"), &mut log),
            Some(c) => {
                let expected_understated = c.n as u64 > c.declared as u64;
                let rec = idx.get(&(c.pak.clone(), c.hash)).unwrap();
                let pak = paks.get(&c.pak).unwrap();
                let bytes = payload::decode(pak, rec).expect("re-decode").bytes;
                // 落盘前再 parse 一次，保证「写出去的字节」就是被校验的字节
                let g = parse_scene(&bytes).expect("re-parse");
                assert_eq!(g.instances.len(), c.n);
                let path = tmp.join(name);
                std::fs::write(&path, &bytes).expect("write");
                say(format!(
                    "\n{name}   [{how}]\n  path        = {}\n  pak/off     = {} @ {}\n  hash        = {:016x}\n  rtype/sub   = {} / {}   props={}\n  size        = {} bytes\n  tag         = {}   stride = {}\n  declared    = {}   instances = {}   understated = {}\n  tail_bytes  = {}   has_tail = {}\n  first3 name = {:?}\n  first3 pos  = {:?}\n  wrote       = {}",
                    c.path, c.pak, c.offset, c.hash, c.rtype, c.subtype, c.props,
                    bytes.len(), g.tag, g.stride, g.declared, g.instances.len(),
                    expected_understated, g.tail_bytes, g.has_tail,
                    c.first_names, c.first_pos, path.display()
                ), &mut log);
                say(format!("  file size on disk = {} bytes", std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0)), &mut log);
            }
        }
    }

    std::fs::write("D:/TLGL/.scratch/scene_pick.txt", log.join("\n")).ok();
    eprintln!("temp dir = {}", tmp.display());
}
