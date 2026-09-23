//! Asset version comparison: two snapshots of the same library, one structured diff.
//!
//! Why this exists: the tool has to answer "did the art change?" after a client update,
//! and every cheaper signal answers a different question. `resources.db`'s own
//! `asset_fingerprint.fp_asset` digests the *stored* bytes, so re-packing a pak with a
//! different compressor setting moves it for every single asset — reporting that as
//! "content changed" would be a lie. The judgement table this project already settled on
//! (see `.scratch/identity.py`) is the rule implemented here:
//!
//!   压缩 / 重新打包     -> 不是内容变化（`ChangeKind::Repacked`）
//!   成员排序变化        -> 不是内容变化（成员按多重集比较，顺序无关）
//!   指纹变化而成员一致  -> 不是内容变化（`ChangeKind::FingerprintOnly`）
//!   名称口径变化        -> 单独标注（客户端不携带中文名，见 `NamesOnly` 的说明）
//!   只有贴图变了        -> `ChangeKind::TextureOnly`，与模型/材质变化分开
//!   成员增删 / 内容替换 -> `ChangeKind::Content`
//!
//! Fingerprints. `sqlite::Catalog` exposes only `fp_asset`, never the per-role columns
//! (`fp_model` … `fp_texture`), so a diff cannot be driven by them. Instead every
//! snapshot derives its own digests from the member list it carries: one aggregate, one
//! per role, one over the stored-byte CRCs and one over the pak locations. Those are
//! stability digests (FNV-1a 64, see [`digest`]), not collision-resistant identities —
//! all they must do is compare equal across two snapshots sharing a [`Snapshot::basis`].
//! The catalog's own `fp_asset` is carried verbatim in [`Fingerprints::observed`], so the
//! database's packing-sensitive signal stays visible without being read as content.
//!
//! Matching runs: unique `(目录, 主干)` → unique content fingerprint → member overlap.
//! The same cascade `.scratch/identity.py` uses, because two distinct assets can share a
//! fingerprint and many groups carry no name at all, so a non-unique key proves nothing
//! and is dropped rather than guessed at.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::catalog::labels::role_zh;
use crate::catalog::sqlite::{self, Catalog};

/// Native snapshot format version, carried in `格式`.
pub const FORMAT: u32 = 1;

/// What member `标识` means in a catalog-built snapshot: the resource hash.
pub const BASIS_RESOURCE: &str = "资源标识";
/// What it means in an `identity.py` v2 snapshot: SHA-256 of the decompressed payload.
pub const BASIS_PAYLOAD: &str = "内容标识";

/// A role this asset has no members of. Different from the empty string, which means
/// "this snapshot never computed that digest" and must never be compared.
pub const NONE: &str = "-";

/// How many added/removed/replaced files one change row lists before summarising.
const MAX_LISTED: usize = 20;

/// Members shared by more groups than this are too generic to identify anything.
const POSTING_CAP: usize = 64;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Error {
    /// The text was neither a native snapshot nor an `identity` v2 snapshot.
    Parse(String),
    /// The catalog could not be read.
    Catalog(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Parse(s) => write!(f, "快照解析失败: {s}"),
            Error::Catalog(s) => write!(f, "目录读取失败: {s}"),
        }
    }
}

impl std::error::Error for Error {}

impl From<sqlite::Error> for Error {
    fn from(e: sqlite::Error) -> Self {
        Error::Catalog(e.to_string())
    }
}

pub type Result<T> = std::result::Result<T, Error>;

/// Order-free, length-prefixed digest of a multiset of strings.
pub fn digest(items: &[String]) -> String {
    let mut sorted: Vec<&str> = items.iter().map(|s| s.as_str()).collect();
    sorted.sort_unstable();
    let mut buf = String::new();
    buf.push_str("n=");
    buf.push_str(&sorted.len().to_string());
    buf.push('\u{1f}');
    for s in sorted {
        buf.push_str(s);
        buf.push('\u{1f}');
    }
    format!("{:016x}", fnv1a(buf.as_bytes()))
}

fn fnv1a(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in bytes {
        h ^= *b as u64;
        h = h.wrapping_mul(0x1000_0000_01b3);
    }
    h
}

fn leaf_lower(p: &str) -> String {
    p.rsplit(['/', '\\']).next().unwrap_or(p).to_lowercase()
}

fn role_norm(r: &str) -> String {
    let r = r.trim().to_lowercase();
    if r.is_empty() {
        "other".to_string()
    } else {
        r
    }
}

/// One file inside one asset group.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Member {
    /// `model` / `mesh` / `material` / `animation` / `skeleton` / `texture` / ...
    #[serde(rename = "角色")]
    pub role: String,
    /// Content identity, in whatever vocabulary [`Snapshot::basis`] declares. Empty means
    /// the payload was never located.
    #[serde(rename = "标识")]
    pub ident: String,
    /// Shipped file name; only used to say "this file changed" instead of "one file left
    /// and a different one arrived".
    #[serde(rename = "名称", default, skip_serializing_if = "String::is_empty")]
    pub name: String,
    /// CRC of the stored (compressed) bytes — a packing signal, never a content one.
    #[serde(rename = "包内CRC", default, skip_serializing_if = "String::is_empty")]
    pub crc: String,
    /// `pak@offset/ver`: where the payload sits, which moves on any re-pack.
    #[serde(rename = "位置", default, skip_serializing_if = "String::is_empty")]
    pub loc: String,
}

impl Member {
    /// Identity key: the file name when known, otherwise the content identity.
    fn key(&self, role: &str) -> String {
        let what = if self.name.is_empty() { &self.ident } else { &self.name };
        format!("{role}\u{1}{what}")
    }
}

/// The digests a verdict rests on. Empty means "not computed in this snapshot".
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct Fingerprints {
    #[serde(rename = "整体", default)]
    pub asset: String,
    #[serde(rename = "模型", default)]
    pub model: String,
    #[serde(rename = "骨骼", default)]
    pub skeleton: String,
    #[serde(rename = "网格", default)]
    pub mesh: String,
    #[serde(rename = "材质", default)]
    pub material: String,
    #[serde(rename = "动作", default)]
    pub animation: String,
    #[serde(rename = "贴图", default)]
    pub texture: String,
    /// Any other role present, keyed by the raw role token.
    #[serde(rename = "其他角色", default, skip_serializing_if = "BTreeMap::is_empty")]
    pub others: BTreeMap<String, String>,
    #[serde(rename = "名称", default)]
    pub names: String,
    /// Multiset of stored-byte CRCs: moves when the asset was re-packed.
    #[serde(rename = "包内字节", default)]
    pub pack: String,
    /// Multiset of pak locations: moves when payloads moved on disk.
    #[serde(rename = "位置", default)]
    pub loc: String,
    /// `asset_fingerprint.fp_asset` as the catalog stores it, kept verbatim.
    #[serde(rename = "库内指纹", default, skip_serializing_if = "String::is_empty")]
    pub observed: String,
    /// Foreign digests the source carried (`id_content`, `id_pack`, ...), kept for
    /// traceability and never compared.
    #[serde(rename = "外部指纹", default, skip_serializing_if = "BTreeMap::is_empty")]
    pub foreign: BTreeMap<String, String>,
}

impl Fingerprints {
    /// Derive every local digest from members and referenced names.
    pub fn derive(members: &[Member], names: &[String]) -> Self {
        let mut fp = Fingerprints::default();
        let mut by_role: BTreeMap<String, Vec<String>> = BTreeMap::new();
        let mut all: Vec<String> = Vec::with_capacity(members.len());
        let mut pack: Vec<String> = Vec::new();
        let mut loc: Vec<String> = Vec::new();
        for m in members {
            let role = role_norm(&m.role);
            all.push(format!("{role}\u{1}{}", m.ident));
            if !m.ident.is_empty() {
                by_role.entry(role.clone()).or_default().push(m.ident.clone());
            }
            if !m.crc.is_empty() {
                pack.push(format!("{role}\u{1}{}", m.crc));
            }
            if !m.loc.is_empty() {
                loc.push(format!("{role}\u{1}{}\u{1}{}", m.ident, m.loc));
            }
        }
        fp.model = take_role(&mut by_role, "model");
        fp.skeleton = take_role(&mut by_role, "skeleton");
        fp.mesh = take_role(&mut by_role, "mesh");
        fp.material = take_role(&mut by_role, "material");
        fp.animation = take_role(&mut by_role, "animation");
        fp.texture = take_role(&mut by_role, "texture");
        for (role, idents) in by_role {
            fp.others.insert(role, digest(&idents));
        }
        fp.asset = digest(&all);
        let lowered: Vec<String> = names.iter().map(|n| n.to_lowercase()).collect();
        fp.names = if lowered.is_empty() { NONE.to_string() } else { digest(&lowered) };
        fp.pack = if pack.is_empty() { String::new() } else { digest(&pack) };
        fp.loc = if loc.is_empty() { String::new() } else { digest(&loc) };
        fp
    }

