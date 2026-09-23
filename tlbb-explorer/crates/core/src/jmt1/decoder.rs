//! `JMT1` texture container → RGBA.
//!
//! Layout: `[24B header]['JMT1', tag 4CC, u32 marker, u32 declared, u16 w, u16 h,
//! u32 mips]` then one `[u32 mip_size][mip data]` per level starting at offset 24.
//!
//! The 4CC tag lies: the engine ships BC3 payloads tagged `DXT1`, so the real codec is
//! derived from mip0's byte count against the block grid. Two tags are not block
//! textures at all: `COLW` is an embedded WebP bitstream describing a `(w+2)×(h+2)`
//! image, and `COLR` is raw RGBA with the same 1-pixel border.
//!
//! Block layouts follow the standard compressed-texture definitions: BC1 is
//! `[c0 u16][c1 u16][4KiB of 2-bit indices]`, BC3 is `[a0 a1][6B of 3-bit alpha
//! indices][c0 c1][2-bit indices]`. (`.scratch/explorer.py` reads BC1 colours from the
//! index field, which is a bug in that reference, not in the format.)

use std::fmt;

pub const MAGIC: [u8; 4] = *b"JMT1";
const HEADER_LEN: usize = 24;
/// Tolerance for trailing bytes past the declared mip chain.
const MIP_SLACK: usize = 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Codec {
    Bc1,
    Bc3,
    Rgba32,
    /// Single 8-bit channel (glyph and soft-part masks); rendered as grey.
    L8,
    /// RGBA stored `(w+2)×(h+2)`; the extra border is cropped.
    Rgba32Bordered,
    /// WebP bitstream, `(w+2)×(h+2)`; handed through undecoded.
    Webp,
    /// mip0 matches no known size class.
    Unknown,
}

impl Codec {
    pub fn extension(self) -> &'static str {
        match self {
            Codec::Webp => "webp",
            _ => "png",
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Codec::Bc1 => "BC1",
            Codec::Bc3 => "BC3",
            Codec::Rgba32 => "RGBA32",
            Codec::L8 => "L8",
            Codec::Rgba32Bordered => "RGBA32+border",
            Codec::Webp => "WEBP",
            Codec::Unknown => "unknown",
        }
    }
}

/// Sub-format key at offset 8. Unlike the 4CC this is honest, but it is not total:
/// `0x1908` covers both `RGBA` and `COLW`, so size or tag still has to break the tie.
pub const MK_BC1: u32 = 0x83F0;
pub const MK_BC3: u32 = 0x83F3;
pub const MK_L8: u32 = 0x1909;
pub const MK_RGBA: u32 = 0x1908;
pub const MK_WEBP_ALT: u32 = 0x1907;

/// Pick the real codec.
///
/// Measured over all 26,520 shipped textures, the ordering below is the only one that
/// works: `ALI8` mip0 is `w*h`, which for 4-aligned sizes is identically the BC3 block
/// count — so size alone cannot separate them, and five `COLW` blobs likewise land in
/// the BC3/BC1 size buckets. The tag is trusted only for `COLW`/`COLR`/`ALI8`; for the
/// block codecs it is known to lie (BC3 payloads ship tagged `DXT1`). The marker is
/// honest, so a marker/size agreement outranks a bare size match — that is what keeps a
/// 2×2 BC3 block (16 bytes) from being read as 2×2 RGBA (also 16 bytes).
pub fn classify(tag: &str, marker: u32, m0: usize, w: u16, h: u16) -> Codec {
    let px = w as usize * h as usize;
    let b0 = block_grid(w, h);
    if tag == "COLW" {
        return Codec::Webp;
    }
    if tag == "COLR" && m0 == (w as usize + 2) * (h as usize + 2) * 4 {
        return Codec::Rgba32Bordered;
    }
    if marker == MK_L8 || tag == "ALI8" {
        return if m0 == px { Codec::L8 } else { Codec::Unknown };
    }
    if (marker == MK_BC3 && m0 == b0 * 16) || (marker == MK_BC1 && m0 == b0 * 8) {
        return if marker == MK_BC3 { Codec::Bc3 } else { Codec::Bc1 };
    }
    if m0 == px * 4 {
        return Codec::Rgba32;
    }
    if m0 == b0 * 16 {
        Codec::Bc3
    } else if m0 == b0 * 8 {
        Codec::Bc1
    } else {
        Codec::Unknown
    }
}

