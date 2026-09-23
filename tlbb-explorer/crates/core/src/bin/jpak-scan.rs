//! M0 smoke tool: open every shipped pak, walk the chain, verify it, print the panel.

use std::collections::HashMap;
use std::path::Path;

use tlbb_core::jpak::Pak;
use tlbb_core::jpak::verify;

fn gib(n: u64) -> String {
    format!("{:.1} GiB", n as f64 / (1 << 30) as f64)
}

fn mib(n: u64) -> String {
    format!("{:.1} MiB", n as f64 / (1 << 20) as f64)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let deep = args.iter().any(|a| a == "--deep");
    let root = args
        .iter()
        .find_map(|a| a.strip_prefix("--root="))
        .map(Path::new)
        .unwrap_or(Path::new("D:/TLGL"));

    let mut paks: Vec<_> = std::fs::read_dir(root)
        .expect("read dir")
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x == "pak").unwrap_or(false))
        .collect();
    paks.sort();

    let mut seen: HashMap<u64, usize> = HashMap::new();
    let (mut t_records, mut t_stored, mut t_original, mut t_bad) = (0usize, 0u64, 0u64, 0usize);

    println!(
        "{:<12} {:>8} {:>7} {:>9} {:>10} {:>10}  {}",
        "pak", "arrays", "records", "used_end", "stored", "original", "status"
    );
    for path in &paks {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        let pak = match Pak::open(path) {
            Ok(p) => p,
            Err(e) => {
                println!("{:<12} OPEN FAILED: {}", name, e);
                t_bad += 1;
                continue;
            }
        };
        let r = verify::verify(&pak, deep).expect("verify");
        for rec in pak.records() {
            *seen.entry(rec.hash).or_insert(0) += 1;
        }
        t_records += r.records;
        t_stored += r.stored_bytes;
        t_original += r.original_bytes;
        let mut fails = Vec::new();
        if r.crc_fail > 0 {
            fails.push(format!("crc={}", r.crc_fail));
        }
        if r.bounds_fail > 0 {
            fails.push(format!("bounds={}", r.bounds_fail));
        }
        if r.method_fail > 0 {
            fails.push(format!("method={}", r.method_fail));
        }
        if deep && r.payload_crc_fail > 0 {
            fails.push(format!("payload_crc={}", r.payload_crc_fail));
        }
        if !fails.is_empty() {
            t_bad += 1;
        }
        println!(
            "{:<12} {:>8} {:>7} {:>10} {:>10} {:>10}  {}",
            name,
            r.arrays,
            r.records,
            mib(r.used_end as u64),
            gib(r.stored_bytes),
            gib(r.original_bytes),
            if fails.is_empty() { "正常".to_string() } else { format!("异常 {}", fails.join(" ")) },
        );
        for f in &r.first_failures {
            println!("             ! {f}");
        }
    }

    let dup = t_records - seen.len();
    println!("{}", "-".repeat(72));
    println!(
        "paks {} | records {} | unique hashes {} | superseded {} | stored {} | payload {}",
        paks.len(),
        t_records,
        seen.len(),
        dup,
        gib(t_stored),
        gib(t_original)
    );
    if deep {
        println!("deep payload CRC: {}", if t_bad == 0 { "all pass" } else { "FAILURES above" });
    }
    if t_bad > 0 {
        std::process::exit(1);
    }
}
