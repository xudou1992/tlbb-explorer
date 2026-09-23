//! On-disk structures: 16-byte file header, the linked index arrays, 36-byte records.

use crate::jpak::crypto::crc32;
use crate::jpak::{Error, Result};

pub const MAGIC: [u8; 4] = *b"JPAK";
pub const FILE_HEADER_LEN: u64 = 16;
pub const ARRAY_HEADER_LEN: u64 = 16;
pub const RECORD_LEN: usize = 36;

/// Records per index array as shipped; larger values only ever appear in hand-made paks.
pub const MAX_CAP: u32 = 65_536;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FileHeader {
    pub gen: u32,
    pub used_end: u32,
    pub crc: u32,
}

impl FileHeader {
    pub fn parse(data: &[u8]) -> Result<Self> {
        if data.len() < FILE_HEADER_LEN as usize {
            return Err(Error::Truncated {
                what: "file header",
                need: FILE_HEADER_LEN,
                have: data.len() as u64,
            });
        }
        if data[..4] != MAGIC {
            let mut found = [0u8; 4];
            found.copy_from_slice(&data[..4]);
            return Err(Error::BadMagic { found });
        }
        let this = Self {
            gen: rd32(data, 4),
            used_end: rd32(data, 8),
            crc: rd32(data, 12),
        };
        if !this.checksum_ok(data) {
            return Err(Error::Checksum {
                what: "file header",
                offset: 0,
                found: this.crc,
                expected: crc32(0, &data[..12]),
            });
        }
        Ok(this)
    }

    pub fn checksum_ok(&self, data: &[u8]) -> bool {
        self.crc == crc32(0, &data[..12])
    }
}

/// One link of the index chain. `next` is an absolute file offset, `0` ends the chain.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ArrayHeader {
    pub at: u64,
    pub cap: u32,
    pub used: u32,
    pub next: u32,
    pub crc: u32,
}

impl ArrayHeader {
    pub fn parse(at: u64, data: &[u8]) -> Result<Self> {
        let need = at as usize + ARRAY_HEADER_LEN as usize;
        if data.len() < need {
            return Err(Error::Truncated {
                what: "index array header",
                need: need as u64,
                have: data.len() as u64,
            });
        }
        let b = &data[at as usize..need];
        let this = Self {
            at,
            cap: rd32(b, 0),
            used: rd32(b, 4),
            next: rd32(b, 8),
            crc: rd32(b, 12),
        };
        if this.crc != crc32(0, &b[..12]) {
            return Err(Error::Checksum {
                what: "index array header",
                offset: at,
                found: this.crc,
                expected: crc32(0, &b[..12]),
            });
        }
        Ok(this)
    }

    pub fn records_at(&self) -> u64 {
        self.at + ARRAY_HEADER_LEN
    }
}

pub mod flags {
    pub const MANIFEST: u8 = 1 << 0;
    pub const LOCKED: u8 = 1 << 1;
    pub const ENCRYPTED: u8 = 1 << 2;
    pub const PADDED: u8 = 1 << 3;
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Method {
    Stored,
    Snappy,
    Unknown(u8),
}

#[derive(Debug, Clone, Copy)]
pub struct Record {
    pub at: u64,
    pub array: u32,
    pub hash: u64,
    pub offset: u32,
    pub stored: u32,
    pub occupied: u32,
    pub original: u32,
    pub version: u16,
    pub flags: u8,
    pub method: u8,
    pub file_crc: u32,
    pub crc: u32,
}

impl Record {
    /// Caller guarantees `data.len() >= at + RECORD_LEN`.
    pub fn parse(at: u64, array: u32, data: &[u8]) -> Self {
        let b = &data[at as usize..at as usize + RECORD_LEN];
        Self {
            at,
            array,
            hash: u64::from_le_bytes(b[..8].try_into().unwrap()),
            offset: rd32(b, 8),
            stored: rd32(b, 12),
            occupied: rd32(b, 16),
            original: rd32(b, 20),
            version: u16::from_le_bytes(b[24..26].try_into().unwrap()),
            flags: b[26],
            method: b[27],
            file_crc: rd32(b, 28),
            crc: rd32(b, 32),
        }
    }

    pub fn checksum_ok(&self, data: &[u8]) -> bool {
        let b = &data[self.at as usize..self.at as usize + RECORD_LEN];
        self.crc == crc32(0, &b[..32])
    }

    pub fn method(&self) -> Method {
        match self.method {
            0 => Method::Stored,
            0x33 => Method::Snappy,
            other => Method::Unknown(other),
        }
    }

    pub fn has_flag(&self, f: u8) -> bool {
        self.flags & f != 0
    }

    /// The stored byte range, or `None` when the record points outside the file.
    pub fn stored_bytes<'a>(&self, data: &'a [u8]) -> Option<&'a [u8]> {
        let start = self.offset as usize;
        let end = start.checked_add(self.stored as usize)?;
        if end <= data.len() {
            Some(&data[start..end])
        } else {
            None
        }
    }
}

fn rd32(b: &[u8], at: usize) -> u32 {
    u32::from_le_bytes(b[at..at + 4].try_into().unwrap())
}
