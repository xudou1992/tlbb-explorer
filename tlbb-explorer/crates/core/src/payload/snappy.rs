//! Raw (block-format) Snappy, decoder only — method `0x33` payloads are stored without
//! the framing chunk headers, and the engine's own reader is this same state machine.
//!
//! Written by hand on purpose: the format is ~120 lines, it keeps the dependency set
//! offline-buildable, and every branch is reachable from shipped data.

use crate::jpak::{Error, Result};

const TAG_LITERAL: u8 = 0b00;
const TAG_COPY1: u8 = 0b01;
const TAG_COPY2: u8 = 0b10;
const TAG_COPY4: u8 = 0b11;

/// Refuse to allocate beyond this; shipped entries top out near 40 MiB.
pub const MAX_RAW_LEN: usize = 512 * 1024 * 1024;

fn truncated(need: usize, have: usize) -> Error {
    Error::Record {
        offset: 0,
        reason: format!("snappy: needs {need} more bytes, {have} available"),
    }
}

fn need(n: usize, have: usize) -> Result<()> {
    if have >= n {
        Ok(())
    } else {
        Err(truncated(n, have))
    }
}

/// Decompress a raw Snappy block. `expected` is checked when supplied so a short or
/// long stream is reported as container corruption rather than silently accepted.
pub fn decompress(input: &[u8], expected: Option<u32>) -> Result<Vec<u8>> {
    let (declared, mut p) = read_varint(input)?;
    if declared as usize > MAX_RAW_LEN {
        return Err(Error::Record {
            offset: 0,
            reason: format!("snappy: declared length {declared} exceeds cap"),
        });
    }
    if let Some(want) = expected {
        if want != declared {
            return Err(Error::Record {
                offset: 0,
                reason: format!("snappy: header says {declared}, record says {want}"),
            });
        }
    }

    let mut out: Vec<u8> = Vec::with_capacity(declared as usize);

    while p < input.len() {
        let tag = input[p];
        p += 1;
        let len_field = tag >> 2;
        match tag & 0b11 {
            TAG_LITERAL => {
                let n = if len_field < 60 {
                    len_field as usize + 1
                } else {
                    let extra = len_field as usize - 59;
                    if extra > 4 {
                        return Err(Error::Record {
                            offset: 0,
                            reason: "snappy: bad literal length field".into(),
                        });
                    }
                    need(extra, input.len() - p)?;
                    let mut v = 0u64;
                    for i in 0..extra {
                        v |= (input[p + i] as u64) << (8 * i);
                    }
                    p += extra;
                    if v > 0xFFFF_FFFF {
                        return Err(Error::Record {
                            offset: 0,
                            reason: format!("snappy: literal length {v} too large"),
                        });
                    }
                    v as usize + 1
                };
                need(n, input.len() - p)?;
                out.extend_from_slice(&input[p..p + n]);
                p += n;
            }
            TAG_COPY1 => {
                // 11-bit offset split across the tag: bits 5..7 hold the high three,
                // the next byte holds the low eight. Length uses only bits 2..4.
                need(1, input.len() - p)?;
                let offset = ((tag >> 5) as usize) << 8 | input[p] as usize;
                let length = ((tag >> 2) as usize & 0b111) + 4;
                p += 1;
                copy(&mut out, offset, length)?;
            }
            TAG_COPY2 | TAG_COPY4 => {
                let (offset, width) = if tag & 0b11 == TAG_COPY2 {
                    need(2, input.len() - p)?;
                    (u16::from_le_bytes([input[p], input[p + 1]]) as usize, 2)
                } else {
                    need(4, input.len() - p)?;
                    (
                        u32::from_le_bytes(input[p..p + 4].try_into().unwrap()) as usize,
                        4,
                    )
                };
                let length = len_field as usize + 1;
                p += width;
                copy(&mut out, offset, length)?;
            }
            _ => unreachable!(),
        }
        if out.len() > declared as usize {
            return Err(Error::Record {
                offset: 0,
                reason: format!("snappy: overflowed declared length {}", declared),
            });
        }
    }

    if out.len() != declared as usize {
        return Err(Error::Record {
            offset: 0,
            reason: format!("snappy: produced {} of {} bytes", out.len(), declared),
        });
    }
    Ok(out)
}

/// Back-reference copy; overlapping sources are legal and must stream byte by byte.
fn copy(out: &mut Vec<u8>, offset: usize, length: usize) -> Result<()> {
    if offset == 0 || offset > out.len() {
        return Err(Error::Record {
            offset: 0,
            reason: format!("snappy: copy offset {offset} past output end {}", out.len()),
        });
    }
    let start = out.len() - offset;
    if offset >= length {
        let src_end = start + length;
        out.extend_from_within(start..src_end);
    } else {
        out.reserve(length);
        for i in 0..length {
            let b = out[start + i];
            out.push(b);
        }
    }
    Ok(())
}

fn read_varint(input: &[u8]) -> Result<(u32, usize)> {
    let mut value: u64 = 0;
    let mut shift = 0;
    let mut p = 0;
    loop {
        if p >= input.len() {
            return Err(truncated(1, input.len() - p));
        }
        let b = input[p];
        p += 1;
        value |= ((b & 0x7F) as u64) << shift;
        if b < 0x80 {
            if value > u64::from(u32::MAX) {
                return Err(Error::Record {
                    offset: 0,
                    reason: format!("snappy: varint {value} too large"),
                });
            }
            return Ok((value as u32, p));
        }
        shift += 7;
        if shift > 28 {
            return Err(Error::Record {
                offset: 0,
                reason: "snappy: varint longer than 5 bytes".into(),
            });
        }
    }
}

/// Only the declared length is needed to sanity-check an index entry.
pub fn declared_len(input: &[u8]) -> Result<u32> {
    read_varint(input).map(|(n, _)| n)
}
