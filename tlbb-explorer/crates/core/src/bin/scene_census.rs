//! 全库 `.scene` 形态普查：把 `parse_scene` 的结果按 tag 分组统计，
//! 用**实测**判定是否存在「声明被低估」与「尾部字节」这两类样本。
//!
//! 只读、不写库；结果打到 stdout + 一个 txt。
//!
//!   cargo run --bin scene_census

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::catalog::Catalog;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::scene::parse_scene;

fn main() {
    let root = PathBuf::from("D:/TLGL");
    let db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let out = PathBuf::from("D:/TLGL/.scratch/scene_census.txt");

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
    eprintln!("{} paks, {} records", paks.len(), idx.len());

    let cat = Catalog::open_ro(&db).expect("open catalog");
    let mut cands: Vec<tlbb_core::catalog::Asset> = Vec::new();
    cands.extend(cat.by_type("scene", usize::MAX).expect("scene"));
    cands.extend(cat.by_type("binary", usize::MAX).expect("binary"));

    let mut lines: Vec<String> = Vec::new();
    let mut say = |s: String, lines: &mut Vec<String>| {
        println!("{s}");
        lines.push(s);
    };

    // 按 tag 汇总
    let mut by_tag: HashMap<u32, TagStat> = HashMap::new();
    let mut parse_err = 0usize;
    let mut decode_err = 0usize;
    let mut total = 0usize;

    for asset in &cands {
        if !asset.ext.eq_ignore_ascii_case(".scene") {
            continue;
        }
        total += 1;
        let Some(rec) = idx.get(&(asset.pak.clone(), asset.hash)) else { continue };
        if rec.offset as i64 != asset.offset {
            continue;
        }
        let Some(pak) = paks.get(&asset.pak) else { continue };
        let Ok(dec) = payload::decode(pak, rec) else {
            decode_err += 1;
            continue;
        };
        let raw = dec.bytes;
        let Ok(g) = parse_scene(&raw) else {
            parse_err += 1;
            continue;
        };
        let e = by_tag.entry(g.tag).or_insert_with(|| TagStat::new(g.tag, g.stride));
        e.n += 1;
        e.sizes.push(raw.len() as i64);
        e.declared.push(g.declared as i64);
        e.instances.push(g.instances.len() as i64);
        e.tails.push(g.tail_bytes as i64);
        if g.understated {
            e.understated += 1;
            let gap = g.instances.len() as i64 - g.declared as i64;
            if gap > e.best_gap.0 {
                e.best_gap = (gap, g.instances.len(), g.declared, raw.len());
            }
            if e.under_examples.len() < 8 {
                e.under_examples.push((
                    asset.path.clone().unwrap_or_default(),
                    g.declared,
                    g.instances.len(),
                ));
            }
        }
        if g.instances.len() < g.declared as usize {
            e.overstated += 1;
        }
        if g.tail_bytes > 0 {
            e.with_tail += 1;
            if g.tail_bytes > e.best_tail.0 {
                e.best_tail = (g.tail_bytes, g.instances.len(), g.declared, raw.len());
            }
            if e.tail_examples.len() < 8 {
                e.tail_examples.push((
                    asset.path.clone().unwrap_or_default(),
                    g.declared,
                    g.instances.len(),
                    g.tail_bytes,
                ));
            }
        }
        if g.tail_bytes == 0 && g.instances.len() >= 5 {
            e.clean_ge5 += 1;
            if e.clean_pick.size == 0 || raw.len() < e.clean_pick.size {
                e.clean_pick = Pick {
                    size: raw.len(),
                    n: g.instances.len(),
                    declared: g.declared,
                    path: asset.path.clone().unwrap_or_default(),
                };
            }
        }
        if e.name_sample.is_empty() {
            e.name_sample = g.instances.iter().take(2).map(|i| i.name.clone()).collect();
        }
    }

    say(format!("total .scene rows = {total}; decode_err = {decode_err}; parse_err = {parse_err}"), &mut lines);
    let mut keys: Vec<u32> = by_tag.keys().copied().collect();
    keys.sort();
    for k in keys {
        let e = &by_tag[&k];
        say(format!(
            "\n=== tag {} stride {} ===\n  files                 = {}\n  size min/med/max      = {} / {} / {}\n  declared min/med/max  = {} / {} / {}\n  instances min/med/max = {} / {} / {}\n  tail min/med/max      = {} / {} / {}\n  understated (n>decl)  = {}\n  overstated (n<decl)   = {}\n  tail_bytes>0          = {}\n  tail==0 && n>=5       = {}\n  best understated gap  = {:?}   (gap, n, declared, size)\n  best tail             = {:?}   (tail, n, declared, size)\n  clean pick            = size={} n={} decl={} {}\n  name sample           = {:?}",
            e.tag, e.stride, e.n,
            e.sizes.iter().min().unwrap(), med(&mut e.sizes.clone()), e.sizes.iter().max().unwrap(),
            e.declared.iter().min().unwrap(), med(&mut e.declared.clone()), e.declared.iter().max().unwrap(),
            e.instances.iter().min().unwrap(), med(&mut e.instances.clone()), e.instances.iter().max().unwrap(),
            e.tails.iter().min().unwrap(), med(&mut e.tails.clone()), e.tails.iter().max().unwrap(),
            e.understated, e.overstated, e.with_tail, e.clean_ge5,
            e.best_gap, e.best_tail,
            e.clean_pick.size, e.clean_pick.n, e.clean_pick.declared, e.clean_pick.path,
            e.name_sample
        ), &mut lines);
        say(format!("  >>> understated examples: {:?}", e.under_examples), &mut lines);
        say(format!("  >>> tail examples:        {:?}", e.tail_examples), &mut lines);
    }

    std::fs::write(&out, lines.join("\n")).ok();
    eprintln!("wrote {}", out.display());
}

fn med(v: &mut Vec<i64>) -> i64 {
    if v.is_empty() { return -1; }
    v.sort_unstable();
    v[v.len() / 2]
}

#[derive(Default)]
struct Pick {
    size: usize,
    n: usize,
    declared: u32,
    path: String,
}

struct TagStat {
    tag: u32,
    stride: usize,
    n: usize,
    sizes: Vec<i64>,
    declared: Vec<i64>,
    instances: Vec<i64>,
    tails: Vec<i64>,
    understated: usize,
    overstated: usize,
    with_tail: usize,
    clean_ge5: usize,
    best_gap: (i64, usize, u32, usize),
    best_tail: (usize, usize, u32, usize),
    clean_pick: Pick,
    name_sample: Vec<String>,
    under_examples: Vec<(String, u32, usize)>,
    tail_examples: Vec<(String, u32, usize, usize)>,
}

impl TagStat {
    fn new(tag: u32, stride: usize) -> Self {
        Self {
            tag,
            stride,
            n: 0,
            sizes: Vec::new(),
            declared: Vec::new(),
            instances: Vec::new(),
            tails: Vec::new(),
            understated: 0,
            overstated: 0,
            with_tail: 0,
            clean_ge5: 0,
            best_gap: (0, 0, 0, 0),
            best_tail: (0, 0, 0, 0),
            clean_pick: Pick::default(),
            name_sample: Vec::new(),
            under_examples: Vec::new(),
            tail_examples: Vec::new(),
        }
    }
}
