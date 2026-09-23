//! Container integrity check — the same invariants the engine's `LoadFileList`
//! enforces before it will install an index.

use crate::jpak::crypto::crc32;
use crate::jpak::index::{flags, Method};
use crate::jpak::{Pak, Result};

#[derive(Debug, Default)]
pub struct Report {
    pub file_size: u64,
    pub gen: u32,
    pub used_end: u32,
    pub arrays: usize,
    pub records: usize,
    pub crc_fail: usize,
    pub bounds_fail: usize,
    pub method_fail: usize,
    pub payload_crc_fail: usize,
    pub empty: usize,
    pub stored_bytes: u64,
    pub original_bytes: u64,
    pub encrypted: usize,
    pub manifest: usize,
    pub snappy: usize,
    pub first_failures: Vec<String>,
}

impl Report {
    pub fn ok(&self, deep: bool) -> bool {
        self.crc_fail == 0
            && self.bounds_fail == 0
            && self.method_fail == 0
            && (!deep || self.payload_crc_fail == 0)
    }
}

pub fn verify(pak: &Pak, deep: bool) -> Result<Report> {
    let data = pak.data();
    let mut r = Report {
        file_size: pak.file_size(),
        gen: pak.header.gen,
        used_end: pak.header.used_end,
        arrays: pak.arrays.len(),
        ..Default::default()
    };

    for rec in pak.records() {
        r.records += 1;
        if !rec.checksum_ok(data) {
            r.crc_fail += 1;
            r.note(&rec, "record crc");
            continue;
        }
        if rec.occupied < rec.stored || rec.occupied as u64 % 8 != 0 {
            r.bounds_fail += 1;
            r.note(&rec, "occupied < stored or not 8-aligned");
        }
        let end = rec.offset as u64 + rec.occupied as u64;
        if end > pak.file_size() {
            r.bounds_fail += 1;
            r.note(&rec, "payload beyond eof");
        }
        if end > r.used_end as u64 && r.used_end != 0 {
            r.bounds_fail += 1;
            r.note(&rec, "payload beyond used_end watermark");
        }
        match rec.method() {
            Method::Stored => {}
            Method::Snappy => r.snappy += 1,
            Method::Unknown(m) => {
                r.method_fail += 1;
                r.note(&rec, &format!("unknown method {m:#04x}"));
            }
        }
        if rec.stored == 0 {
            r.empty += 1;
            continue;
        }
        r.stored_bytes += rec.stored as u64;
        r.original_bytes += rec.original as u64;
        if rec.has_flag(flags::ENCRYPTED) {
            r.encrypted += 1;
        }
        if rec.has_flag(flags::MANIFEST) {
            r.manifest += 1;
        }
        if deep {
            if let Some(bytes) = rec.stored_bytes(data) {
                if crc32(0, bytes) != rec.file_crc {
                    r.payload_crc_fail += 1;
                    r.note(&rec, "payload crc");
                }
            }
        }
    }
    Ok(r)
}

impl Report {
    fn note(&mut self, rec: &crate::jpak::Record, why: &str) {
        if self.first_failures.len() < 10 {
            self.first_failures
                .push(format!("{:016x} @ {:#x}: {}", rec.hash, rec.at, why));
        }
    }
}
