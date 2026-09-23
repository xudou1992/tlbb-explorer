//! `JBCF` config containers and the dependency names they carry.

pub mod parser;

pub use parser::{
    parse, predicted_strtab, role, round8, Error, Jbcf, Role, Str, MAGIC, ROOT_ID,
    STRTABLE_ID,
};

/// The engine's own name for this container class, from the RTTI.
pub const CLASS: &str = "BinaryConfigFile";

impl Jbcf {
    /// Strings grouped by the role their extension implies. Control characters are
    /// rejected by the reader, so every entry here is a printable name.
    pub fn grouped(&self) -> Vec<(Role, Vec<&str>)> {
        let mut buckets: Vec<(Role, Vec<&str>)> = Vec::new();
        for s in &self.strings {
            let r = role(&s.text);
            if r == Role::Other {
                continue;
            }
            match buckets.iter_mut().find(|(k, _)| *k == r) {
                Some((_, v)) => v.push(s.text.as_str()),
                None => buckets.push((r, vec![s.text.as_str()])),
            }
        }
        buckets
    }

    /// All names that look like `r`, e.g. the textures a material references.
    pub fn names(&self, r: Role) -> Vec<&str> {
        self.strings
            .iter()
            .filter(|s| role(&s.text) == r)
            .map(|s| s.text.as_str())
            .collect()
    }
}
