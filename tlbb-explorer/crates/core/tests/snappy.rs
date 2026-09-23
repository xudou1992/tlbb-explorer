//! Decoder-level Snappy tests pinned against hand-built streams, so a regression in the
//! copy1 offset split cannot hide behind the container vectors.

use tlbb_core::payload::snappy;

fn dec(b: &[u8]) -> Vec<u8> {
    snappy::decompress(b, None).unwrap_or_else(|e| panic!("decode failed: {e}"))
}

/// varint, little-endian, as the format preamble.
fn varint(mut n: usize) -> Vec<u8> {
    let mut out = Vec::new();
    loop {
        let byte = (n & 0x7F) as u8;
        n >>= 7;
        if n == 0 {
            out.push(byte);
            return out;
        }
        out.push(byte | 0x80);
    }
}

fn literal_tag(len: usize) -> u8 {
    ((len - 1) << 2) as u8
}

#[test]
fn short_literal() {
    assert_eq!(&dec(b"\x05\x10hello"), b"hello");
}

#[test]
fn long_literal_uses_two_extra_length_bytes() {
    // len_field 61 => two little-endian bytes hold length-1.
    let body: Vec<u8> = (0..300u16).map(|i| i as u8).collect();
    let mut src = varint(300);
    src.push((61 << 2) as u8);
    src.extend_from_slice(&299u16.to_le_bytes());
    src.extend_from_slice(&body);
    assert_eq!(dec(&src), body);
}

#[test]
fn copy1_offset_high_bits_come_from_the_tag() {
    // 300-byte literal, then copy1 length 4 at offset 300 (0x12C): the tag must carry
    // the upper three bits (1) and the following byte the low eight (0x2C).
    let prefix: Vec<u8> = (0..300u16).map(|i| i as u8).collect();
    let mut src = varint(304);
    src.push((61 << 2) as u8);
    src.extend_from_slice(&299u16.to_le_bytes());
    src.extend_from_slice(&prefix);
    src.push(0b001_000_01); // offset_hi=1, len-4=0, type=01
    src.push(0x2C); // offset_lo
    let out = dec(&src);
    assert_eq!(out.len(), 304);
    assert_eq!(&out[..300], &prefix[..]);
    assert_eq!(&out[300..], &prefix[..4]);
}

#[test]
fn overlapping_copy_repeats_just_written_bytes() {
    // "abcd" then copy1 len 4 offset 3 => the tail of the copy reads its own output.
    let src = [0x08, literal_tag(4), b'a', b'b', b'c', b'd', 0x01, 0x03];
    assert_eq!(&dec(&src), b"abcdbcdb");
}

#[test]
fn copy2_and_copy4_offsets() {
    let src2 = [0x06, literal_tag(3), b'a', b'b', b'c', 0x02 | (2 << 2), 0x03, 0x00];
    assert_eq!(&dec(&src2), b"abcabc");
    let src4 = [
        0x06,
        literal_tag(3),
        b'a',
        b'b',
        b'c',
        0x03 | (2 << 2),
        0x03,
        0x00,
        0x00,
        0x00,
    ];
    assert_eq!(&dec(&src4), b"abcabc");
}

#[test]
fn rejects_truncated_and_inconsistent_streams() {
    // Declared 10, literal wants 7, only 1 byte present.
    assert!(snappy::decompress(&[0x0A, literal_tag(7), b'a'], None).is_err());
    // Copy references further back than the output produced so far.
    assert!(snappy::decompress(&[0x01, literal_tag(1), b'a', 0x01, 0x05], None).is_err());
    // Stream yields 4 bytes but declares 3.
    assert!(snappy::decompress(&[0x03, literal_tag(4), b'a', b'b', b'c', b'd'], None).is_err());
    // Zero offset is not a valid back reference.
    assert!(snappy::decompress(&[0x04, literal_tag(3), b'a', b'b', b'c', 0x03, 0x00], None).is_err());
}

#[test]
fn declared_length_is_cross_checked_against_the_record() {
    let good = b"\x05\x10hello";
    assert!(snappy::decompress(good, Some(5)).is_ok());
    assert!(snappy::decompress(good, Some(6)).is_err());
}

#[test]
fn rle_run_of_one_byte() {
    // 'z' x4 then copy1 runs (length 4..11 only) to reach exactly 200 bytes.
    let mut src = varint(200);
    src.push(literal_tag(4));
    src.extend_from_slice(b"zzzz");
    let mut produced = 4usize;
    while produced < 200 {
        let n = (200 - produced).min(11).max(4);
        src.push(0x01 | (((n - 4) as u8) << 2));
        src.push(1);
        produced += n;
    }
    assert_eq!(produced, 200);
    assert_eq!(dec(&src), vec![b'z'; 200]);
}