#[derive(Debug)]
pub enum Error {
    NotJmt1,
    ImplausibleHeader { w: u16, h: u16, mips: u32 },
    TruncatedMipTable,
    MipOverrun { walked: usize, len: usize },
    UnknownMip0 { size: u32, expected: Vec<u32> },
    TruncatedMip0 { need: usize, have: usize },
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::NotJmt1 => write!(f, "not a JMT1 payload"),
            Error::ImplausibleHeader { w, h, mips } => {
                write!(f, "implausible header {w}x{h} x{mips} mips")
            }
            Error::TruncatedMipTable => write!(f, "truncated mip table"),
            Error::MipOverrun { walked, len } => {
                write!(f, "mip table overruns payload ({walked} > {len})")
            }
            Error::UnknownMip0 { size, expected } => {
                write!(f, "unrecognised mip0 size {size}, expected one of {expected:?}")
            }
            Error::TruncatedMip0 { need, have } => {
                write!(f, "truncated mip0: need {need}, have {have}")
            }
        }
    }
}

impl std::error::Error for Error {}

#[derive(Debug, Clone)]
pub struct Texture {
    pub width: u16,
    pub height: u16,
    pub mips: u32,
    /// Declared 4CC, kept for reporting — it lies for block textures.
    pub declared_tag: String,
    /// Sub-format key at +8.
    pub marker: u32,
    pub codec: Codec,
    /// RGBA8 row-major, `width*height*4`; empty for [`Codec::Webp`].
    pub rgba: Vec<u8>,
    /// Present only for [`Codec::Webp`].
    pub webp: Option<Vec<u8>>,
    pub mip_sizes: Vec<u32>,
}

impl Texture {
    pub fn pixel(&self, x: usize, y: usize) -> [u8; 4] {
        let o = (y * self.width as usize + x) * 4;
        self.rgba[o..o + 4].try_into().unwrap()
    }
}

/// Number of 4x4 blocks covering `w`×`h`.
pub fn block_grid(w: u16, h: u16) -> usize {
    ((w as usize + 3) / 4) * ((h as usize + 3) / 4)
}

/// Walk the mip table, returning each level's `(offset, len)`.
#[derive(Debug, Clone)]
pub struct Meta {
    pub width: u16,
    pub height: u16,
    pub mips: u32,
    pub tag: String,
    pub marker: u32,
    pub declared: u32,
    pub levels: Vec<(usize, usize)>,
}

pub fn mip_levels(raw: &[u8]) -> Result<Meta, Error> {
    if raw.len() < 28 || raw[..4] != MAGIC {
        return Err(Error::NotJmt1);
    }
    let width = u16::from_le_bytes([raw[16], raw[17]]);
    let height = u16::from_le_bytes([raw[18], raw[19]]);
    let mips = u32::from_le_bytes(raw[20..24].try_into().unwrap());
    if width == 0 || width > 8192 || height == 0 || height > 8192 || mips == 0 || mips > 16 {
        return Err(Error::ImplausibleHeader {
            w: width,
            h: height,
            mips,
        });
    }
    let tag = String::from_utf8_lossy(&raw[4..8]).into_owned();
    let mut p = HEADER_LEN;
    let mut levels = Vec::with_capacity(mips as usize);
    for _ in 0..mips {
        if p + 4 > raw.len() {
            return Err(Error::TruncatedMipTable);
        }
        let sz = u32::from_le_bytes(raw[p..p + 4].try_into().unwrap()) as usize;
        p += 4;
        levels.push((p, sz));
        p += sz;
    }
    if p.saturating_sub(raw.len()) > MIP_SLACK {
        return Err(Error::MipOverrun {
            walked: p,
            len: raw.len(),
        });
    }
    Ok(Meta {
        marker: u32::from_le_bytes(raw[8..12].try_into().unwrap()),
        declared: u32::from_le_bytes(raw[12..16].try_into().unwrap()),
        width,
        height,
        mips,
        tag,
        levels,
    })
}