    /// Digest of one role's content, `None` when this snapshot computed nothing.
    pub fn role(&self, role: &str) -> Option<&str> {
        if self.asset.is_empty() {
            return None;
        }
        let v = match role {
            "model" => &self.model,
            "skeleton" => &self.skeleton,
            "mesh" => &self.mesh,
            "material" => &self.material,
            "animation" => &self.animation,
            "texture" => &self.texture,
            r => self.others.get(r)?,
        };
        Some(v.as_str())
    }

    /// Roles whose digest moved, as `(角色, 前, 后)`. Excludes the aggregate, the name
    /// digest and the packing digests: those answer different questions.
    pub fn moved_roles(&self, other: &Fingerprints) -> Vec<(String, String, String)> {
        let mut out = Vec::new();
        if self.asset.is_empty() || other.asset.is_empty() {
            return out;
        }
        for role in ["model", "skeleton", "mesh", "material", "animation", "texture"] {
            push_move(&mut out, role, self.role(role), other.role(role));
        }
        let mut roles: Vec<&String> = self.others.keys().chain(other.others.keys()).collect();
        roles.sort_unstable();
        roles.dedup();
        for role in roles {
            push_move(
                &mut out,
                role,
                self.others.get(role).map(|s| s.as_str()),
                other.others.get(role).map(|s| s.as_str()),
            );
        }
        out
    }

    fn moved(&self, other: &Fingerprints, pick: fn(&Fingerprints) -> &str) -> bool {
        let (a, b) = (pick(self), pick(other));
        !a.is_empty() && !b.is_empty() && a != b
    }

    pub fn asset_moved(&self, other: &Fingerprints) -> bool {
        self.moved(other, |f| &f.asset)
    }

    pub fn pack_moved(&self, other: &Fingerprints) -> bool {
        self.moved(other, |f| &f.pack)
    }

    pub fn loc_moved(&self, other: &Fingerprints) -> bool {
        self.moved(other, |f| &f.loc)
    }

    pub fn names_moved(&self, other: &Fingerprints) -> bool {
        self.moved(other, |f| &f.names)
    }

    /// The catalog's own `fp_asset`, which folds in the stored bytes, moved.
    pub fn observed_moved(&self, other: &Fingerprints) -> bool {
        self.moved(other, |f| &f.observed)
    }
}

fn push_move(out: &mut Vec<(String, String, String)>, role: &str, a: Option<&str>, b: Option<&str>) {
    if let (Some(a), Some(b)) = (a.filter(|s| !s.is_empty()), b.filter(|s| !s.is_empty())) {
        if a != b {
            out.push((role.to_string(), a.to_string(), b.to_string()));
        }
    }
}

fn take_role(map: &mut BTreeMap<String, Vec<String>>, role: &str) -> String {
    match map.remove(role) {
        Some(v) => digest(&v),
        None => NONE.to_string(),
    }
}

/// One asset group as one version saw it.
#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct SnapAsset {
    #[serde(rename = "组")]
    pub gid: i64,
    #[serde(rename = "主干")]
    pub stem: String,
    #[serde(rename = "类型")]
    pub kind: String,
    #[serde(rename = "目录")]
    pub dir: String,
    #[serde(rename = "主文件")]
    pub hub: String,
    #[serde(rename = "成员数")]
    pub n_members: usize,
    #[serde(rename = "名称数")]
    pub n_names: usize,
    /// Members per role; comparable across snapshots even without member detail.
    #[serde(rename = "组成", default)]
    pub roles: BTreeMap<String, usize>,
    #[serde(rename = "成员", default, skip_serializing_if = "Vec::is_empty")]
    pub members: Vec<Member>,
    /// Names the asset references whose payload this install does not hold.
    #[serde(rename = "引用名称", default, skip_serializing_if = "Vec::is_empty")]
    pub names: Vec<String>,
    #[serde(rename = "指纹", default)]
    pub fp: Fingerprints,
}

impl SnapAsset {
    /// Recompute counts and digests from the carried members. Idempotent, and a no-op on
    /// a composition-only asset, which has no member detail to derive from.
    pub fn refresh(&mut self) {
        if self.members.is_empty() {
            return;
        }
        self.n_members = self.members.len();
        self.n_names = self.names.len();
        let mut roles: BTreeMap<String, usize> = BTreeMap::new();
        for m in &self.members {
            *roles.entry(role_norm(&m.role)).or_insert(0) += 1;
        }
        self.roles = roles;
        // `observed` and `foreign` are carried observations, never derivations: they
        // survive a refresh so a re-read snapshot still equals the one it came from.
        let mut fp = Fingerprints::derive(&self.members, &self.names);
        fp.observed = std::mem::take(&mut self.fp.observed);
        fp.foreign = std::mem::take(&mut self.fp.foreign);
        self.fp = fp;
    }

    fn path_key(&self) -> (String, String) {
        (self.dir.clone(), self.stem.clone())
    }

    /// Shape signature: kind, member count and the per-role counts. An unnamed group has
    /// no usable path key, and a composition-only snapshot has no fingerprints at all, so
    /// for those rows this is the only key that exists.
    fn shape_key(&self) -> String {
        let mut parts: Vec<String> =
            self.roles.iter().map(|(r, n)| format!("{r}:{n}")).collect();
        parts.sort();
        parts.push(format!("{}:{}:{}", self.kind, self.n_members, self.dir));
        parts.join("\u{1}")
    }

    /// The coarse half of [`Self::shape_key`]: kind, member count and directory only. A
    /// composition-only snapshot never saw the per-role split, so this is the widest key
    /// two differently built snapshots can still agree on.
    fn rough_key(&self) -> String {
        format!("{}\u{1}{}\u{1}{}", self.kind, self.n_members, self.dir)
    }

    /// `(角色, 标识)` pairs — the content ground truth when detail is present.
    fn content_set(&self) -> Vec<(String, String)> {
        self.members
            .iter()
            .map(|m| (role_norm(&m.role), m.ident.clone()))
            .collect()
    }

    /// Keyed view used to tell "replaced" from "one left, another arrived".
    fn keyed(&self) -> HashMap<String, (String, String)> {
        let mut out = HashMap::with_capacity(self.members.len());
        for m in &self.members {
            let role = role_norm(&m.role);
            out.insert(m.key(&role), (role, m.ident.clone()));
        }
        out
    }

    pub fn display_name(&self) -> &str {
        if !self.stem.is_empty() {
            return &self.stem;
        }
        let leaf = self.hub.rsplit(['/', '\\']).next().unwrap_or("");
        if leaf.is_empty() {
            "(未命名资产)"
        } else {
            leaf
        }
    }
}

/// One point in time of the asset library.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Snapshot {
    #[serde(rename = "格式")]
    pub format: u32,
    /// Where it came from: a database path, a JSON path, ...
    #[serde(rename = "来源", default)]
    pub source: String,
    /// What a member `标识` means here. Two snapshots may only be compared for content
    /// when this matches; see [`BASIS_RESOURCE`] and [`BASIS_PAYLOAD`].
    #[serde(rename = "标识口径", default)]
    pub basis: String,
    #[serde(rename = "资产")]
    pub assets: Vec<SnapAsset>,
}

impl Snapshot {
    /// The catalog's current state: every group with its members and referenced names.
    ///
    /// Members and names come per group because that is what the public `Catalog` API
    /// offers, so this is N+1 by construction — still cheap: the real library's 8,537
    /// groups and 38,781 members read in a fraction of a second.
    pub fn from_db(cat: &Catalog) -> Result<Snapshot> {
        Snapshot::from_db_opts(cat, true)
    }

    /// Groups and composition counts only, no member detail. Still answers 新增/删除 and
    /// 组成数量变化, and stays light enough for a first pass over the library.
    pub fn from_db_composition_only(cat: &Catalog) -> Result<Snapshot> {
        Snapshot::from_db_opts(cat, false)
    }

