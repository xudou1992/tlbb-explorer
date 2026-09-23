//! Golden vectors recovered from the shipped client / the Python reference implementation.

use tlbb_core::jpak::crypto::{crc32, crypt, path_hash};

#[test]
fn crc32_is_zlib_compatible() {
    assert_eq!(crc32(0, b"123456789"), 0xCBF4_3926);
    // Reseeding with a finished value must continue the same checksum, which is how
    // the engine derives keystream seeds and how callers stream large payloads.
    let (a, b) = (b"abcd".as_slice(), b"efgh".as_slice());
    assert_eq!(crc32(crc32(0, a), b), crc32(0, &[a, b].concat()));
}

#[test]
fn path_hash_matches_engine() {
    for (path, want) in [
        ("webview_x64/locales/hu.pak", 0x3a6d_0bae_1ae3_e6d1),
        ("webview_x64/locales/da.pak", 0x9344_1a9e_13ab_b963),
        ("webview_x64/locales/ca.pak", 0x7d17_b95f_3fca_0c16),
        ("webview_x64/locales/en-GB.pak", 0x6abe_2916_8665_8a37),
    ] {
        assert_eq!(path_hash(path), want, "hash of {path}");
        // Case and separator insensitive: callers pass whatever the scripts wrote.
        assert_eq!(path_hash(&path.replace('/', "\\")), want);
        assert_eq!(path_hash(&path.to_uppercase()), want);
    }
}

#[test]
fn keystream_matches_engine_decrypt() {
    let raw = hex(b"5e9eec88f025abaee017583b43236c5bae73ae385eefcc598799f4feff760bf46e6ee7467f33dd0bfa03dfd862d2a47982afa7aca2191562b021a6d4bee7dec73f");
    let want = hex(b"e401644a4d543144585431f0830000cc00000010001000050000008000fe0100ee0100090100208a830000081d24110c3cf0f0ffff0800000000000000fcffffff");
    let key = 0x29d8_6dc5_dd6e_7e8d_u64;
    let mut buf = raw.clone();
    crypt(key, 65, &mut buf);
    assert_eq!(buf, want, "decrypted body must start with the snappy varint then JMT1");
    crypt(key, 65, &mut buf);
    assert_eq!(buf, raw, "crypt is self-inverse");
}

fn hex(s: &[u8]) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(std::str::from_utf8(&s[i..i + 2]).unwrap(), 16).unwrap())
        .collect()
}
