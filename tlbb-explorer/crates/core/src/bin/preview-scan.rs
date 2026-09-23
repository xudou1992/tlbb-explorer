//! M2 driver: census the decoders over the real catalog and emit first-pass previews.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use tlbb_core::catalog::Catalog;
use tlbb_core::jbcf::{self, Role};
use tlbb_core::jmt1::{self, Codec};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview;

struct Args {
    root: PathBuf,
    db: PathBuf,
    out: Option<PathBuf>,
    unnamed: bool,
    thumb: usize,
    pick: usize,
    limit: usize,
    named: bool,
}

fn parse() -> Args {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut a = Args {
        root: PathBuf::from("D:/TLGL"),
        db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
        out: None,
        unnamed: false,
        thumb: 0,
        pick: 12,
        limit: usize::MAX,
        named: false,
    };
    let mut i = 0;
    while i < raw.len() {
        let (k, v) = match raw[i].split_once('=') {
            Some((k, v)) => (k.to_string(), Some(v.to_string())),
            None => {
                let k = raw[i].clone();
                let v = raw.get(i + 1).filter(|s| !s.starts_with("--")).map(|s| s.clone());
                if v.is_some() {
                    i += 1;
                }
                (k, v)
            }
        };
        let v = || v.clone().unwrap_or_default();
        match k.as_str() {
            "--root" => a.root = PathBuf::from(v()),
            "--db" => a.db = PathBuf::from(v()),
            "--out" => a.out = Some(PathBuf::from(v())),
            "--pick" => a.pick = v().parse().unwrap_or(12),
            "--limit" => a.limit = v().parse().unwrap_or(usize::MAX),
            "--named" => a.named = true,
            "--unnamed" => a.unnamed = true,
            "--thumb" => a.thumb = v().parse().unwrap_or(0),
            _ => {}
        }
        i += 1;
    }
    a
}

type Index = HashMap<(String, u64), tlbb_core::Record>;

fn load_paks(root: &Path) -> (HashMap<String, Pak>, Index) {
    let mut paks = HashMap::new();
    let mut idx: Index = HashMap::new();
    let mut files: Vec<_> = std::fs::read_dir(root)
        .expect("read root")
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "pak").unwrap_or(false))
        .collect();
    files.sort();
    for path in files {
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        let pak = Pak::open(&path).expect("open pak");
        for rec in pak.records() {
            idx.insert((stem.clone(), rec.hash), rec);
        }
        paks.insert(stem, pak);
    }
    (paks, idx)
}

fn decode_asset(paks: &HashMap<String, Pak>, idx: &Index, pak: &str, hash: u64, want_off: i64) -> Result<Vec<u8>, String> {
    let rec = idx
        .get(&(pak.to_string(), hash))
        .ok_or_else(|| "not in index".to_string())?;
    if rec.offset as i64 != want_off {
        return Err(format!("offset moved: index {} vs catalog {want_off}", rec.offset));
    }
    let pak = paks.get(pak).ok_or("pak missing")?;
    payload::decode(pak, rec).map(|d| d.bytes).map_err(|e| e.to_string())
}

fn safe_name(asset: &tlbb_core::catalog::Asset, hash: u64) -> String {
    match &asset.path {
        Some(p) => p.replace(['/', '\\'], "_"),
        None => format!("{hash:016x}"),
    }
}