    pub fn from_db_opts(cat: &Catalog, with_members: bool) -> Result<Snapshot> {
        let mut assets = Vec::new();
        for g in cat.groups(i64::MAX as usize / 4)? {
            let mut a = SnapAsset {
                gid: g.id,
                stem: g.stem.clone(),
                kind: g.kind.clone(),
                dir: g.dir.clone(),
                hub: g.hub_path.clone(),
                ..Default::default()
            };
            if with_members {
                for m in cat.members(g.id)? {
                    a.members.push(Member {
                        role: role_norm(&m.role),
                        ident: format!("{:016x}", m.hash),
                        name: m.path.map(|p| leaf_lower(&p)).unwrap_or_default(),
                        crc: String::new(),
                        loc: format!("{}@{}/{}", m.pak, m.offset, m.ver),
                    });
                }
                a.names = cat
                    .group_names(g.id)?
                    .into_iter()
                    .map(|(n, _)| leaf_lower(&n))
                    .collect();
                a.refresh();
            } else {
                // The group table counts mesh/mtl/ani/ske/tex. Whatever is left is either
                // the body model or an unclassified file and cannot be split from here, so
                // it lands in one aggregated bucket.
                let mut roles: BTreeMap<String, usize> = BTreeMap::new();
                for (role, n) in [
                    ("mesh", g.n_mesh),
                    ("material", g.n_mtl),
                    ("animation", g.n_ani),
                    ("skeleton", g.n_ske),
                    ("texture", g.n_tex),
                ] {
                    if n > 0 {
                        roles.insert(role.to_string(), n as usize);
                    }
                }
                let known: i64 = roles.values().map(|v| *v as i64).sum();
                let rest = (g.n - known).max(0) as usize;
                if rest > 0 {
                    roles.insert("model_or_other".to_string(), rest);
                }
                a.n_members = g.n.max(0) as usize;
                a.roles = roles;
            }
            assets.push(a);
        }
        assets.sort_by_key(|a| a.gid);
        Ok(Snapshot {
            format: FORMAT,
            source: "resources.db".to_string(),
            basis: BASIS_RESOURCE.to_string(),
            assets,
        })
    }

    /// Attach `asset_fingerprint.fp_asset` as [`Fingerprints::observed`]. Optional because
    /// it costs one query per group; without it the diff is complete, it just cannot show
    /// the database's own packing-sensitive fingerprint moving.
    pub fn with_observed_fingerprints(&mut self, cat: &Catalog) -> Result<()> {
        for a in &mut self.assets {
            if let Some(fp) = cat.fingerprint(a.gid)? {
                a.fp.observed = fp;
            }
        }
        Ok(())
    }

    /// Parse a snapshot: this module's own format, or the `identity.py` v2 dump that
    /// `.scratch/versions/示例_下一版.json` ships — there the member `sha` becomes `标识`
    /// and `crc` becomes `包内CRC`, while its own `id_*` digests are parked in
    /// [`Fingerprints::foreign`] instead of being compared.
    pub fn from_json(text: &str) -> Result<Snapshot> {
        match serde_json::from_str::<Snapshot>(text) {
            Ok(mut s) => {
                s.finish_loaded();
                Ok(s)
            }
            Err(native) => match serde_json::from_str::<RawV2>(text) {
                Ok(raw) => Ok(raw.into_snapshot()),
                Err(v2) => Err(Error::Parse(format!(
                    "既不是原生快照（{native}），也不是 identity v2 快照（{v2}）"
                ))),
            },
        }
    }

    pub fn from_json_file(path: impl AsRef<Path>) -> Result<Snapshot> {
        let p = path.as_ref();
        let text =
            std::fs::read_to_string(p).map_err(|e| Error::Parse(format!("{}: {e}", p.display())))?;
        let name = p.file_name().map(|s| s.to_string_lossy().into_owned()).unwrap_or_default();
        let mut s = Snapshot::from_json(&text)?;
        if s.source.is_empty() {
            s.source = name;
        }
        Ok(s)
    }

    /// Compact JSON in the native format: store this as the next version's snapshot.
    pub fn to_json(&self) -> String {
        serde_json::to_string(self).expect("a snapshot always serializes")
    }

    fn finish_loaded(&mut self) {
        if self.basis.is_empty() {
            self.basis = BASIS_RESOURCE.to_string();
        }
        for a in &mut self.assets {
            a.refresh();
        }
        self.assets.sort_by_key(|a| a.gid);
    }

    /// Whether some asset carries member detail, i.e. whether content can be judged file
    /// by file rather than by digests alone.
    pub fn has_member_detail(&self) -> bool {
        self.assets.iter().any(|a| !a.members.is_empty())
    }

    pub fn len(&self) -> usize {
        self.assets.len()
    }

    pub fn is_empty(&self) -> bool {
        self.assets.is_empty()
    }

    pub fn total_members(&self) -> usize {
        self.assets.iter().map(|a| a.members.len()).sum()
    }
}

// --------------------------------------------------------------------------- v2 import

#[derive(Deserialize)]
struct RawV2 {
    #[serde(default)]
    #[allow(dead_code)]
    version: u32,
    #[serde(default)]
    built_from: String,
    assets: Vec<RawAssetV2>,
}

#[derive(Deserialize)]
struct RawAssetV2 {
    #[serde(default)]
    gid: i64,
    #[serde(default)]
    stem: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    dir: String,
    #[serde(default)]
    hub_path: String,
    #[serde(default)]
    members: Vec<RawMemberV2>,
    #[serde(default)]
    names: Vec<String>,
    #[serde(default)]
    id_asset: Option<String>,
    #[serde(default)]
    id_content: Option<String>,
    #[serde(default)]
    id_pack: Option<String>,
    #[serde(default)]
    id_struct: Option<String>,
    #[serde(default)]
    id_names: Option<String>,
}

#[derive(Deserialize)]
struct RawMemberV2 {
    #[serde(default)]
    role: String,
    #[serde(default)]
    name: String,
    #[serde(default)]
    sha: String,
    #[serde(default)]
    crc: String,
}

impl RawV2 {
    fn into_snapshot(self) -> Snapshot {
        let mut assets = Vec::with_capacity(self.assets.len());
        for a in self.assets {
            let mut s = SnapAsset {
                gid: a.gid,
                stem: a.stem,
                kind: a.kind,
                dir: a.dir,
                hub: a.hub_path,
                members: a
                    .members
                    .into_iter()
                    .map(|m| Member {
                        role: role_norm(&m.role),
                        ident: m.sha,
                        name: leaf_lower(&m.name),
                        crc: m.crc,
                        loc: String::new(),
                    })
                    .collect(),
                names: a.names.into_iter().map(|n| n.to_lowercase()).collect(),
                ..Default::default()
            };
            s.refresh();
            for (k, v) in [
                ("id_asset", a.id_asset),
                ("id_content", a.id_content),
                ("id_pack", a.id_pack),
                ("id_struct", a.id_struct),
                ("id_names", a.id_names),
            ] {
                if let Some(v) = v {
                    s.fp.foreign.insert(k.to_string(), v);
                }
            }
            assets.push(s);
        }
        assets.sort_by_key(|a| a.gid);
        Snapshot {
            format: FORMAT,
            source: if self.built_from.is_empty() {
                "identity v2".to_string()
            } else {
                self.built_from
            },
            basis: BASIS_PAYLOAD.to_string(),
            assets,
        }
    }
}

// --------------------------------------------------------------------------------- diff

/// What moved. Loudness runs from "the library gained or lost something" down to "none".
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum ChangeKind {
    #[serde(rename = "新增资产")]
    Added,
    #[serde(rename = "删除资产")]
    Removed,
    #[serde(rename = "内容变化")]
    Content,
    #[serde(rename = "组成数量变化")]
    Composition,
    #[serde(rename = "仅贴图变化")]
    TextureOnly,
    #[serde(rename = "仅名称变化")]
    NamesOnly,
    #[serde(rename = "仅重新打包")]
    Repacked,
    #[serde(rename = "仅路径变化")]
    Renamed,
    #[serde(rename = "仅指纹变化")]
    FingerprintOnly,
    #[serde(rename = "未变")]
    Unchanged,
}

impl ChangeKind {
    /// How to read the label, and above all what it is *not*.
    pub fn note(self) -> &'static str {
        match self {
            ChangeKind::Added => "该版本出现了此前没有的资产",
            ChangeKind::Removed => "该版本不再出现此前的资产",
            ChangeKind::Content => "成员文件本身变了：增删成员，或同名文件内容被替换",
            ChangeKind::Composition => "各角色成员数量变化，例如多了一组动作",
            ChangeKind::TextureOnly => "只有贴图/表现层文件变了，模型与材质未动",
            ChangeKind::NamesOnly => "只有引用名称清单变了；客户端不携带中文名，这通常是采集口径变化而非美术改动",
            ChangeKind::Repacked => "内容一致，只有压缩结果或在包内的位置变了，不算内容变化",
            ChangeKind::Renamed => "内容一致，只有目录或主干名变了",
            ChangeKind::FingerprintOnly => "成员一致而指纹不同（重排、摘要口径或采集差异），不算内容变化",
            ChangeKind::Unchanged => "完全一致",
        }
    }

    /// Report order: the loudest label on a row wins.
    pub fn rank(self) -> u8 {
        match self {
            ChangeKind::Added => 0,
            ChangeKind::Removed => 1,
            ChangeKind::Content => 2,
            ChangeKind::Composition => 3,
            ChangeKind::TextureOnly => 4,
            ChangeKind::Repacked => 5,
            ChangeKind::NamesOnly => 6,
            ChangeKind::Renamed => 7,
            ChangeKind::FingerprintOnly => 8,
            ChangeKind::Unchanged => 9,
        }
    }
}

