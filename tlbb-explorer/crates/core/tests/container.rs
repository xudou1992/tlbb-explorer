//! Chain walking against the real containers. Skips when the game dir isn't present.

use std::path::Path;
use tlbb_core::jpak::{verify, Pak};

const ROOT: &str = "D:/TLGL";

#[test]
fn data_pak_chain_is_exact() {
    let path = Path::new(ROOT).join("data.pak");
    if !path.exists() {
        eprintln!("skip: {path:?} not present");
        return;
    }
    let pak = Pak::open(&path).expect("open");
    assert_eq!(pak.arrays.len(), 16);
    assert_eq!(pak.arrays.last().unwrap().next, 0, "chain must terminate");
    assert!(pak.arrays.iter().all(|a| a.used <= a.cap));

    let r = verify::verify(&pak, true).expect("verify");
    assert_eq!(r.records, 15_651);
    assert_eq!(r.crc_fail, 0);
    assert_eq!(r.bounds_fail, 0, "{:?}", r.first_failures);
    assert_eq!(r.method_fail, 0);
    assert_eq!(r.payload_crc_fail, 0, "{:?}", r.first_failures);
    assert!(r.encrypted > 0 && r.snappy > 0);
    // used_end is the writer's high-water mark; payloads must never cross it.
    assert!(pak.records().all(|rec| rec.offset as u64 + rec.occupied as u64 <= r.used_end as u64));
}

#[test]
fn rejects_non_jpak_input() {
    let path = Path::new(ROOT).join("tlbbgl_x64.exe");
    if !path.exists() {
        return;
    }
    let err = match Pak::open(&path) {
        Ok(_) => panic!("an .exe must not parse as JPAK"),
        Err(e) => e,
    }
    .to_string();
    assert!(err.contains("JPAK"), "unexpected error: {err}");
}

/// A card for a resource with no recorded path must never borrow an image from elsewhere.
#[test]
fn empty_dir_yields_no_texture_candidates() {
    let db = std::path::Path::new("D:/TLGL/.scratch/resources.db");
    if !db.exists() {
        eprintln!("skip: catalog absent");
        return;
    }
    let cat = tlbb_core::catalog::Catalog::open_ro(db).unwrap();
    assert!(cat.textures_in_dir("").unwrap().is_empty());
    assert!(cat.textures_in_dir("   ").unwrap().is_empty());
    assert!(!cat.textures_in_dir("ui/icon/skill").unwrap().is_empty());
}
