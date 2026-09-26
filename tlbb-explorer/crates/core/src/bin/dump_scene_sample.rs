//! 从真实 `resources.db` 里挑出符合形态要求的 `.scene` 样本并**原样导出**字节。
//!
//! 这是一个**一次性的取证工具**：不做修改、不写库，只把 pak 里的原始 payload
//! 解出来落盘，供 `crates/core/src/preview/scene.rs` 的 `真实样本` 测试当固定输入。
//!
//! 目标三个形态：
//! 1. `grid_749.scene`            —— tag=749、≥5 条记录、tail_bytes == 0
//! 2. `grid_753_overstated.scene` —— tag=753、实际条数 > u32@0（声明被低估）
//! 3. `grid_753_with_tail.scene`  —— tag=753、stride 走完后仍有尾部字节
//!
//! 用法（先落 %TEMP%，再复制到 tests/scene_samples，避免工作区大文件删除保护）：
//!   cargo run --bin dump_scene_sample
//!
//! 输出同时在 stdout 打印一张数值表。

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::catalog::Catalog;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::scene::parse_scene;

/// 候选清单表：三个目标形态各一行。
#[derive(Clone)]
struct Hit {
    hash: u64,
    path: String,
    pak: String,
    offset: i64,
    stored: i64,
    original: i64,
    subtype: String,
    props: String,
    declared: u32,
    tag: u32,
    stride: usize,
    n: usize,
    tail: usize,
    size: usize,
    first_names: Vec<String>,
    first_pos: Vec<[f32; 3]>,
}

