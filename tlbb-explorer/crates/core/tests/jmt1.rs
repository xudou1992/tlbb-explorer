//! JMT1 header/classification/block-decode tests.

use tlbb_core::jmt1::{classify, decode, Codec, MK_BC1, MK_BC3, MK_L8, MK_RGBA};

fn jmt1(tag: &str, marker: u32, w: u16, h: u16, mips: &[u32]) -> Vec<u8> {
    let mut v = Vec::new();
    v.extend_from_slice(b"JMT1");
    v.extend_from_slice(tag.as_bytes());
    v.extend_from_slice(&marker.to_le_bytes());
    let body: u32 = mips.iter().map(|n| n + 4).sum();
    v.extend_from_slice(&body.to_le_bytes());
    v.extend_from_slice(&w.to_le_bytes());
    v.extend_from_slice(&h.to_le_bytes());
    v.extend_from_slice(&(mips.len() as u32).to_le_bytes());
    for n in mips {
        v.extend_from_slice(&n.to_le_bytes());
        v.extend_from_slice(&vec![0u8; *n as usize]);
    }
    v
}

#[test]
fn classify_matches_the_shipped_decision_table() {
    // 8x8 → two-by-two block grid = 4 blocks.
    assert_eq!(classify("COLW", MK_RGBA, 999, 8, 8), Codec::Webp);
    assert_eq!(classify("COLR", 0x1907, (10 * 10 * 4) as u32 as usize, 8, 8), Codec::Rgba32Bordered);
    // ALI8 mip0 is w*h, which for 4-aligned sizes is identically the BC3 size.
    assert_eq!(classify("ALI8", MK_L8, 64, 8, 8), Codec::L8);
    assert_eq!(classify("DXT1", MK_L8, 4 * 16, 8, 8), Codec::L8);
    assert_eq!(classify("RGBA", MK_RGBA, 8 * 8 * 4, 8, 8), Codec::Rgba32);
    // The tag lies about block formats; the marker plus size decides.
    assert_eq!(classify("DXT1", MK_BC3, 4 * 16, 8, 8), Codec::Bc3);
    assert_eq!(classify("DXT1", MK_BC1, 4 * 8, 8, 8), Codec::Bc1);
    // A bogus `ALI8` whose size fits neither ramp nor block is refused, not guessed.
    assert_eq!(classify("ALI8", MK_BC1, 4 * 8, 8, 8), Codec::Unknown);
    assert_eq!(classify("DXT1", MK_BC1, 7, 8, 8), Codec::Unknown);
}

#[test]
fn l8_renders_as_grey() {
    let raw = jmt1("ALI8", MK_L8, 2, 2, &[4]);
    let body_at = raw.len() - 4;
    let mut raw = raw;
    raw[body_at..].copy_from_slice(&[0, 85, 170, 255]);
    let t = decode(&raw).unwrap();
    assert_eq!(t.codec, Codec::L8);
    assert_eq!(t.pixel(0, 0), [0, 0, 0, 255]);
    assert_eq!(t.pixel(1, 0), [85, 85, 85, 255]);
    assert_eq!(t.pixel(1, 1), [255, 255, 255, 255]);
}

#[test]
fn colr_border_is_cropped() {
    let (w, h) = (2u16, 2u16);
    let stride = (w as usize + 2) * 4;
    let mut px = vec![0u8; stride * (h as usize + 2)];
    // top-left real texel: stored blue-first (0,0,255) → RGBA (255,0,0)
    px[0..4].copy_from_slice(&[255, 0, 0, 255]);
    let raw = {
        let mut v = Vec::new();
        v.extend_from_slice(b"JMT1COLR");
        v.extend_from_slice(&0x1908u32.to_le_bytes());
        v.extend_from_slice(&(px.len() as u32 + 4).to_le_bytes());
        v.extend_from_slice(&w.to_le_bytes());
        v.extend_from_slice(&h.to_le_bytes());
        v.extend_from_slice(&1u32.to_le_bytes());
        v.extend_from_slice(&(px.len() as u32).to_le_bytes());
        v.extend_from_slice(&px);
        v
    };
    let t = decode(&raw).unwrap();
    assert_eq!(t.codec, Codec::Rgba32Bordered);
    assert_eq!(t.width, 2);
    assert_eq!(t.pixel(0, 0), [0, 0, 255, 255]);
    assert_eq!(t.rgba.len(), 2 * 2 * 4);
}