/// How a matched pair was recognised as the same asset. This is the contract's
/// `差异项.匹配方式` vocabulary, and it is also the honest answer to "on what evidence did
/// you dare to call these two rows one asset" — a pair whose basis is `成员重叠` or
/// `身份证` moved on disk, so it must not be reported as a deletion plus an arrival.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub enum MatchBasis {
    /// Same `(目录, 主干)`.
    #[serde(rename = "路径")]
    Path,
    /// Same content digest, and that digest occurred exactly once on the far side.
    #[serde(rename = "身份证")]
    Fingerprint,
    /// Enough of the same member files to be one asset that moved.
    #[serde(rename = "成员重叠")]
    MemberOverlap,
    /// Nothing to match against: the asset is new.
    #[serde(rename = "新增")]
    Added,
}

/// One asset that moved, with the evidence behind the verdict.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct AssetChange {
    #[serde(rename = "名称")]
    pub name: String,
    #[serde(rename = "类型")]
    pub kind: String,
    #[serde(rename = "主判定")]
    pub headline: ChangeKind,
    /// 匹配方式 — how this row's two sides were recognised as one asset. `None` when there
    /// is no far side at all, i.e. the asset disappeared. See [`MatchBasis`].
    #[serde(rename = "匹配方式", skip_serializing_if = "Option::is_none")]
    pub matched_by: Option<MatchBasis>,
    #[serde(rename = "前目录")]
    pub before_dir: String,
    #[serde(rename = "后目录")]
    pub after_dir: String,
    #[serde(rename = "变化")]
    pub changes: Vec<ChangeKind>,
    #[serde(rename = "说明")]
    pub notes: Vec<String>,
    #[serde(rename = "前成员数")]
    pub before_members: usize,
    #[serde(rename = "后成员数")]
    pub after_members: usize,
    #[serde(rename = "新增成员", skip_serializing_if = "Vec::is_empty")]
    pub added_members: Vec<String>,
    #[serde(rename = "删除成员", skip_serializing_if = "Vec::is_empty")]
    pub removed_members: Vec<String>,
    #[serde(rename = "替换成员", skip_serializing_if = "Vec::is_empty")]
    pub replaced_members: Vec<String>,
    #[serde(rename = "组成变化", skip_serializing_if = "Vec::is_empty")]
    pub role_moves: Vec<RoleMove>,
    #[serde(rename = "指纹变化", skip_serializing_if = "Vec::is_empty")]
    pub fingerprint_moves: Vec<(String, String, String)>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RoleMove {
    #[serde(rename = "角色")]
    pub role: String,
    #[serde(rename = "前")]
    pub before: usize,
    #[serde(rename = "后")]
    pub after: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Default, Serialize)]
pub struct Summary {
    #[serde(rename = "前资产数")]
    pub before_assets: usize,
    #[serde(rename = "后资产数")]
    pub after_assets: usize,
    #[serde(rename = "配对数")]
    pub paired: usize,
    #[serde(rename = "未变")]
    pub unchanged: usize,
    #[serde(rename = "新增资产")]
    pub added: usize,
    #[serde(rename = "删除资产")]
    pub removed: usize,
    #[serde(rename = "内容变化")]
    pub content: usize,
    #[serde(rename = "组成数量变化")]
    pub composition: usize,
    #[serde(rename = "仅贴图变化")]
    pub texture_only: usize,
    #[serde(rename = "仅名称变化")]
    pub names_only: usize,
    #[serde(rename = "仅重新打包")]
    pub repacked: usize,
    #[serde(rename = "仅路径变化")]
    pub renamed: usize,
    #[serde(rename = "仅指纹变化")]
    pub fingerprint_only: usize,
    /// Paired assets whose content could not be judged: the two snapshots speak different
    /// identification vocabularies.
    #[serde(rename = "内容未判定")]
    pub content_unjudged: usize,
}

impl Summary {
    fn bump(&mut self, k: ChangeKind) {
        match k {
            ChangeKind::Added => self.added += 1,
            ChangeKind::Removed => self.removed += 1,
            ChangeKind::Content => self.content += 1,
            ChangeKind::Composition => self.composition += 1,
            ChangeKind::TextureOnly => self.texture_only += 1,
            ChangeKind::NamesOnly => self.names_only += 1,
            ChangeKind::Repacked => self.repacked += 1,
            ChangeKind::Renamed => self.renamed += 1,
            ChangeKind::FingerprintOnly => self.fingerprint_only += 1,
            ChangeKind::Unchanged => self.unchanged += 1,
        }
    }
}

/// The whole comparison: `变化` lists only assets that moved, `未变` counts the rest.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Diff {
    #[serde(rename = "前快照")]
    pub before: String,
    #[serde(rename = "后快照")]
    pub after: String,
    #[serde(rename = "前口径")]
    pub before_basis: String,
    #[serde(rename = "后口径")]
    pub after_basis: String,
    /// False when member identities mean different things on the two sides; stated up front
    /// instead of being reported as thousands of changes.
    #[serde(rename = "口径可比")]
    pub comparable: bool,
    #[serde(rename = "判定范围")]
    pub scope: String,
    #[serde(rename = "汇总")]
    pub summary: Summary,
    #[serde(rename = "变化")]
    pub changes: Vec<AssetChange>,
}

impl Diff {
    pub fn is_empty(&self) -> bool {
        self.changes.is_empty()
    }

    pub fn count(&self, k: ChangeKind) -> usize {
        match k {
            ChangeKind::Added => self.summary.added,
            ChangeKind::Removed => self.summary.removed,
            ChangeKind::Content => self.summary.content,
            ChangeKind::Composition => self.summary.composition,
            ChangeKind::TextureOnly => self.summary.texture_only,
            ChangeKind::NamesOnly => self.summary.names_only,
            ChangeKind::Repacked => self.summary.repacked,
            ChangeKind::Renamed => self.summary.renamed,
            ChangeKind::FingerprintOnly => self.summary.fingerprint_only,
            ChangeKind::Unchanged => self.summary.unchanged,
        }
    }

    pub fn pretty_json(&self) -> String {
        serde_json::to_string_pretty(self).expect("a diff always serializes")
    }
}

/// How much of a pair's content can actually be judged.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Judge {
    /// Same identification vocabulary and member detail on both sides.
    Members,
    /// Same vocabulary but one side carries only composition counts: content is judged by
    /// the per-role digests, which are local to the role that moved.
    Digests,
    /// Different vocabulary: content stays undetermined.
    None,
}

