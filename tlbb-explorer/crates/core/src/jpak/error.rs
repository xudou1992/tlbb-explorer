use std::fmt;

#[derive(Debug)]
pub enum Error {
    Io {
        context: String,
        source: std::io::Error,
    },
    BadMagic {
        found: [u8; 4],
    },
    Truncated {
        what: &'static str,
        need: u64,
        have: u64,
    },
    Checksum {
        what: &'static str,
        offset: u64,
        found: u32,
        expected: u32,
    },
    Chain {
        offset: u64,
        reason: String,
    },
    Record {
        offset: u64,
        reason: String,
    },
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Io { context, source } => write!(f, "{context}: {source}"),
            Error::BadMagic { found } => write!(f, "not a JPAK file (magic {:?})", found),
            Error::Truncated { what, need, have } => {
                write!(f, "{what} needs {need} bytes, file has {have}")
            }
            Error::Checksum {
                what,
                offset,
                found,
                expected,
            } => write!(
                f,
                "{what} checksum mismatch at {offset:#x}: got {found:#010x}, expected {expected:#010x}"
            ),
            Error::Chain { offset, reason } => write!(f, "index chain broken at {offset:#x}: {reason}"),
            Error::Record { offset, reason } => write!(f, "record at {offset:#x}: {reason}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<std::io::Error> for Error {
    fn from(source: std::io::Error) -> Self {
        Error::Io {
            context: "i/o error".into(),
            source,
        }
    }
}

pub type Result<T> = std::result::Result<T, Error>;