fn main() {
    let root = PathBuf::from("D:/TLGL");
    let db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let out_dir = std::env::temp_dir().join("tlbb_scene_samples");
    std::fs::create_dir_all(&out_dir).expect("create temp dir");

    // ---- 打开所有 pak（清单表里的 pak 名就是 pak 文件 stem） ----
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
    eprintln!("{} paks, {} indexed records", paks.len(), idx.len());

    let cat = Catalog::open_ro(&db).expect("open catalog");

    // 三组候选：type='scene'（subtype=grid753）与 type='binary'（props.f[1] 里带真实 tag）。
    let mut cands: Vec<tlbb_core::catalog::Asset> = Vec::new();
    cands.extend(cat.by_type("scene", usize::MAX).expect("scene rows"));
    cands.extend(cat.by_type("binary", usize::MAX).expect("binary rows"));

    let mut best: [Option<Hit>; 3] = [None, None, None];
    let mut tried = 0usize;
    let mut decoded = 0usize;

    for asset in &cands {
        if !asset.ext.eq_ignore_ascii_case(".scene") {
            continue;
        }
        // props 里给出的头部 u32 三元组（binary 行专有）——只当提示，不当结论。
        let declared_hint = parse_f(asset).map(|f| f[0]);
        let tag_hint = parse_f(asset).map(|f| f[1]);

        tried += 1;
        let Some(rec) = idx.get(&(asset.pak.clone(), asset.hash)) else {
            continue;
        };
        if rec.offset as i64 != asset.offset {
            continue;
        }
        let Some(pak) = paks.get(&asset.pak) else {
            continue;
        };
        let Ok(dec) = payload::decode(pak, rec) else {
            continue;
        };
        decoded += 1;
        let raw = dec.bytes;
        let Ok(g) = parse_scene(&raw) else {
            continue;
        };

        let hit = Hit {
            hash: asset.hash,
            path: asset.path.clone().unwrap_or_default(),
            pak: asset.pak.clone(),
            offset: asset.offset,
            stored: asset.stored,
            original: asset.original,
            subtype: asset.subtype.clone(),
            props: asset.props.clone(),
            declared: g.declared,
            tag: g.tag,
            stride: g.stride,
            n: g.instances.len(),
            tail: g.tail_bytes,
            size: raw.len(),
            first_names: g.instances.iter().take(3).map(|i| i.name.clone()).collect(),
            first_pos: g.instances.iter().take(3).map(|i| i.position).collect(),
        };
        let _ = (declared_hint, tag_hint);

        // ---- 判据 ----
        if g.tag == 749 && g.instances.len() >= 5 && g.tail_bytes == 0 {
            let keep = match &best[0] {
                // 取「大小适中的」：优先落在 4KB..200KB，且条数更多者
                Some(b) => b.n < hit.n && hit.size >= 4096 && hit.size <= 200_000,
                None => true,
            };
            if keep {
                best[0] = Some(hit.clone());
            }
        }
        if g.tag == 753 && g.understated && g.instances.len() >= 5 {
            // 挑「差距明显」的：先按 (实际-声明) 排，再按条数
            let gap = hit.n as i64 - hit.declared as i64;
            let keep = match &best[1] {
                Some(b) => {
                    let bgap = b.n as i64 - b.declared as i64;
                    gap > bgap || (gap == bgap && hit.n > b.n)
                }
                None => true,
            };
            if keep {
                best[1] = Some(hit.clone());
            }
        }
        if g.tag == 753 && g.tail_bytes > 0 {
            let keep = match &best[2] {
                Some(b) => hit.tail > b.tail,
                None => true,
            };
            if keep {
                best[2] = Some(hit.clone());
            }
        }
    }

    eprintln!("tried={tried} decoded_ok={decoded}");

    let names = ["grid_749.scene", "grid_753_overstated.scene", "grid_753_with_tail.scene"];
    println!("=== scene sample dump ===");
    for (i, name) in names.iter().enumerate() {
        match &best[i] {
            None => println!("{name}: NOT FOUND"),
            Some(h) => {
                let path = out_dir.join(name);
                let raw = read_back(&paks, &idx, h);
                match raw {
                    Ok(bytes) => {
                        std::fs::write(&path, &bytes).expect("write sample");
                        println!(
                            "{name}\n  src      = {} ({}, off={}, stored={}, original={})\n  hash     = {:016x}\n  subtype  = {} props={}\n  bytes    = {}\n  declared = {} tag = {} stride = {}\n  instances= {}\n  tail     = {}\n  understated = {}\n  first3   = {:?}\n  pos3     = {:?}\n  wrote    = {}",
                            h.path, h.pak, h.offset, h.stored, h.original,
                            h.hash, h.subtype, h.props,
                            bytes.len(), h.declared, h.tag, h.stride,
                            h.n, h.tail, (h.n as u64) > (h.declared as u64),
                            h.first_names, h.first_pos,
                            path.display()
                        );
                    }
                    Err(e) => println!("{name}: re-read failed: {e}"),
                }
            }
        }
    }
    println!("\ntemp dir = {}", out_dir.display());
}

/// 从 pak 里把同一个 hash 的字节再解一次（保持「写出的字节 == 校验用的字节」）。
fn read_back(
    paks: &HashMap<String, Pak>,
    idx: &HashMap<(String, u64), tlbb_core::Record>,
    h: &Hit,
) -> Result<Vec<u8>, String> {
    let rec = idx.get(&(h.pak.clone(), h.hash)).ok_or("not in index")?;
    let pak = paks.get(&h.pak).ok_or("pak missing")?;
    payload::decode(pak, rec).map(|d| d.bytes).map_err(|e| e.to_string())
}

/// `props` 形如 `{"f": [21, 749, 0, 1059481190]}`；取 `f` 数组。
fn parse_f(a: &tlbb_core::catalog::Asset) -> Option<[u32; 4]> {
    let s = a.props.trim();
    if !s.starts_with('{') {
        return None;
    }
    let start = s.find('[')?;
    let end = s.find(']')?;
    let inner = &s[start + 1..end];
    let mut out = [0u32; 4];
    let mut n = 0;
    for part in inner.split(',') {
        if n >= 4 {
            break;
        }
        out[n] = part.trim().parse().ok()?;
        n += 1;
    }
    if n == 4 {
        Some(out)
    } else {
        None
    }
}