/// Compare two snapshots of the same library.
pub fn diff(before: &Snapshot, after: &Snapshot) -> Diff {
    let comparable = !before.basis.is_empty() && before.basis == after.basis;
    let detail = before.has_member_detail() && after.has_member_detail();
    let judge = if !comparable {
        Judge::None
    } else if detail {
        Judge::Members
    } else {
        Judge::Digests
    };
    let scope = match judge {
        Judge::Members => "逐文件内容、组成、名称、打包位置",
        Judge::Digests => "组成与名称；成员明细缺失，内容按角色指纹判定",
        Judge::None => "仅组成、名称与路径：两份快照的成员标识口径不同，内容不作判定",
    }
    .to_string();

    // Index of the far side. A shared key may only pair as many times as it occurs, and a
    // content fingerprint is never trusted when it is not unique — 1,062 assets in this
    // install share a fingerprint with another, so guessing from one would mislabel both.
    // An unnamed group has no usable path key at all: 836 of them share one empty key, and
    // pairing inside that bucket by position invents hundreds of changes. They fall
    // through to content and overlap instead, exactly like `.scratch/identity.py` does.
    let n_before = before.assets.len();
    let n_after = after.assets.len();
    let mut path_idx: HashMap<(String, String), Vec<usize>> = HashMap::new();
    let mut fp_idx: HashMap<String, Vec<usize>> = HashMap::new();
    let mut postings: HashMap<String, Vec<usize>> = HashMap::new();
    for (i, a) in after.assets.iter().enumerate() {
        if !a.stem.is_empty() {
            path_idx.entry(a.path_key()).or_default().push(i);
        }
        if judge == Judge::Members {
            if !a.fp.asset.is_empty() {
                fp_idx.entry(a.fp.asset.clone()).or_default().push(i);
            }
            for (role, ident) in a.content_set() {
                if !ident.is_empty() {
                    postings.entry(format!("{role}\u{1}{ident}")).or_default().push(i);
                }
            }
        }
    }
    if judge == Judge::Members {
        postings.retain(|_, v| v.len() <= POSTING_CAP);
    }

    let mut before_by_path: HashMap<(String, String), Vec<usize>> = HashMap::new();
    for (i, a) in before.assets.iter().enumerate() {
        if !a.stem.is_empty() {
            before_by_path.entry(a.path_key()).or_default().push(i);
        }
    }

    let mut mate: Vec<Option<usize>> = vec![None; n_before];
    let mut taken: Vec<bool> = vec![false; n_after];

    // Pass 1 — same place in the tree. A key that occurs k times on either side pairs k
    // times in order: some groups share a (dir, stem), and refusing to pair them would
    // report a disappearance plus an arrival for an asset that did not move at all.
    for (key, bidx) in &before_by_path {
        let Some(aidx) = path_idx.get(key) else { continue };
        for (i, j) in bidx.iter().zip(aidx.iter()) {
            if !taken[*j] {
                mate[*i] = Some(*j);
                taken[*j] = true;
            }
        }
    }
    if judge == Judge::Members {
        // Pass 2 — identical content appearing exactly once on the far side.
        for (i, a) in before.assets.iter().enumerate() {
            if mate[i].is_some() || a.fp.asset.is_empty() {
                continue;
            }
            if let Some([j]) = fp_idx.get(&a.fp.asset).map(|v| &v[..]) {
                if !taken[*j] {
                    mate[i] = Some(*j);
                    taken[*j] = true;
                }
            }
        }
        // Pass 3 — enough members in common to be the same asset under a new name.
        for (i, a) in before.assets.iter().enumerate() {
            if mate[i].is_some() {
                continue;
            }
            let keys = a.content_set();
            if keys.is_empty() {
                continue;
            }
            let need = (keys.len() / 2).max(1);
            let mut scores: HashMap<usize, usize> = HashMap::new();
            for (role, ident) in &keys {
                if let Some(list) = postings.get(&format!("{role}\u{1}{ident}")) {
                    for j in list {
                        if !taken[*j] {
                            *scores.entry(*j).or_insert(0) += 1;
                        }
                    }
                }
            }
            let mut best: Option<(usize, usize)> = None;
            for (j, s) in scores {
                if s < need {
                    continue;
                }
                // A tie goes to the lowest index. Two candidates sharing the same number
                // of files are indistinguishable on evidence, and choosing between them by
                // hash-map order would not reproduce itself — while a library compared
                // with itself has to come out empty.
                let better = match best {
                    None => true,
                    Some((bj, bs)) => s > bs || (s == bs && j < bj),
                };
                if better {
                    best = Some((j, s));
                }
            }
            if let Some((j, _)) = best {
                mate[i] = Some(j);
                taken[j] = true;
            }
        }
    }

    // Pass 4 — a group that was never named, and whose members are too widely shared to
    // identify it, falls back to shape (kind, member count, per-role counts) in order.
    // Refusing here would report a disappearance plus an arrival for every one of the 836
    // unnamed rows when a library is compared with itself: the loudest possible way of
    // saying nothing changed. The first round demands the full shape; the second settles
    // for kind plus member count, which is all two snapshots built in different modes can
    // agree on (one of them never saw the per-role split at all).
    for fine in [true, false] {
        let mut after_by_shape: HashMap<String, Vec<usize>> = HashMap::new();
        for (j, b) in after.assets.iter().enumerate() {
            if b.stem.is_empty() && !taken[j] {
                let k = if fine { b.shape_key() } else { b.rough_key() };
                after_by_shape.entry(k).or_default().push(j);
            }
        }
        let mut before_by_shape: HashMap<String, Vec<usize>> = HashMap::new();
        for (i, a) in before.assets.iter().enumerate() {
            if a.stem.is_empty() && mate[i].is_none() {
                let k = if fine { a.shape_key() } else { a.rough_key() };
                before_by_shape.entry(k).or_default().push(i);
            }
        }
        for (key, list) in &before_by_shape {
            let Some(cands) = after_by_shape.get(key) else { continue };
            for (i, j) in list.iter().zip(cands.iter()) {
                if mate[*i].is_none() && !taken[*j] {
                    mate[*i] = Some(*j);
                    taken[*j] = true;
                }
            }
        }
    }

    let mut summary = Summary {
        before_assets: n_before,
        after_assets: n_after,
        ..Default::default()
    };
    let mut changes: Vec<AssetChange> = Vec::new();

    for (i, a) in before.assets.iter().enumerate() {
        match mate[i] {
            Some(j) => {
                summary.paired += 1;
                if judge == Judge::None {
                    summary.content_unjudged += 1;
                }
                match compare_pair(a, &after.assets[j], judge, &mut summary) {
                    Some(c) => changes.push(c),
                    None => summary.unchanged += 1,
                }
            }
            None => {
                summary.bump(ChangeKind::Removed);
                changes.push(blank(
                    a.display_name(),
                    &a.kind,
                    ChangeKind::Removed,
                    a.dir.clone(),
                    String::new(),
                    a.n_members,
                    0,
                    format!("{} 个成员文件不再出现", a.n_members),
                ));
            }
        }
    }
    for (j, b) in after.assets.iter().enumerate() {
        if taken[j] {
            continue;
        }
        summary.bump(ChangeKind::Added);
        changes.push(blank(
            b.display_name(),
            &b.kind,
            ChangeKind::Added,
            String::new(),
            b.dir.clone(),
            0,
            b.n_members,
            format!("{} 个成员文件", b.n_members),
        ));
    }

    changes.sort_by(|x, y| {
        x.headline
            .rank()
            .cmp(&y.headline.rank())
            .then_with(|| x.name.cmp(&y.name))
            .then_with(|| x.before_dir.cmp(&y.before_dir))
    });

    Diff {
        before: before.source.clone(),
        after: after.source.clone(),
        before_basis: before.basis.clone(),
        after_basis: after.basis.clone(),
        comparable,
        scope,
        summary,
        changes,
    }
}

#[allow(clippy::too_many_arguments)]
fn blank(
    name: &str,
    kind: &str,
    k: ChangeKind,
    before_dir: String,
    after_dir: String,
    before_members: usize,
    after_members: usize,
    note: String,
) -> AssetChange {
    AssetChange {
        name: name.to_string(),
        kind: kind.to_string(),
        headline: k,
        // An arrival has no far side to match, a disappearance has no far side at all, so
        // in both cases the basis is a property of the label, not of the passes.
        matched_by: match k {
            ChangeKind::Added => Some(MatchBasis::Added),
            _ => None,
        },
        before_dir,
        after_dir,
        changes: vec![k],
        notes: vec![note],
        before_members,
        after_members,
        added_members: Vec::new(),
        removed_members: Vec::new(),
        replaced_members: Vec::new(),
        role_moves: Vec::new(),
        fingerprint_moves: Vec::new(),
    }
}

