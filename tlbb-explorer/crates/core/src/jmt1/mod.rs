//! `JMT1` textures.

pub mod decoder;

pub use decoder::{
    block_grid, classify, decode, mip_levels, Codec, Error, Meta, Texture,
    MK_BC1, MK_BC3, MK_L8, MK_RGBA, MK_WEBP_ALT, MAGIC,
};

/// True when a decoded payload starts with the `JMT1` magic — the catalog classifies by
/// content because shipped extensions lie (named textures are `.tga` but hold `JMT1`).
pub fn looks_like(data: &[u8]) -> bool {
    data.len() >= 28 && data[..4] == MAGIC
}