pub fn decode(raw: &[u8]) -> Result<Texture, Error> {
    let meta = mip_levels(raw)?;
    let (width, height) = (meta.width, meta.height);
    let (m0_at, m0_len) = meta.levels[0];
    let base = Texture {
        width,
        height,
        mips: meta.mips,
        declared_tag: meta.tag.clone(),
        marker: meta.marker,
        codec: Codec::Unknown,
        rgba: Vec::new(),
        webp: None,
        mip_sizes: meta.levels.iter().map(|(_, n)| *n as u32).collect(),
    };
    let codec = classify(&meta.tag, meta.marker, m0_len, width, height);
    let slice = |at: usize, len: usize| -> Result<&[u8], Error> {
        raw.get(at..at + len).ok_or(Error::TruncatedMip0 {
            need: at + len,
            have: raw.len(),
        })
    };
    let px = width as usize * height as usize;
    let b0 = block_grid(width, height);
    match codec {
        Codec::Webp => Ok(Texture {
            webp: Some(slice(m0_at, m0_len)?.to_vec()),
            codec,
            ..base
        }),
        Codec::Rgba32Bordered => Ok(Texture {
            rgba: bgra_to_rgba(crop_bordered(slice(m0_at, m0_len)?, width, height)?),
            codec,
            ..base
        }),
        Codec::Rgba32 => Ok(Texture {
            rgba: bgra_to_rgba(slice(m0_at, px * 4)?.to_vec()),
            codec,
            ..base
        }),
        Codec::L8 => {
            let src = slice(m0_at, px)?;
            let mut rgba = Vec::with_capacity(px * 4);
            for v in src {
                rgba.extend_from_slice(&[*v, *v, *v, 255]);
            }
            Ok(Texture {
                rgba,
                codec,
                ..base
            })
        }
        Codec::Bc1 | Codec::Bc3 => {
            let block = if codec == Codec::Bc3 { 16 } else { 8 };
            Ok(Texture {
                rgba: decode_blocks(slice(m0_at, b0 * block)?, width, height, block),
                codec,
                ..base
            })
        }
        Codec::Unknown => Err(Error::UnknownMip0 {
            size: m0_len as u32,
            expected: vec![
                (px * 4) as u32,
                (px) as u32,
                (b0 * 16) as u32,
                (b0 * 8) as u32,
            ],
        }),
    }
}

/// The engine's 32-bit textures are stored blue-first; every consumer here speaks RGBA.
fn bgra_to_rgba(mut v: Vec<u8>) -> Vec<u8> {
    for px in v.chunks_exact_mut(4) {
        px.swap(0, 2);
    }
    v
}

/// Copy the top-left `w`×`h` of a `(w+2)×(h+2)` RGBA image.
fn crop_bordered(src: &[u8], w: u16, h: u16) -> Result<Vec<u8>, Error> {
    let stride = (w as usize + 2) * 4;
    let mut out = vec![0u8; w as usize * h as usize * 4];
    for y in 0..h as usize {
        let end = y * stride + w as usize * 4;
        if end > src.len() {
            return Err(Error::TruncatedMip0 {
                need: end,
                have: src.len(),
            });
        }
        let dst = y * w as usize * 4;
        out[dst..dst + w as usize * 4].copy_from_slice(&src[y * stride..end]);
    }
    Ok(out)
}

fn decode_blocks(data: &[u8], w: u16, h: u16, block: usize) -> Vec<u8> {
    let bw = (w as usize + 3) / 4;
    let bh = (h as usize + 3) / 4;
    let mut px = vec![0u8; w as usize * h as usize * 4];
    for by in 0..bh {
        for bx in 0..bw {
            let off = (by * bw + bx) * block;
            let Some(chunk) = data.get(off..off + block) else {
                continue;
            };
            let mut quad = [(0u8, 0u8, 0u8, 0u8); 16];
            decode_block(chunk, block, &mut quad);
            for (k, (r, g, b, a)) in quad.iter().enumerate() {
                let (x, y) = (bx * 4 + k % 4, by * 4 + k / 4);
                if x < w as usize && y < h as usize {
                    let o = (y * w as usize + x) * 4;
                    px[o..o + 4].copy_from_slice(&[*r, *g, *b, *a]);
                }
            }
        }
    }
    px
}

