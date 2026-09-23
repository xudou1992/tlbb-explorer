//! Open a pak read-only and walk its index chain.

use std::fs::File;
use std::path::{Path, PathBuf};

use memmap2::Mmap;

use crate::jpak::index::{
    ArrayHeader, FileHeader, Record, ARRAY_HEADER_LEN, MAX_CAP, RECORD_LEN,
};
use crate::jpak::{Error, Result};

pub struct Pak {
    path: PathBuf,
    data: Mmap,
    pub header: FileHeader,
    pub arrays: Vec<ArrayHeader>,
}

impl Pak {
    pub fn open(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref().to_path_buf();
        let file = File::open(&path).map_err(|source| Error::Io {
            context: format!("open {}", path.display()),
            source,
        })?;
        let data = unsafe { Mmap::map(&file) }.map_err(|source| Error::Io {
            context: format!("mmap {}", path.display()),
            source,
        })?;
        let header = FileHeader::parse(&data)?;
        let arrays = walk(&data)?;
        Ok(Self {
            path,
            data,
            header,
            arrays,
        })
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn data(&self) -> &[u8] {
        &self.data
    }

    pub fn file_size(&self) -> u64 {
        self.data.len() as u64
    }

    pub fn record_total(&self) -> usize {
        self.arrays.iter().map(|a| a.used as usize).sum()
    }

    pub fn records(&self) -> impl Iterator<Item = Record> + '_ {
        self.arrays
            .iter()
            .enumerate()
            .flat_map(move |(idx, array)| {
                let base = array.records_at() as usize;
                (0..array.used as usize).filter_map(move |i| {
                    let at = (base + i * RECORD_LEN) as u64;
                    if at as usize + RECORD_LEN > self.data.len() {
                        return None;
                    }
                    Some(Record::parse(at, idx as u32, &self.data))
                })
            })
    }
}

/// Follow `next` pointers from the first array. Every link is CRC-checked by
/// [`ArrayHeader::parse`], so a chain that survives this walk is the chain the
/// engine's `LoadFileList` would install.
fn walk(data: &[u8]) -> Result<Vec<ArrayHeader>> {
    let mut out = Vec::new();
    let mut at = ARRAY_HEADER_LEN; // first array follows the 16-byte file header
    loop {
        let array = ArrayHeader::parse(at, data)?;
        if array.used > array.cap || array.cap > MAX_CAP {
            return Err(Error::Chain {
                offset: at,
                reason: format!("cap={} used={}", array.cap, array.used),
            });
        }
        let end = array.records_at() + array.cap as u64 * RECORD_LEN as u64;
        if end > data.len() as u64 {
            return Err(Error::Truncated {
                what: "index array",
                need: end,
                have: data.len() as u64,
            });
        }
        let last_slot_end = array.records_at() + array.used as u64 * RECORD_LEN as u64;
        out.push(array);
        if array.next == 0 {
            return Ok(out);
        }
        if array.next as u64 <= last_slot_end {
            return Err(Error::Chain {
                offset: at,
                reason: format!("next={:#x} overlaps records ending at {:#x}", array.next, last_slot_end),
            });
        }
        at = array.next as u64;
    }
}