/// The verdict for one matched pair; `None` when nothing about it moved.
fn compare_pair(
    a: &SnapAsset,
    b: &SnapAsset,
    judge: Judge,
    summary: &mut Summary,
) -> Option<AssetChange> {
    let mut kinds: Vec<ChangeKind> = Vec::new();
    let mut notes: Vec<String> = Vec::new();
    let mut added_members: Vec<String> = Vec::new();
    let mut removed_members: Vec<String> = Vec::new();
    let mut replaced_members: Vec<String> = Vec::new();
    // Which roles' content moved, whichever way the evidence arrived.
    let mut moved: HashSet<String> = HashSet::new();

    // Composition needs no shared vocabulary: counting files is vocabulary-free.
    let mut roles: Vec<String> =
        a.roles.keys().cloned().chain(b.roles.keys().cloned()).collect();
    roles.sort();
    roles.dedup();
    let role_moves: Vec<RoleMove> = roles
        .iter()
        .filter_map(|r| {
            let before = a.roles.get(r.as_str()).copied().unwrap_or(0);
            let after = b.roles.get(r.as_str()).copied().unwrap_or(0);
            (before != after).then(|| RoleMove { role: r.clone(), before, after })
        })
        .collect();
    if !role_moves.is_empty() {
        kinds.push(ChangeKind::Composition);
        notes.push(
            role_moves
                .iter()
                .map(|m| {
                    let zh = role_zh(&m.role);
                    if m.after > m.before {
                        format!("新增 {} 个{zh}", m.after - m.before)
                    } else {
                        format!("删除 {} 个{zh}", m.before - m.after)
                    }
                })
                .collect::<Vec<_>>()
                .join("；"),
        );
    }

    let fingerprint_moves = a.fp.moved_roles(&b.fp);
    // Which files entered or left, for the evidence lists, and whether any *content
    // identity* moved, which is the only thing that may be called 内容变化. A member that
    // arrives without an identity (the payload was never located) or a file that merely
    // changed name says something about which group owns what — attribution, a collection
    // vocabulary — and says nothing about the art.
    let mut attribution = false;
    match judge {
        Judge::Members => {
            let (ma, mb) = (a.keyed(), b.keyed());
            for (k, _) in &mb {
                if !ma.contains_key(k) {
                    added_members.push(describe(k));
                }
            }
            for (k, _) in &ma {
                if !mb.contains_key(k) {
                    removed_members.push(describe(k));
                }
            }
            for (k, (_, id)) in &ma {
                if let Some((_, bid)) = mb.get(k) {
                    if !id.is_empty() && !bid.is_empty() && id != bid {
                        replaced_members.push(describe(k));
                    }
                }
            }
            // Content moved iff a content identity arrived or departed. A renamed file keeps
            // its identity, and a member whose payload was never located has none to keep or
            // to lose, so neither of them is evidence about the art.
            let (ia, ib) = (content_ids(a), content_ids(b));
            for (role, _) in minus(&ia, &ib).into_iter().chain(minus(&ib, &ia).into_iter()) {
                moved.insert(role);
            }
            for (role, _, _) in &fingerprint_moves {
                moved.insert(role.clone());
            }
            attribution = moved.is_empty()
                && !(added_members.is_empty()
                    && removed_members.is_empty()
                    && replaced_members.is_empty());
        }
        Judge::Digests => {
            for (role, _, _) in &fingerprint_moves {
                moved.insert(role.clone());
            }
        }
        Judge::None => {}
    }

    added_members.sort();
    removed_members.sort();
    replaced_members.sort();
    let content_moved = !moved.is_empty();
    let presentation_only =
        content_moved && !moved.iter().any(|r| r != "texture");

    if content_moved {
        if presentation_only {
            kinds.push(ChangeKind::TextureOnly);
            notes.push("仅贴图/表现层文件变化，模型与材质指纹未动".to_string());
        } else {
            kinds.push(ChangeKind::Content);
            let mut parts = Vec::new();
            if !added_members.is_empty() {
                parts.push(format!("新增 {} 个文件", added_members.len()));
            }
            if !removed_members.is_empty() {
                parts.push(format!("删除 {} 个文件", removed_members.len()));
            }
            if !replaced_members.is_empty() {
                parts.push(format!("{} 个文件内容被替换", replaced_members.len()));
            }
            if parts.is_empty() {
                parts.push("成员数量变化而文件名称集合未变".to_string());
            }
            notes.push(parts.join("；"));
            if judge == Judge::Digests {
                notes.push("按角色指纹判定（成员明细缺失）".to_string());
            }
        }
    }

    let path_moved = a.path_key() != b.path_key();
    let names_moved = names_differ(a, b);
    let repacked =
        judge != Judge::None && !content_moved && (a.fp.pack_moved(&b.fp) || a.fp.loc_moved(&b.fp));
    // Nothing content-bearing moved, yet a digest or the file list did: that is the
    // 归属/口径 axis. It composes with a re-pack or a move instead of swallowing them,
    // because each of the three answers a different question.
    let fingerprint_only = judge != Judge::None
        && !content_moved
        && (attribution
            || !fingerprint_moves.is_empty()
            || a.fp.asset_moved(&b.fp)
            || a.fp.observed_moved(&b.fp));

    if repacked {
        kinds.push(ChangeKind::Repacked);
        notes.push("内容完全一致，只有压缩结果或在包内的位置变了".to_string());
    }
    if names_moved && !content_moved {
        // A re-pack riding along does not make the name layer's move invisible: those are
        // two different questions, and the contract keeps them as two orthogonal booleans.
        kinds.push(ChangeKind::NamesOnly);
        notes.push(ChangeKind::NamesOnly.note().to_string());
    }
    if path_moved && !content_moved {
        kinds.push(ChangeKind::Renamed);
        notes.push(format!("{} → {}", dir_or(a), dir_or(b)));
    }
    if fingerprint_only {
        kinds.push(ChangeKind::FingerprintOnly);
        notes.push(if attribution {
            "成员归属或文件名清单变了而内容标识一致，属采集口径变化，不作内容变化处理".to_string()
        } else {
            "成员文件一致而指纹不同，通常是重新打包或采集口径差异，不作内容变化处理".to_string()
        });
    }

    if kinds.is_empty() {
        return None;
    }

    let headline =
        kinds.iter().copied().min_by_key(|k| k.rank()).unwrap_or(ChangeKind::Unchanged);
    for k in &kinds {
        summary.bump(*k);
    }
    kinds.sort_by_key(|k| k.rank());
    kinds.dedup();
    trunc(&mut added_members);
    trunc(&mut removed_members);
    trunc(&mut replaced_members);

    Some(AssetChange {
        name: b.display_name().to_string(),
        kind: b.kind.clone(),
        headline,
        matched_by: Some(match_basis(a, b, judge)),
        before_dir: a.dir.clone(),
        after_dir: b.dir.clone(),
        changes: kinds,
        notes,
        before_members: a.n_members,
        after_members: b.n_members,
        added_members,
        removed_members,
        replaced_members,
        role_moves,
        fingerprint_moves,
    })
}

/// Which rule paired this row, recomputed from the pair itself instead of being remembered
/// by the matching passes: a report must say what its pairing rested on, and the passes run
/// cheapest-proof-first, so the first test that holds here is the rule that matched.
fn match_basis(a: &SnapAsset, b: &SnapAsset, judge: Judge) -> MatchBasis {
    if a.path_key() == b.path_key() {
        return MatchBasis::Path;
    }
    if judge != Judge::None && !a.fp.asset.is_empty() && a.fp.asset == b.fp.asset {
        return MatchBasis::Fingerprint;
    }
    MatchBasis::MemberOverlap
}

/// The content identities this asset carries, as a sorted multiset, with the members whose
/// payload was never located left out: they prove nothing about content either way.
fn content_ids(a: &SnapAsset) -> Vec<(String, String)> {
    let mut v: Vec<(String, String)> =
        a.content_set().into_iter().filter(|(_, id)| !id.is_empty()).collect();
    v.sort();
    v
}

/// Multiset difference of two sorted lists: what `kept` has that `gone` does not.
fn minus(kept: &[(String, String)], gone: &[(String, String)]) -> Vec<(String, String)> {
    let mut out = Vec::new();
    let mut rest = gone.iter().peekable();
    for x in kept {
        match rest.peek() {
            Some(y) if *y == x => {
                rest.next();
            }
            _ => out.push(x.clone()),
        }
    }
    out
}

/// Referenced names differ, judged on the lists themselves when either side carries any
/// and on the name digest otherwise. Sorted comparison: order is presentation, not fact.
fn names_differ(a: &SnapAsset, b: &SnapAsset) -> bool {
    if !a.names.is_empty() || !b.names.is_empty() {
        let (mut x, mut y) = (a.names.clone(), b.names.clone());
        x.sort();
        y.sort();
        return x != y;
    }
    a.fp.names_moved(&b.fp)
}

fn describe(key: &str) -> String {
    let mut parts = key.split('\u{1}');
    let role = parts.next().unwrap_or("");
    let what = parts.next().unwrap_or(key);
    format!("{what}({})", role_zh(role))
}

fn dir_or(a: &SnapAsset) -> String {
    if a.dir.is_empty() {
        "(无目录)".to_string()
    } else {
        a.dir.clone()
    }
}

fn trunc(v: &mut Vec<String>) {
    if v.len() > MAX_LISTED {
        v.truncate(MAX_LISTED);
        v.push("…另有更多项未列出".to_string());
    }
}

// ------------------------------------------------------------------ contract projection
//
// `contracts/VersionDiff.schema.json` is the shape the UI reads. It is deliberately
// narrower than the native `Diff` — it is `additionalProperties:false` — so what follows is
// a projection, never a second opinion: every value is read off the same [`AssetChange`]
// rows the native report prints, so the two views cannot disagree about a verdict.
//
// The schema's load-bearing demand is that `内容变化` and `指纹变化` stay orthogonal:
// `内容变化=false` together with `指纹变化=true` is exactly a re-pack or a collection
// vocabulary change, and is what keeps "the art changed" from being an artefact of
// `asset_fingerprint.fp_asset` digesting stored bytes.

/// `差异项.种类` value domain: the closed enum of raw English kind tokens. Anything the
/// catalog invents later lands in `other` rather than invalidating a whole document.
fn contract_kind(kind: &str) -> &'static str {
    match kind {
        "npc" => "npc",
        "player" => "player",
        "map-prop" => "map-prop",
        "effect" => "effect",
        "ui" => "ui",
        "shared-material" => "shared-material",
        _ => "other",
    }
}

/// `差异项.变化层` vocabulary: the eight comparable `asset_fingerprint` columns. A role with
/// no column of its own (`scene`, `config`, ...) is only visible through `fp_asset`.
fn contract_layer(role: &str) -> Option<&'static str> {
    Some(match role {
        "model" => "fp_model",
        "skeleton" => "fp_skeleton",
        "mesh" => "fp_mesh",
        "material" => "fp_material",
        "animation" => "fp_animation",
        "texture" => "fp_texture",
        _ => return None,
    })
}

fn push_layer(v: &mut Vec<&'static str>, l: &'static str) {
    if !v.contains(&l) {
        v.push(l);
    }
}

