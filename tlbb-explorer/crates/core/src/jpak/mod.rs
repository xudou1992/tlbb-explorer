//! Read-only JPAK container access.
//!
//! The layout below was recovered from `tlbbgl_x64.exe` (`PackageManager` =
//! `sub_1405A44F0`, writer = `sub_1405B3410`) and verified against all six shipped
//! paks with every CRC recomputed.

pub mod crypto;
pub mod error;
pub mod index;
pub mod reader;
pub mod verify;

pub use error::{Error, Result};
pub use index::{ArrayHeader, FileHeader, Record, RECORD_LEN};
pub use reader::Pak;