#[test]
fn colw_is_passed_through() {
    let raw = jmt1("COLW", 0x1908, 4, 4, &[3]);
    let t = decode(&raw).unwrap();
    assert_eq!(t.codec, Codec::Webp);
    assert_eq!(t.webp.as_deref(), Some(&[0u8, 0, 0][..]));
    assert!(t.rgba.is_empty());
}

/// Build a one-block BC1 texture whose four texels pick palette entries 0..3.
fn bc1_one_block(c0: u16, c1: u16, indices: u32) -> Vec<u8> {
    let mut blk = Vec::new();
    blk.extend_from_slice(&c0.to_le_bytes());
    blk.extend_from_slice(&c1.to_le_bytes());
    blk.extend_from_slice(&indices.to_le_bytes());
    assert_eq!(blk.len(), 8);
    let mut v = Vec::new();
    v.extend_from_slice(b"JMT1DXT1");
    v.extend_from_slice(&MK_BC1.to_le_bytes());
    v.extend_from_slice(&12u32.to_le_bytes());
    v.extend_from_slice(&2u16.to_le_bytes());
    v.extend_from_slice(&2u16.to_le_bytes());
    v.extend_from_slice(&1u32.to_le_bytes());
    v.extend_from_slice(&(blk.len() as u32).to_le_bytes());
    v.extend_from_slice(&blk);
    v
}

#[test]
fn bc1_four_colour_mode() {
    // A 2x2 texture samples k = 0, 1, 4, 5 of the 4x4 block, so the indices are
    // placed at those positions: 0=c0, 1=c1, 4=2/3 mix, 5=1/3 mix.
    let ci = (0b01 << 2) | (0b10 << 8) | (0b11 << 10);
    let t = decode(&bc1_one_block(0xF800, 0x001F, ci)).unwrap();
    assert_eq!(t.codec, Codec::Bc1);
    assert_eq!(t.pixel(0, 0), [255, 0, 0, 255]); // c0 = red
    assert_eq!(t.pixel(1, 0), [0, 0, 255, 255]); // c1 = blue
    let p2 = t.pixel(0, 1);
    let p3 = t.pixel(1, 1);
    assert!(p2[0] > p2[2] && p2[0] < 255, "2/3 red mix: {p2:?}");
    assert!(p3[2] > p3[0] && p3[2] < 255, "1/3 red mix: {p3:?}");
    assert_eq!((p2[0] as u32 + p3[0] as u32), 255 + 0); // symmetric around the midpoint
}

#[test]
fn bc1_three_colour_mode_has_transparent_entry() {
    // c0 <= c1 → palette entry 3 is transparent black; texel k=5 picks it.
    let t = decode(&bc1_one_block(0x001F, 0xF800, 0b11 << 10)).unwrap();
    assert_eq!(t.pixel(1, 1), [0, 0, 0, 0]);
    assert_eq!(t.pixel(0, 0), [0, 0, 255, 255]);
}

#[test]
fn bc3_alpha_ramp_is_indexed_three_bits() {
    // One BC3 block: alpha0=255, alpha1=0 (a0 > a1 → 8-entry ramp), all texels pick 0.
    let mut blk = vec![0u8; 16];
    blk[0] = 255;
    blk[1] = 0;
    blk[8..10].copy_from_slice(&0xF800u16.to_le_bytes()); // c0 = red
    blk[10..12].copy_from_slice(&0x001Fu16.to_le_bytes()); // c1 = blue
    let mut v = Vec::new();
    v.extend_from_slice(b"JMT1DXT1");
    v.extend_from_slice(&MK_BC3.to_le_bytes());
    v.extend_from_slice(&20u32.to_le_bytes());
    v.extend_from_slice(&2u16.to_le_bytes());
    v.extend_from_slice(&2u16.to_le_bytes());
    v.extend_from_slice(&1u32.to_le_bytes());
    v.extend_from_slice(&(blk.len() as u32).to_le_bytes());
    v.extend_from_slice(&blk);
    let t = decode(&v).unwrap();
    assert_eq!(t.codec, Codec::Bc3);
    for px in t.rgba.chunks(4) {
        assert_eq!(px[3], 255, "index 0 must pick alpha0");
        assert_eq!(px[0], 255);
    }
}

#[test]
fn rejects_garbage() {
    assert!(decode(b"nope").is_err());
    let mut raw = jmt1("RGBA", MK_RGBA, 4, 4, &[64]);
    raw[20..24].copy_from_slice(&99u32.to_le_bytes()); // absurd mip count
    assert!(decode(&raw).is_err());
    raw = jmt1("RGBA", MK_RGBA, 4, 4, &[64]);
    let n = raw.len();
    raw.truncate(n - 32); // chop the pixel data
    assert!(decode(&raw).is_err());
}