/// One row in contract vocabulary:
/// `(变更类型, 判定, 内容变化, 指纹变化, 变化层, 匹配方式)`.
fn contract_shape(
    c: &AssetChange,
) -> (&'static str, &'static str, bool, bool, Vec<&'static str>, Option<&'static str>) {
    let has = |k: ChangeKind| c.changes.contains(&k);
    // The single honest answer to "did the art change": a member file's own content moved.
    let content = has(ChangeKind::Content) || has(ChangeKind::TextureOnly);
    let repacked = has(ChangeKind::Repacked);

    let mut layers: Vec<&'static str> = Vec::new();
    if !c.fingerprint_moves.is_empty() {
        push_layer(&mut layers, "fp_asset");
        for (role, _, _) in &c.fingerprint_moves {
            if let Some(l) = contract_layer(role) {
                push_layer(&mut layers, l);
            }
        }
    }
    if has(ChangeKind::NamesOnly) {
        push_layer(&mut layers, "fp_names");
    }
    // 仅指纹变化 covers both flavours of "the members are the same but a digest moved": the
    // aggregate digest, and the database's own stored-byte `fp_asset` (`observed`). An
    // arrival puts whole new content into the library, so its aggregate layer moved too.
    if content || has(ChangeKind::FingerprintOnly) || has(ChangeKind::Added) {
        push_layer(&mut layers, "fp_asset");
    }

    let basis = c.matched_by.map(|m| match m {
        MatchBasis::Path => "路径",
        MatchBasis::Fingerprint => "身份证",
        MatchBasis::MemberOverlap => "成员重叠",
        MatchBasis::Added => "新增",
    });

    let (bucket, verdict) = if has(ChangeKind::Added) {
        ("新增", "新资产出现")
    } else if has(ChangeKind::Removed) {
        ("删除", "资产消失")
    } else if content {
        // 结构变化 = files entered or left; 内容微调 = the same files, different bytes.
        let structural = has(ChangeKind::Composition)
            || !c.added_members.is_empty()
            || !c.removed_members.is_empty();
        ("变更", if structural { "结构变化" } else { "内容微调" })
    } else if has(ChangeKind::Composition) {
        // Composition counts moved while content could not be read (no member detail): the
        // bucket is still 变更, but `内容变化` below stays false, which is the whole point of
        // separating the two axes.
        ("变更", "结构变化")
    } else if has(ChangeKind::FingerprintOnly) {
        ("变更", "身份证不同")
    } else if has(ChangeKind::NamesOnly) {
        if repacked {
            ("仅名称变化", "仅重新打包")
        } else {
            ("仅名称变化", "相同")
        }
    } else if repacked {
        ("未变", "仅重新打包")
    } else {
        // Only the path moved (or nothing more was provable): one asset that relocated,
        // never a deletion plus an arrival.
        ("未变", "相同")
    };

    let out_content = match bucket {
        "新增" => true,
        "删除" => false,
        _ => content,
    };
    // The schema forbids 未变 from carrying layers, and 仅名称变化 from carrying anything
    // but its own column: packing and location signals are not content layers, so they are
    // reported by `指纹变化` and the flags instead.
    match bucket {
        "未变" => layers.clear(),
        "仅名称变化" => {
            layers.clear();
            push_layer(&mut layers, "fp_names");
        }
        _ => {}
    }
    let fingerprint =
        out_content || repacked || has(ChangeKind::FingerprintOnly) || !layers.is_empty();
    let basis = if bucket == "删除" { None } else { basis };
    (bucket, verdict, out_content, fingerprint, layers, basis)
}

impl Diff {
    /// `差异文档.版本`. 2 matches the reference builder in `contracts/crosscheck.js`, so the
    /// two implementations' tallies can sit side by side and disagree informatively.
    pub const CONTRACT_VERSION: u32 = 2;

    /// This diff as a `contracts/VersionDiff.schema.json` document. It carries no
    /// timestamp: two runs over the same pair of snapshots must be byte-identical.
    pub fn contract_document(&self) -> serde_json::Value {
        let mut stats: BTreeMap<&'static str, usize> = BTreeMap::new();
        let mut buckets: BTreeMap<&'static str, usize> = BTreeMap::new();
        let mut items = Vec::with_capacity(self.changes.len());
        for c in &self.changes {
            let (bucket, verdict, content, fingerprint, layers, basis) = contract_shape(c);
            *stats.entry(verdict).or_insert(0) += 1;
            *buckets.entry(bucket).or_insert(0) += 1;
            let mut notes = c.notes.clone();
            if !self.comparable && c.matched_by.is_some() {
                // The document has no envelope field for this, and a row that cannot be
                // judged must not read as one that was.
                notes.push(format!("判定范围：{}", self.scope));
            }
            let mut row = serde_json::Map::new();
            row.insert("变更类型".into(), serde_json::json!(bucket));
            row.insert("判定".into(), serde_json::json!(verdict));
            row.insert("名称".into(), serde_json::json!(c.name));
            row.insert("种类".into(), serde_json::json!(contract_kind(&c.kind)));
            if let Some(b) = basis {
                row.insert("匹配方式".into(), serde_json::json!(b));
            }
            row.insert("内容变化".into(), serde_json::json!(content));
            row.insert("指纹变化".into(), serde_json::json!(fingerprint));
            row.insert("变化层".into(), serde_json::json!(layers));
            if verdict == "仅重新打包" {
                row.insert("仅重新打包".into(), serde_json::json!(true));
            }
            if bucket == "仅名称变化" {
                row.insert("仅名称变化".into(), serde_json::json!(true));
            }
            if !notes.is_empty() {
                row.insert("说明".into(), serde_json::json!(notes.join("；")));
            }
            items.push(serde_json::Value::Object(row));
        }
        // 明细 lists only the rows that moved; the rows that did not are still counted, or
        // the two tables would not reconcile against the snapshot sizes.
        *stats.entry("相同").or_insert(0) += self.summary.unchanged;
        *buckets.entry("未变").or_insert(0) += self.summary.unchanged;
        serde_json::json!({
            "版本": Self::CONTRACT_VERSION,
            // 基线/目标 are free-form identifier strings, and they are the only legal place
            // in this document for the one thing the schema has no field for: which
            // identification vocabulary each side spoke, and therefore that a `未变` count is
            // "not judged" rather than "checked and equal" when the two do not match.
            "基线": side(&self.before, &self.before_basis, self.comparable),
            "目标": side(&self.after, &self.after_basis, self.comparable),
            "统计": stats,
            "变化计数": buckets,
            "明细": items,
        })
    }

    /// [`Diff::contract_document`] as compact JSON, ready for the UI or for
    /// `node contracts/crosscheck.js`.
    pub fn contract_json(&self) -> String {
        serde_json::to_string(&self.contract_document()).expect("a contract document serializes")
    }
}

