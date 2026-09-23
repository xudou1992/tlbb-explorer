//! Phase-4 acceptance: 200 shipped entries decoded by Rust must match the Python
//! reference byte for byte. Vectors come from `.scratch/golden.py`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};
use tlbb_core::jpak::crypto::crc32;
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

#[derive(Debug)]
struct Row {
    kind: String,
    pak: String,
    hash: u64,
    offset: u32,
    stored: u32,
    original: u32,
    crc32: u32,
    sha256: String,
    head: String,
    tail: String,
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn load() -> Vec<Row> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden/entries.tsv");
    let text = std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("{}: {e} — rerun .scratch/golden.py", path.display()));
    text.lines()
        .skip(1)
        .filter(|l| !l.trim().is_empty())
        .map(|l| {
            let c: Vec<&str> = l.split('\t').collect();
            Row {
                kind: c[0].to_string(),
                pak: c[1].to_string(),
                hash: u64::from_str_radix(c[2], 16).unwrap(),
                offset: c[3].parse().unwrap(),
                stored: c[4].parse().unwrap(),
                original: c[5].parse().unwrap(),
                crc32: c[9].parse().unwrap(),
                sha256: c[10].to_string(),
                head: c[11].to_string(),
                tail: c[12].to_string(),
            }
        })
        .collect()
}

#[test]
fn golden_entries_match_the_python_reference() {
    let root = Path::new(if cfg!(windows) { "D:/TLGL" } else { "/mnt/d/TLGL" });
    if !root.join("data.pak").exists() {
        eprintln!("skip: no paks under {}", root.display());
        return;
    }
    let rows = load();
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut by_kind: HashMap<String, usize> = HashMap::new();
    let mut checked = 0usize;

    for row in &rows {
        if !paks.contains_key(&row.pak) {
            let p: PathBuf = root.join(&row.pak);
            paks.insert(row.pak.clone(), Pak::open(&p).expect("open pak"));
        }
        let pak = &paks[&row.pak];
        let rec = pak
            .records()
            .find(|r| r.hash == row.hash && r.offset == row.offset)
            .unwrap_or_else(|| panic!("{:016x} @ {} not found in {}", row.hash, row.offset, row.pak));

        assert_eq!(rec.stored, row.stored, "stored size drifted");
        assert_eq!(rec.original, row.original, "original size drifted");

        let d = payload::decode(pak, &rec)
            .unwrap_or_else(|e| panic!("{:016x} [{}]: {e}", row.hash, row.kind));
        assert_eq!(d.bytes.len() as u32, row.original, "decoded length");
        assert_eq!(crc32(0, &d.bytes), row.crc32, "crc32 {:016x}", row.hash);

        let mut h = Sha256::new();
        h.update(&d.bytes);
        assert_eq!(hex(&h.finalize()), row.sha256, "sha256 {:016x}", row.hash);

        let n = d.bytes.len().min(64);
        assert_eq!(hex(&d.bytes[..n]), row.head, "head64 {:016x}", row.hash);
        assert_eq!(hex(&d.bytes[d.bytes.len() - n..]), row.tail, "tail64 {:016x}", row.hash);

        // Branch-specific expectations, so a row cannot pass by landing in the wrong bucket.
        match row.kind.as_str() {
            "manifest" => {
                let p = d.info.path.as_ref().expect("manifest row lost its path");
                assert!(!p.is_empty() && !p.contains('\0'), "bad path {p:?}");
            }
            "plain" => assert!(!d.info.encrypted, "plain row was decrypted"),
            "stored" => assert!(!d.info.compressed, "stored row claimed compression"),
            _ => {}
        }
        if row.kind == "huge" {
            assert!(d.bytes.len() > 1_000_000);
        }
        *by_kind.entry(row.kind.clone()).or_default() += 1;
        checked += 1;
    }

    let mut kinds: Vec<_> = by_kind.into_iter().collect();
    kinds.sort();
    println!("[OK] {checked}/{} entries byte-identical to the Python reference", rows.len());
    for (k, n) in &kinds {
        println!("     {k:<10} {n}");
    }
    assert_eq!(checked, rows.len());
    assert!(checked >= 200, "expected at least 200 vectors, got {checked}");
}
