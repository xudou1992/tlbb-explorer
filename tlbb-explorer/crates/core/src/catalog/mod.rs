//! Read-only view of the Python-built `resources.db` catalog.

pub mod evidence;
pub mod labels;
pub mod search;
pub mod sqlite;
pub mod versiondiff;

pub use evidence::{gaps, grade, Decode, EvidenceFacts, Grade, Signals};
pub use labels::{is_texture_name, kind_zh, role_zh, tag_zh};
pub use search::{matches, matches_asset, normalize, query_keys, tokens};
pub use sqlite::{
    Asset, Catalog, DanglingName, Fingerprints, Group, Identity, KindCount, Member, MemberDigest,
    RefExt, RefHealth, RelationCensus, Reference, Totals, UseEdge,
};
pub use versiondiff::{diff, Diff, Snapshot};