/// One side of the document's provenance line: what it was, and in which vocabulary — or,
/// when the two vocabularies differ, that content was never judged at all.
fn side(source: &str, basis: &str, comparable: bool) -> String {
    let name = if source.is_empty() { "(未具名快照)" } else { source };
    if comparable {
        format!("{name}〔{basis}〕")
    } else {
        format!("{name}〔{basis}·口径不可比，内容未判定〕")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn member(role: &str, ident: &str, name: &str) -> Member {
        Member {
            role: role.to_string(),
            ident: ident.to_string(),
            name: name.to_string(),
            crc: String::new(),
            loc: String::new(),
        }
    }

    /// One asset, built the way a snapshot builder builds it.
    fn asset(gid: i64, stem: &str, members: Vec<Member>) -> SnapAsset {
        let mut a = SnapAsset {
            gid,
            stem: stem.to_string(),
            kind: "npc".to_string(),
            dir: "data/source/npc/x".to_string(),
            hub: format!("data/source/npc/x/{stem}.mdl"),
            ..Default::default()
        };
        a.members = members;
        a.refresh();
        a
    }

    fn snap(assets: Vec<SnapAsset>) -> Snapshot {
        Snapshot {
            format: FORMAT,
            source: "test".to_string(),
            basis: BASIS_RESOURCE.to_string(),
            assets,
        }
    }

    #[track_caller]
    fn find<'d>(d: &'d Diff, name: &str) -> &'d AssetChange {
        match d.changes.iter().find(|c| c.name == name) {
            Some(c) => c,
            None => panic!("{name} not reported in {:?}", report(d)),
        }
    }

    /// A failure must stay readable: a real diff is thousands of rows long.
    fn report(d: &Diff) -> Vec<(&str, Vec<ChangeKind>)> {
        d.changes
            .iter()
            .take(8)
            .map(|c| (c.name.as_str(), c.changes.clone()))
            .collect()
    }

    fn has(c: &AssetChange, k: ChangeKind) -> bool {
        c.changes.contains(&k)
    }

    #[test]
    fn added_and_removed_assets_are_named_as_such() {
        let a = snap(vec![asset(1, "gone", vec![member("model", "h1", "gone.mdl")])]);
        let b = snap(vec![asset(2, "fresh", vec![member("model", "h2", "fresh.mdl")])]);
        let d = diff(&a, &b);
        assert_eq!(d.summary.added, 1, "{d:?}");
        assert_eq!(d.summary.removed, 1);
        assert!(has(find(&d, "gone"), ChangeKind::Removed));
        assert!(has(find(&d, "fresh"), ChangeKind::Added));
        assert_eq!(d.summary.content, 0, "配对失败不得伪装成内容变化");
    }

    #[test]
    fn only_names_moved_is_flagged_as_a_collection_change() {
        let mut x = asset(1, "npc_a", vec![member("model", "h1", "npc_a.mdl")]);
        let mut y = asset(1, "npc_a", vec![member("model", "h1", "npc_a.mdl")]);
        x.names = vec!["a_old.tga".to_string()];
        y.names = vec!["a_new.tga".to_string()];
        x.refresh();
        y.refresh();
        let d = diff(&snap(vec![x]), &snap(vec![y]));
        let c = find(&d, "npc_a");
        assert_eq!(c.headline, ChangeKind::NamesOnly, "{c:?}");
        assert!(c.notes.iter().any(|n| n.contains("采集口径")), "{:?}", c.notes);
        assert_eq!(d.summary.content, 0);
    }

    #[test]
    fn a_texture_swap_is_not_a_model_change() {
        let x = asset(
            1,
            "npc_a",
            vec![member("model", "m1", "a.mdl"), member("texture", "t1", "a.tga")],
        );
        let y = asset(
            1,
            "npc_a",
            vec![member("model", "m1", "a.mdl"), member("texture", "t2", "a.tga")],
        );
        let d = diff(&snap(vec![x]), &snap(vec![y]));
        let c = find(&d, "npc_a");
        assert_eq!(c.headline, ChangeKind::TextureOnly, "{c:?}");
        assert!(!has(c, ChangeKind::Content), "贴图变化不得重复计为内容变化");
        assert_eq!(c.replaced_members.len(), 1);
        assert_eq!(d.summary.texture_only, 1);
    }

    #[test]
    fn members_can_move_while_the_fingerprint_stays_put() {
        // The carried fingerprint says nothing happened; the member list says otherwise,
        // and the member list wins.
        let mut x = asset(1, "npc_a", vec![member("model", "m1", "a.mdl")]);
        let mut y = asset(
            1,
            "npc_a",
            vec![member("model", "m1", "a.mdl"), member("animation", "k1", "a_idle.ani")],
        );
        x.fp.observed = "same".to_string();
        y.fp.observed = "same".to_string();
        y.fp.asset = x.fp.asset.clone();
        let d = diff(&snap(vec![x]), &snap(vec![y]));
        let c = find(&d, "npc_a");
        assert!(has(c, ChangeKind::Content), "{c:?}");
        assert!(has(c, ChangeKind::Composition), "{c:?}");
        assert!(!has(c, ChangeKind::FingerprintOnly));
    }

    #[test]
    fn a_fingerprint_move_without_members_is_not_content() {
        // Same members, but the database's own fp_asset moved: re-packing, not art.
        let mut x = asset(1, "npc_a", vec![member("model", "m1", "a.mdl")]);
        let mut y = asset(1, "npc_a", vec![member("model", "m1", "a.mdl")]);
        x.fp.observed = "1111111111111111".to_string();
        y.fp.observed = "2222222222222222".to_string();
        let d = diff(&snap(vec![x]), &snap(vec![y]));
        let c = find(&d, "npc_a");
        assert_eq!(c.headline, ChangeKind::FingerprintOnly, "{c:?}");
        assert_eq!(d.summary.content, 0);
        assert!(c.notes.iter().any(|n| n.contains("不作内容变化")), "{:?}", c.notes);
    }

    #[test]
    fn repacking_is_not_content_either() {
        let mut x = asset(1, "npc_a", vec![member("model", "m1", "a.mdl")]);
        let mut y = asset(1, "npc_a", vec![member("model", "m1", "a.mdl")]);
        for m in &mut x.members {
            m.loc = "data.pak@100/3".to_string();
        }
        for m in &mut y.members {
            m.loc = "data.pak@9000/3".to_string();
        }
        x.refresh();
        y.refresh();
        let d = diff(&snap(vec![x]), &snap(vec![y]));
        let c = find(&d, "npc_a");
        assert_eq!(c.headline, ChangeKind::Repacked, "{c:?}");
        assert_eq!(d.summary.content, 0);
    }

    #[test]
    fn member_order_alone_changes_nothing() {
        let x = asset(
            1,
            "npc_a",
            vec![member("model", "m1", "a.mdl"), member("mesh", "g1", "a.mesh")],
        );
        let y = asset(
            1,
            "npc_a",
            vec![member("mesh", "g1", "a.mesh"), member("model", "m1", "a.mdl")],
        );
        let d = diff(&snap(vec![x]), &snap(vec![y]));
        assert!(d.is_empty(), "{:?}", d.changes);
        assert_eq!(d.summary.unchanged, 1);
    }

    #[test]
    fn a_renamed_asset_pairs_on_its_members() {
        let mut x = asset(1, "old_name", vec![member("model", "m1", "a.mdl")]);
        let mut y = asset(9, "new_name", vec![member("model", "m1", "a.mdl")]);
        x.dir = "data/source/npc/one".to_string();
        y.dir = "data/source/npc/two".to_string();
        let d = diff(&snap(vec![x]), &snap(vec![y]));
        assert_eq!(d.summary.added, 0, "{d:?}");
        assert_eq!(d.summary.removed, 0);
        assert_eq!(find(&d, "new_name").headline, ChangeKind::Renamed);
    }

    #[test]
    fn digests_are_multiset_and_stable() {
        let v = |s: &[&str]| s.iter().map(|x| x.to_string()).collect::<Vec<String>>();
        assert_eq!(digest(&v(&["a", "b"])), digest(&v(&["b", "a"])));
        assert_ne!(digest(&v(&["a", "b"])), digest(&v(&["ab"])));
        assert_ne!(digest(&v(&["a", "b"])), digest(&v(&["a", "b", "b"])));
    }

    #[test]
    fn foreign_basis_reports_no_content_but_still_counts_composition() {
        let x = snap(vec![asset(1, "npc_a", vec![member("model", "m1", "a.mdl")])]);
        let mut y = snap(vec![asset(
            1,
            "npc_a",
            vec![member("model", "m1", "a.mdl"), member("mesh", "m2", "a.mesh")],
        )]);
        y.basis = BASIS_PAYLOAD.to_string();
        let d = diff(&x, &y);
        assert!(!d.comparable);
        assert_eq!(d.summary.content, 0, "口径不同时不得判定内容");
        assert_eq!(d.summary.content_unjudged, 1);
        assert_eq!(d.summary.composition, 1, "成员计数是可比的");
    }

    #[test]
    fn native_json_round_trips_and_diffs_to_nothing() {
        let s = snap(vec![asset(
            1,
            "npc_a",
            vec![member("model", "m1", "a.mdl"), member("texture", "t1", "a.tga")],
        )]);
        let text = s.to_json();
        let back = Snapshot::from_json(&text).expect("native snapshot parses");
        assert_eq!(back, s);
        assert!(diff(&s, &back).is_empty());
    }

    #[test]
    fn identity_v2_shape_reads_in_and_keeps_packing_signals_separate() {
        let text = r#"{"version":2,"built_from":"resources.db","assets":[{"gid":7,
            "stem":"npc_b","kind":"npc","dir":"data/source/npc/x","hub_path":"",
            "id_content":"c","id_asset":"a","rels":{"use-mtl":1},
            "members":[{"role":"material","name":"b.mtl","sha":"20db67d3f80c2a06","crc":"2832486e","type":"JBCF","w":null,"h":null}],
            "names":["b.tga"]}]}"#;
        let s = Snapshot::from_json(text).expect("v2 snapshot parses");
        assert_eq!(s.basis, BASIS_PAYLOAD);
        assert_eq!(s.len(), 1);
        let a = &s.assets[0];
        assert_eq!(a.members[0].ident, "20db67d3f80c2a06");
        assert_eq!(a.members[0].crc, "2832486e");
        assert_eq!(a.fp.foreign.get("id_content").map(|s| s.as_str()), Some("c"));
        assert!(!a.fp.pack.is_empty(), "包内CRC 要能支撑仅重新打包的判定");

        // Same content, different stored bytes: a re-pack, not new art.
        let other = text.replace("2832486e", "deadbeef");
        let s2 = Snapshot::from_json(&other).expect("second v2 snapshot parses");
        let d = diff(&s, &s2);
        assert_eq!(d.summary.repacked, 1, "{:?}", d.changes);
        assert_eq!(d.summary.content, 0);
        assert_eq!(find(&d, "npc_b").headline, ChangeKind::Repacked);
    }

    #[test]
    fn an_unparsable_blob_names_both_formats() {
        let e = Snapshot::from_json("{\"nope\":1}").unwrap_err();
        assert!(e.to_string().contains("identity v2"), "{e}");
    }
}
