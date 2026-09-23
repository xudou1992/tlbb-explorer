//! The optional per-record name prefix (`flags & 1`, present on 154 of 116,561 records).
//!
//! Layout after decryption: `[u8 path_len][path][u32 version][u64 FILETIME][u32 crc]`.
//! The CRC sits at `path_len + 12`, not `+ 13` — reading it one byte late is the
//! classic off-by-one here and silently fails every manifest check.

use crate::jpak::{Error, Result};

#[derive(Debug, Clone, Copy)]
pub struct Manifest<'a> {
    pub path: &'a [u8],
    pub version: u32,
    /// Windows FILETIME: 100 ns ticks since 1601-01-01.
    pub timestamp: u64,
    pub crc: u32,
}

impl<'a> Manifest<'a> {
    /// Path as written by the packer: `\` normalised to `/`, trailing blanks and any
    /// NUL padding dropped, legacy ANSI (GBK on this build) decoded lossily.
    pub fn path_string(&self) -> String {
        let mut raw = self.path;
        if let Some(nul) = raw.iter().position(|b| *b == 0) {
            raw = &raw[..nul];
        }
        while raw.last() == Some(&b' ') {
            raw = &raw[..raw.len() - 1];
        }
        decode_ansi(raw).replace('\\', "/")
    }
}

/// Returns the payload that follows the prefix plus the parsed header.
pub fn strip(body: &[u8]) -> Result<(&[u8], Manifest<'_>)> {
    if body.is_empty() {
        return Err(Error::Record {
            offset: 0,
            reason: "manifest: empty body".into(),
        });
    }
    let path_len = body[0] as usize;
    let attrs = 1 + path_len;
    if attrs + 16 > body.len() {
        return Err(Error::Record {
            offset: 0,
            reason: format!(
                "manifest: path_len {path_len} overruns body of {} bytes",
                body.len()
            ),
        });
    }
    let m = Manifest {
        path: &body[1..attrs],
        version: u32::from_le_bytes(body[attrs..attrs + 4].try_into().unwrap()),
        timestamp: u64::from_le_bytes(body[attrs + 4..attrs + 12].try_into().unwrap()),
        crc: u32::from_le_bytes(body[attrs + 12..attrs + 16].try_into().unwrap()),
    };
    Ok((&body[attrs + 16..], m))
}

fn decode_ansi(raw: &[u8]) -> String {
    if raw.is_ascii() {
        return String::from_utf8_lossy(raw).into_owned();
    }
    // The shipped packer wrote ANSI paths; only the manifest prefix can carry them.
    match windows_ansi(raw) {
        Some(s) => s,
        None => String::from_utf8_lossy(raw).into_owned(),
    }
}

#[cfg(windows)]
fn windows_ansi(raw: &[u8]) -> Option<String> {
    use std::os::windows::ffi::OsStringExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn MultiByteToWideChar(
            code_page: u32,
            flags: u32,
            mb: *const u8,
            mb_len: i32,
            wc: *mut u16,
            wc_len: i32,
        ) -> i32;
    }
    const CP_ACP: u32 = 0;
    let need = unsafe { MultiByteToWideChar(CP_ACP, 0, raw.as_ptr(), raw.len() as i32, std::ptr::null_mut(), 0) };
    if need <= 0 {
        return None;
    }
    let mut wide = vec![0u16; need as usize];
    let got = unsafe {
        MultiByteToWideChar(CP_ACP, 0, raw.as_ptr(), raw.len() as i32, wide.as_mut_ptr(), need)
    };
    if got <= 0 {
        return None;
    }
    wide.truncate(got as usize);
    Some(std::ffi::OsString::from_wide(&wide).to_string_lossy().into_owned())
}

#[cfg(not(windows))]
fn windows_ansi(_raw: &[u8]) -> Option<String> {
    None
}
