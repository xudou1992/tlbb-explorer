//! Entry layer above the container: decrypt → optional manifest prefix → Snappy.
//!
//! There is no per-entry header. Measured on shipped data: after these three steps the
//! result is always exactly `uFileSize` bytes, so nothing between the index and the
//! asset body needs parsing.

pub mod manifest;
pub mod snappy;

pub use manifest::Manifest;

use crate::jpak::crypto::crypt;
use crate::jpak::index::{flags, Method, Record};
use crate::jpak::{Error, Pak, Result};

/// What the container knows about one entry, decoded or not.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Info {
    pub path: Option<String>,
    pub manifest_version: u32,
    pub timestamp: u64,
    pub manifest_crc: u32,
    pub encrypted: bool,
    pub compressed: bool,
    pub padded: bool,
}

#[derive(Debug, Clone)]
pub struct Decoded {
    pub bytes: Vec<u8>,
    pub info: Info,
    /// crc32 of the manifest prefix's own checksum field vs the decoded body.
    pub manifest_crc_ok: bool,
}

fn err(rec: &Record, reason: impl Into<String>) -> Error {
    Error::Record {
        offset: rec.at,
        reason: reason.into(),
    }
}

/// Stored bytes on disk, decrypted and with the manifest prefix removed.
pub fn body(pak: &Pak, rec: &Record) -> Result<(Vec<u8>, Info)> {
    let stored = rec
        .stored_bytes(pak.data())
        .ok_or_else(|| err(rec, "payload points beyond end of file"))?;
    let mut info = Info {
        encrypted: rec.has_flag(flags::ENCRYPTED),
        compressed: rec.method == 0x33,
        padded: rec.has_flag(flags::PADDED),
        ..Default::default()
    };
    let mut buf = if info.encrypted {
        let mut v = stored.to_vec();
        crypt(rec.hash, rec.stored, &mut v);
        v
    } else {
        stored.to_vec()
    };
    if rec.has_flag(flags::MANIFEST) {
        let (rest, m) = manifest::strip(&buf).map_err(|e| err(rec, e.to_string()))?;
        info.path = Some(m.path_string());
        info.manifest_version = m.version;
        info.timestamp = m.timestamp;
        info.manifest_crc = m.crc;
        let off = buf.len() - rest.len();
        buf.drain(..off);
    }
    Ok((buf, info))
}

/// The real asset bytes, with every length and checksum the container offers verified.
pub fn decode(pak: &Pak, rec: &Record) -> Result<Decoded> {
    let (buf, info) = body(pak, rec)?;
    let bytes = inflate(rec, buf)?;
    let manifest_crc_ok = match info.path {
        Some(_) => crate::jpak::crypto::crc32(0, &bytes) == info.manifest_crc,
        None => false,
    };
    Ok(Decoded {
        bytes,
        info,
        manifest_crc_ok,
    })
}

/// Expand an already-stripped body. Kept public so callers that already hold the
/// decrypted bytes (the probe, the export pipeline) do not redo the cipher.
pub fn inflate(rec: &Record, body: Vec<u8>) -> Result<Vec<u8>> {
    let bytes = match rec.method() {
        Method::Stored => body,
        Method::Snappy => snappy::decompress(&body, Some(rec.original))?,
        Method::Unknown(m) => {
            return Err(err(rec, format!("unknown compression method {m:#04x}")))
        }
    };
    if bytes.len() != rec.original as usize {
        return Err(err(
            rec,
            format!("decoded {} of {} bytes", bytes.len(), rec.original),
        ));
    }
    Ok(bytes)
}