fn census_textures(a: &Args, cat: &Catalog, paks: &HashMap<String, Pak>, idx: &Index) {
    let rows = cat.by_type("texture", a.limit).expect("query");
    let (named, total) = cat.named_of_type("texture").expect("count");
    let mut codec: HashMap<&str, usize> = HashMap::new();
    let mut declared: HashMap<String, usize> = HashMap::new();
    let mut err: HashMap<String, usize> = HashMap::new();
    let mut done = 0usize;
    let mut written = 0usize;
    let mut picked: Vec<(String, u16, u16, Codec)> = Vec::new();

    for asset in &rows {
        let hash = asset.hash;
        let bytes = match decode_asset(paks, idx, &asset.pak, hash, asset.offset) {
            Ok(b) => b,
            Err(e) => {
                *err.entry(e).or_default() += 1;
                continue;
            }
        };
        match jmt1::decode(&bytes) {
            Ok(tex) => {
                done += 1;
                *codec.entry(tex.codec.as_str()).or_default() += 1;
                *declared.entry(tex.declared_tag.clone()).or_default() += 1;
                if let Some(out) = &a.out {
                    // --named exports only assets that carry a real path; otherwise the
                    // big picks list falls back to unnamed blobs once named ones run out.
                    let wanted = match (a.named, a.unnamed) {
                        (true, _) => asset.named,
                        (_, true) => !asset.named,
                        (false, false) => asset.named || a.pick > 200,
                    };
                    if written < a.pick && wanted {
                        let dir = out.join("texture_preview");
                        let base = safe_name(asset, hash);
                        let (px, tw, th) = if a.thumb > 0 && tex.codec != Codec::Webp {
                            tlbb_core::preview::scale_rgba(&tex.rgba, tex.width as usize, tex.height as usize, a.thumb)
                        } else {
                            (tex.rgba.clone(), tex.width as usize, tex.height as usize)
                        };
                        let res = if tex.codec == Codec::Webp {
                            match &tex.webp {
                                Some(w) => std::fs::create_dir_all(&dir)
                                    .map_err(|e| e.to_string())
                                    .and_then(|_| {
                                        std::fs::write(dir.join(format!("{base}.webp")), w)
                                            .map_err(|e| e.to_string())
                                    }),
                                None => Err("no webp bytes".into()),
                            }
                        } else {
                            preview::write_png(
                                &dir.join(format!("{base}.png")),
                                tw as u16,
                                th as u16,
                                &px,
                            )
                        };
                        match res {
                            Ok(_) => written += 1,
                            Err(e) => println!("  write failed {base}: {e}"),
                        }
                    }
                }
                if asset.named && picked.len() < a.pick {
                    picked.push((
                        asset.path.clone().unwrap_or_default(),
                        tex.width,
                        tex.height,
                        tex.codec,
                    ));
                }
            }
            Err(e) => {
                *err.entry(e.to_string()).or_default() += 1;
            }
        }
    }

    println!("TEXTURE  rows={} named={named}/{total} decoded={done}", rows.len());
    let mut c: Vec<_> = codec.into_iter().collect();
    c.sort_by(|x, y| y.1.cmp(&x.1));
    println!("  codec: {c:?}");
    let mut d: Vec<_> = declared.into_iter().collect();
    d.sort_by(|x, y| y.1.cmp(&x.1));
    println!("  declared 4CC (untrusted): {d:?}");
    if !err.is_empty() {
        let mut e: Vec<_> = err.into_iter().collect();
        e.sort_by(|x, y| y.1.cmp(&x.1));
        println!("  errors: {:?}", &e[..e.len().min(6)]);
    }
    println!("  named samples:");
    for (p, w, h, cd) in picked.iter().take(8) {
        println!("     {p:<62} {w:>4}x{h:<4} {cd:?}");
    }
    if let Some(out) = &a.out {
        println!("  wrote {written} files under {}", out.join("texture_preview").display());
    }
}

fn census_jbcf(a: &Args, cat: &Catalog, paks: &HashMap<String, Pak>, idx: &Index) {
    let rows = cat.by_type("JBCF", a.limit).expect("query");
    let mut ok = 0usize;
    let mut err: HashMap<String, usize> = HashMap::new();
    let mut with_textures = 0usize;
    let mut with_material = 0usize;
    let mut with_ske = 0usize;
    let mut with_ani = 0usize;
    let mut strings = 0usize;
    let mut shown = 0usize;

    for asset in &rows {
        let bytes = match decode_asset(paks, idx, &asset.pak, asset.hash, asset.offset) {
            Ok(b) => b,
            Err(e) => {
                *err.entry(e).or_default() += 1;
                continue;
            }
        };
        match jbcf::parse(&bytes) {
            Ok(f) => {
                ok += 1;
                strings += f.strings.len();
                let tex = f.names(Role::Texture).len();
                let mtl = f.names(Role::Material).len();
                let ske = f.names(Role::Skeleton).len();
                let ani = f.names(Role::Animation).len();
                with_textures += tex.min(1) as usize;
                with_material += mtl.min(1) as usize;
                with_ske += ske.min(1) as usize;
                with_ani += ani.min(1) as usize;
                if asset.named && shown < 3 && tex + mtl > 0 {
                    println!(
                        "  {}  str={} tex={} mtl={} ske={} ani={}",
                        asset.path.clone().unwrap_or_default(),
                        f.strings.len(),
                        tex,
                        mtl,
                        ske,
                        ani
                    );
                    for s in f.names(Role::Texture).iter().take(5) {
                        println!("       tex  {s}");
                    }
                    for s in f.names(Role::Material).iter().take(3) {
                        println!("       mtl  {s}");
                    }
                    if let Ok(rs) = cat.refs_from(asset.hash) {
                        let hit = rs.iter().filter(|r| r.to.is_some()).count();
                        println!("       refs {} rows, {} resolved to a hash", rs.len(), hit);
                    }
                    shown += 1;
                }
            }
            Err(e) => {
                *err.entry(e.to_string()).or_default() += 1;
            }
        }
    }
    println!(
        "JBCF     rows={} parsed={ok} strings={}",
        rows.len(),
        strings / ok.max(1)
    );
    println!("  files naming: tex={with_textures} mtl={with_material} ske={with_ske} ani={with_ani}");
    if !err.is_empty() {
        let mut e: Vec<_> = err.into_iter().collect();
        e.sort_by(|x, y| y.1.cmp(&x.1));
        println!("  errors: {:?}", &e[..e.len().min(6)]);
    }
}

fn main() {
    let a = parse();
    if !a.db.exists() {
        eprintln!("catalog not found: {}", a.db.display());
        std::process::exit(2);
    }
    let (paks, idx) = load_paks(&a.root);
    println!(
        "{} paks, {} indexed records, catalog {}",
        paks.len(),
        idx.len(),
        a.db.display()
    );
    let cat = Catalog::open_ro(&a.db).expect("open catalog");
    if let Some(out) = &a.out {
        std::fs::create_dir_all(out).expect("create out");
    }
    census_textures(&a, &cat, &paks, &idx);
    println!();
    census_jbcf(&a, &cat, &paks, &idx);
}
