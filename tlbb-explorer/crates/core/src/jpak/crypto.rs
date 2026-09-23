//! Engine cipher primitives: seeded CRC-32, the per-record keystream, and the path hash.

use crc32fast::Hasher;

/// Keystream table, dumped from `.rdata` at `0x140DC8F90` of `tlbbgl_x64.exe`
/// (sha256 `0d850dc0…`); the segment is read-only so the table is static per build.
pub const CIPHER_TABLE: [u32; 4096] = load_table(include_bytes!("../../assets/cipher_table.bin"));

const fn load_table(bytes: &[u8; 16384]) -> [u32; 4096] {
    let mut out = [0u32; 4096];
    let mut i = 0;
    while i < 4096 {
        out[i] = u32::from_le_bytes([
            bytes[i * 4],
            bytes[i * 4 + 1],
            bytes[i * 4 + 2],
            bytes[i * 4 + 3],
        ]);
        i += 1;
    }
    out
}

/// `sub_1405B0510` — zlib semantics: state starts inverted, result is inverted back.
pub fn crc32(seed: u32, data: &[u8]) -> u32 {
    let mut h = Hasher::new_with_initial(seed);
    h.update(data);
    h.finalize()
}

/// `sub_1405A1CE0` — in-place XOR against the record's keystream. Self-inverse.
///
/// `stored_len` must be the record's full stored size even when `buf` is only its
/// leading bytes: the table index is driven by the total dword count, so a prefix
/// decrypt is exact only if the caller names the whole length.
pub fn crypt(key: u64, stored_len: u32, buf: &mut [u8]) {
    let mut v = crc32(
        crc32(0, &key.to_le_bytes()) ^ 0x0808_8405,
        &stored_len.to_le_bytes(),
    );
    let total_dw = (stored_len as usize) / 4;
    let n_dw = buf.len() / 4;
    let n_rem = buf.len() % 4;
    for c in 0..n_dw {
        let idx = ((total_dw as u32)
            .wrapping_add(v)
            .wrapping_sub(c as u32)
            .wrapping_sub(1)) as usize
            & 0xFFF;
        v = CIPHER_TABLE[idx].wrapping_add(778_904_513);
        let w = &mut buf[c * 4..c * 4 + 4];
        let x = u32::from_le_bytes(w.try_into().unwrap()) ^ v;
        w.copy_from_slice(&x.to_le_bytes());
    }
    // The tail lane is keyed off the record's own remainder, so it only applies when
    // this call actually reached the last bytes.
    let tail = (stored_len as usize) % 4;
    if tail > 0 && buf.len() == stored_len as usize {
        let x = CIPHER_TABLE[tail] ^ v;
        for (k, b) in buf[n_dw * 4..].iter_mut().enumerate() {
            *b ^= (x >> (8 * k)) as u8;
        }
    } else if n_rem > 0 {
        let x = CIPHER_TABLE[n_rem] ^ v;
        for (k, b) in buf[n_dw * 4..].iter_mut().enumerate() {
            *b ^= (x >> (8 * k)) as u8;
        }
    }
}

/// `sub_14059F020` — two 32-bit lanes folded into one u64; ASCII-insensitive to case
/// and separator, so callers can look a resource up without knowing how it was written.
///
/// Both lanes are defined modulo 2^32 — the engine's own arithmetic wraps and the
/// shipped path table was built that way. Spelling the wrap out keeps a debug build
/// from panicking on overflow where a release build would silently wrap, which is the
/// difference between "the hash is right" and "the hash is right only when optimised".
pub fn path_hash(path: &str) -> u64 {
    let mut h1: u32 = 0x4E67_C6A7;
    let mut h2: u32 = 0;
    for mut c in path.bytes() {
        if c.is_ascii_uppercase() {
            c += 32;
        } else if c == b'\\' {
            c = b'/';
        }
        let v = (c as u32)
            .wrapping_add(h1.wrapping_mul(32))
            .wrapping_add(h1 >> 2);
        h1 ^= v;
        h2 = (c as u32).wrapping_add(65_599u32.wrapping_mul(h2));
    }
    h1 as u64 | ((h2 as u64) << 32)
}