fn rgb565(v: u16) -> (u8, u8, u8) {
    let r = (v >> 11) as u32;
    let g = (v >> 5 & 0x3F) as u32;
    let b = (v & 0x1F) as u32;
    (
        ((r * 255 + 15) / 31) as u8,
        ((g * 255 + 31) / 63) as u8,
        ((b * 255 + 15) / 31) as u8,
    )
}

fn mix(a: (u8, u8, u8), b: (u8, u8, u8), aw: u32, bw: u32, div: u32) -> (u8, u8, u8) {
    (
        ((aw * a.0 as u32 + bw * b.0 as u32) / div) as u8,
        ((aw * a.1 as u32 + bw * b.1 as u32) / div) as u8,
        ((aw * a.2 as u32 + bw * b.2 as u32) / div) as u8,
    )
}

/// One 4x4 block, row-major inside the block. `block` is 8 (BC1) or 16 (BC3).
fn decode_block(b: &[u8], block: usize, out: &mut [(u8, u8, u8, u8); 16]) {
    if b.len() < block {
        return;
    }
    let bc3 = block == 16;
    // BC1: [c0 c1][4B indices]. BC3: [a0 a1][6B alpha indices][c0 c1][4B indices].
    let (c_at, ci_at) = if bc3 { (8usize, 12usize) } else { (0usize, 4usize) };
    let c0 = u16::from_le_bytes([b[c_at], b[c_at + 1]]);
    let c1 = u16::from_le_bytes([b[c_at + 2], b[c_at + 3]]);
    let (a, c) = (rgb565(c0), rgb565(c1));
    // BC1 picks the 3-colour mode (with a transparent entry) when c0 <= c1; BC3's
    // colour half always uses the 4-colour mode.
    let pal: [(u8, u8, u8, u8); 4] = if bc3 || c0 > c1 {
        [
            (a.0, a.1, a.2, 255),
            (c.0, c.1, c.2, 255),
            {
                let m = mix(a, c, 2, 1, 3);
                (m.0, m.1, m.2, 255)
            },
            {
                let m = mix(a, c, 1, 2, 3);
                (m.0, m.1, m.2, 255)
            },
        ]
    } else {
        [
            (a.0, a.1, a.2, 255),
            (c.0, c.1, c.2, 255),
            {
                let m = mix(a, c, 1, 1, 2);
                (m.0, m.1, m.2, 255)
            },
            (0, 0, 0, 0),
        ]
    };

    let ci = u32::from_le_bytes(b[ci_at..ci_at + 4].try_into().unwrap());
    let tab = if bc3 {
        Some(alpha_table(b[0], b[1]))
    } else {
        None
    };
    let ai_bits = if bc3 {
        let mut w = [0u8; 8];
        w[..6].copy_from_slice(&b[2..8]);
        u64::from_le_bytes(w)
    } else {
        0
    };
    for k in 0..16 {
        let mut px = pal[((ci >> (2 * k)) & 3) as usize];
        if let Some(t) = &tab {
            px.3 = t[((ai_bits >> (3 * k)) & 7) as usize];
        }
        out[k] = px;
    }
}

/// BC3/BC4 alpha ramp: 8 entries, indexed with 3 bits per texel.
fn alpha_table(a0: u8, a1: u8) -> [u8; 8] {
    let mut t = [0u8; 8];
    t[0] = a0;
    t[1] = a1;
    if a0 > a1 {
        for (i, slot) in t.iter_mut().enumerate().take(8).skip(2) {
            *slot = (((8 - i) as u32 * a0 as u32 + (i - 1) as u32 * a1 as u32) / 7) as u8;
        }
    } else {
        for (i, slot) in t.iter_mut().enumerate().take(6).skip(2) {
            *slot = (((6 - i) as u32 * a0 as u32 + (i - 1) as u32 * a1 as u32) / 5) as u8;
        }
        t[6] = 0;
        t[7] = 255;
    }
    t
}
