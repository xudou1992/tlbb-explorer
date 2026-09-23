//! Phase-1 probe: show what an index entry actually contains, and exercise the whole
//! decode chain over a spread of shipped records.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use tlbb_core::jpak::index::{flags, Method, Record};
use tlbb_core::jpak::Pak;
use tlbb_core::payload::{self, snappy};

#[derive(Default)]
struct Opt {
    root: PathBuf,
    pak: Option<PathBuf>,
    hash: Option<u64>,
    detail: usize,
    selftest: usize,
    out: Option<PathBuf>,
}

fn parse() -> Opt {
    let mut o = Opt {
        root: PathBuf::from("D:/TLGL"),
        detail: 5,
        ..Default::default()
    };
    let raw: Vec<String> = std::env::args().skip(1).collect();
    // Accept both `--key value` and `--key=value`.
    let mut args: Vec<(String, Option<String>)> = Vec::new();
    let mut i = 0;
    while i < raw.len() {
        if let Some((k, v)) = raw[i].split_once('=') {
            args.push((k.to_string(), Some(v.to_string())));
        } else if raw[i].starts_with("--") {
            let next = raw.get(i + 1);
            match next.map(|s| s.starts_with("--")) {
                Some(false) => {
                    args.push((raw[i].clone(), Some(next.unwrap().clone())));
                    i += 1;
                }
                _ => args.push((raw[i].clone(), None)),
            }
        } else {
            args.push((raw[i].clone(), None));
        }
        i += 1;
    }
    for (flag, val) in args {
        let v = || val.clone().unwrap_or_default();
        match flag.as_str() {
            "--pak" => o.pak = Some(PathBuf::from(v())),
            "--root" => o.root = PathBuf::from(v()),
            "--hash" => o.hash = u64::from_str_radix(v().trim_start_matches("0x"), 16).ok(),
            "--detail" => o.detail = v().parse().unwrap_or(5),
            "--selftest" => o.selftest = v().parse().unwrap_or(500),
            "--out" => o.out = Some(PathBuf::from(v())),
            _ => {
                if !flag.starts_with("--") {
                    o.pak = Some(PathBuf::from(flag));
                }
            }
        }
    }
    o
}

fn flag_text(f: u8) -> String {
    let mut v = Vec::new();
    for (bit, name) in [
        (flags::MANIFEST, "manifest"),
        (flags::LOCKED, "locked"),
        (flags::ENCRYPTED, "encrypted"),
        (flags::PADDED, "padded"),
    ] {
        if f & bit != 0 {
            v.push(name);
        }
    }
    if v.is_empty() {
        v.push("plain");
    }
    v.join(" ")
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn ascii(b: &[u8]) -> String {
    b.iter()
        .map(|c| if c.is_ascii_graphic() || *c == b' ' { *c as char } else { '.' })
        .collect()
}

fn show(pak: &Pak, rec: &Record, dump: Option<&Path>) -> (bool, Vec<u8>) {
    println!("  hash           {:016x}", rec.hash);
    println!("  index_offset   {}  (array slot @ {:#x})", rec.at, rec.at);
    println!(
        "  offset         {}   stored {}   occupied {}   raw {}",
        rec.offset, rec.stored, rec.occupied, rec.original
    );
    println!("  flags          {:#04x}  {}", rec.flags, flag_text(rec.flags));
    println!("  version        {}   method {:#04x}", rec.version, rec.method);

    let (body, info) = match payload::body(pak, rec) {
        Ok(v) => v,
        Err(e) => {
            println!("  body           FAILED {e}");
            return (false, Vec::new());
        }
    };
    match &info.path {
        Some(p) => println!(
            "  manifest       {p}  ver={} time={:#x} crc_ok={}",
            info.manifest_version, info.timestamp, info.manifest_crc
        ),
        None => println!("  manifest       none"),
    }
    if rec.method() == Method::Snappy {
        println!(
            "  snappy_header  {}",
            snappy::declared_len(&body).map_or_else(|e| format!("BAD {e}"), |n| n.to_string())
        );
    }
    let bytes = match payload::inflate(rec, body.clone()) {
        Ok(b) => b,
        Err(e) => {
            println!("  decode         FAILED {e}");
            return (false, Vec::new());
        }
    };
    let head = &bytes[..bytes.len().min(8)];
    println!(
        "  decode         {} bytes OK   head {} \"{}\"",
        bytes.len(),
        hex(&bytes[..bytes.len().min(12)]),
        ascii(head)
    );
    if let Some(dir) = dump {
        let name = info
            .path
            .clone()
            .unwrap_or_else(|| format!("{:016x}.bin", rec.hash));
        let dest = dir.join(name.replace(['/', '\\'], "_"));
        if let Err(e) = std::fs::write(&dest, &bytes) {
            println!("  dump           FAILED {e}");
        } else {
            println!("  dump           {}", dest.display());
        }
    }
    (true, bytes)
}

fn main() {
    let opt = parse();
    let paks: Vec<PathBuf> = match &opt.pak {
        Some(p) => vec![p.clone()],
        None => {
            let mut v: Vec<_> = std::fs::read_dir(&opt.root)
                .expect("read root")
                .flatten()
                .map(|e| e.path())
                .filter(|p| p.extension().map(|x| x == "pak").unwrap_or(false))
                .collect();
            v.sort();
            v
        }
    };

    let mut magics: HashMap<[u8; 4], usize> = HashMap::new();
    let mut kinds: HashMap<&str, usize> = HashMap::new();
    let (mut ok, mut fail) = (0usize, 0usize);

    for path in &paks {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let pak = match Pak::open(path) {
            Ok(p) => p,
            Err(e) => {
                println!("{name}: open failed: {e}");
                fail += 1;
                continue;
            }
        };
        let total = pak.record_total();
        println!("== {name}  arrays={} records={}", pak.arrays.len(), total);

        if let Some(want) = opt.hash {
            for rec in pak.records() {
                if rec.hash == want {
                    show(&pak, &rec, opt.out.as_deref());
                    return;
                }
            }
            println!("  {:016x} not present in {name}", want);
            continue;
        }

        let stride = (total / opt.detail.max(1)).max(1);
        for (i, rec) in pak.records().enumerate() {
            if i % stride == 0 && i / stride < opt.detail {
                show(&pak, &rec, opt.out.as_deref());
            }
        }

        if opt.selftest > 0 {
            let stride = (total / opt.selftest).max(1);
            for (i, rec) in pak.records().enumerate() {
                if i % stride != 0 {
                    continue;
                }
                let kind = match rec.method() {
                    Method::Stored => "stored",
                    Method::Snappy => "snappy",
                    Method::Unknown(_) => "unknown",
                };
                *kinds.entry(kind).or_default() += 1;
                match payload::decode(&pak, &rec) {
                    Ok(d) => {
                        ok += 1;
                        let mut k = [0u8; 4];
                        let n = d.bytes.len().min(4);
                        k[..n].copy_from_slice(&d.bytes[..n]);
                        *magics.entry(k).or_default() += 1;
                        if d.info.path.is_some() && !d.manifest_crc_ok {
                            fail += 1;
                            println!("  MANIFEST CRC MISMATCH {:016x}", rec.hash);
                        }
                    }
                    Err(e) => {
                        fail += 1;
                        if fail <= 10 {
                            println!("  FAIL {:016x}: {e}", rec.hash);
                        }
                    }
                }
            }
        }
    }

    if opt.selftest > 0 {
        let mut m: Vec<_> = magics.into_iter().collect();
        m.sort_by(|a, b| b.1.cmp(&a.1));
        println!(
            "-- selftest {} ok / {} fail over methods {:?}",
            ok, fail, kinds
        );
        for (k, n) in m.iter().take(10) {
            println!("     head {} \"{}\" x{}", hex(k), ascii(k), n);
        }
    }
    if fail > 0 {
        std::process::exit(1);
    }
}
