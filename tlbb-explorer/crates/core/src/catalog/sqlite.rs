//! `resources.db` access, read-only.

use std::fmt;
use std::path::Path;

use rusqlite::{Connection, OpenFlags};
use serde::{Deserialize, Serialize};

#[derive(Debug)]
pub enum Error {
    Open(String),
    Sql(String),
    BadHash(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Error::Open(s) => write!(f, "cannot open catalog: {s}"),
            Error::Sql(s) => write!(f, "catalog query failed: {s}"),
            Error::BadHash(s) => write!(f, "malformed hash in catalog: {s}"),
        }
    }
}

impl std::error::Error for Error {}

pub type Result<T> = std::result::Result<T, Error>;

fn hash_of(s: &str) -> Result<u64> {
    u64::from_str_radix(s, 16).map_err(|_| Error::BadHash(s.to_string()))
}

#[derive(Debug, Clone)]
pub struct Asset {
    pub hash: u64,
    pub path: Option<String>,
    pub dir: String,
    pub name: String,
    pub ext: String,
    pub rtype: String,
    pub subtype: String,
    pub codec: String,
    pub width: i64,
    pub height: i64,
    pub mips: i64,
    pub stored: i64,
    pub original: i64,
    pub pak: String,
    pub gen: i64,
    pub offset: i64,
    pub named: bool,
    pub props: String,
    pub src: String,
}

/// One inbound use edge after the internal-edge filter.
#[derive(Debug, Clone)]
pub struct UseEdge {
    pub from_hash: u64,
    pub from_path: String,
    pub kind: String,
    pub from_gid: Option<i64>,
}

#[derive(Debug, Clone)]
pub struct Reference {
    pub name: String,
    pub kind: String,
    pub to: Option<u64>,
    pub to_path: Option<String>,
    pub ambiguous: bool,
}

pub type KindCount = (String, usize);

const ASSET_COLS: &str = "hash, path, dir, name, ext, type, subtype, codec, width, height, \
     mips, stored, original, pak, gen, offset, named, props, src";

impl Asset {
    fn from_row(r: &rusqlite::Row<'_>) -> rusqlite::Result<Self> {
        let hs: String = r.get(0)?;
        // Nearly every descriptive column is NULL for unnamed resources, so nothing
        // here may be read as a plain String.
        let text = |i: usize| -> rusqlite::Result<String> {
            Ok(r.get::<_, Option<String>>(i)?.unwrap_or_default())
        };
        let num = |i: usize| -> rusqlite::Result<i64> { Ok(r.get::<_, Option<i64>>(i)?.unwrap_or(0)) };
        Ok(Asset {
            hash: u64::from_str_radix(&hs, 16).unwrap_or(0),
            path: r.get::<_, Option<String>>(1)?,
            dir: text(2)?,
            name: text(3)?,
            ext: text(4)?,
            rtype: text(5)?,
            subtype: text(6)?,
            codec: text(7)?,
            width: num(8)?,
            height: num(9)?,
            mips: num(10)?,
            stored: num(11)?,
            original: num(12)?,
            pak: text(13)?,
            gen: num(14)?,
            offset: num(15)?,
            named: num(16)? != 0,
            props: text(17)?,
            src: text(18)?,
        })
    }
}

#[derive(Debug, Clone)]
pub struct Group {
    pub id: i64,
    pub hub: u64,
    pub hub_path: String,
    pub dir: String,
    pub stem: String,
    pub kind: String,
    pub n: i64,
    pub n_mesh: i64,
    pub n_mtl: i64,
    pub n_ani: i64,
    pub n_ske: i64,
    pub n_tex: i64,
}

#[derive(Debug, Clone)]
pub struct Member {
    pub hash: u64,
    pub role: String,
    pub path: Option<String>,
    pub rtype: String,
    pub pak: String,
    pub offset: i64,
    pub original: i64,
    pub ver: i64,
}

/// The identity row of a group: content addressee and packing addressee.
///
/// Both are facts *about the asset*, so both consumers read them here rather than running
/// their own SQL. `id_asset` is content-only and `id_pack` folds in the compression
/// result, which is why a repack moves one and not the other.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Identity {
    pub id_asset: String,
    pub id_pack: String,
}

/// The eight comparable fingerprint columns of one asset, kept verbatim.
///
/// [`Catalog::fingerprint`] answers the narrower question "did the content move" with the
/// single `fp_asset` column. This carries the per-role breakdown the report prints, and it
/// is the same row — there is exactly one `asset_fingerprint` table, so there must be
/// exactly one reader.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Fingerprints {
    pub asset: String,
    pub model: String,
    pub skeleton: String,
    pub mesh: String,
    pub material: String,
    pub animation: String,
    pub texture: String,
    pub names: String,
}

/// One member together with the digests that describe its stored bytes.
///
/// [`Catalog::members`] already carries the pak location; this is the identity-oriented
/// view of the same rows, where `sha` answers "is this the same bytes" and `crc` answers
/// "is this the same stored record".
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MemberDigest {
    pub role: String,
    pub name: String,
    pub sha: String,
    pub crc: String,
}

/// How big the library is, in one place.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Totals {
    pub groups: usize,
    pub members: usize,
    pub resources: usize,
    pub names: usize,
    pub dangling: usize,
    pub refs: usize,
    pub relations: usize,
}

/// Evidence health of the reference graph: of every name an asset cites, how many point
/// at a resource we actually hold.
///
/// This is the honest denominator for the whole product. A reference is *resolved* only
/// when its name lands on a real hash; a name that resolves to nothing is not a missing
/// parse, it is a citation the shipped client left behind. Neither is an error, so both
/// are reported rather than one being dressed up as the other.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct RefHealth {
    pub refs_total: usize,
    pub refs_resolved: usize,
    /// Rows the catalog recorded as dangling names, counted separately from `refs`.
    pub dangling_names: usize,
    /// Distinct assets with any citation edge at all — the denominator.
    pub assets_citing: usize,
    /// Distinct assets whose citations resolved to something we hold.
    pub assets_citing_resolved: usize,
    /// Resolved rows, broken down by the cited extension.
    pub by_ext: Vec<RefExt>,
}

/// One extension's share of the reference graph.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct RefExt {
    /// Extension as it appears in `refs.kind`, e.g. `.mtl`.
    pub ext: String,
    pub total: usize,
    pub resolved: usize,
    /// Distinct dangling names carrying this extension. Not the same unit as `total`:
    /// `total` counts edges, this counts names.
    pub dangling_names: usize,
}

/// A name that is cited but points at no resource we hold.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct DanglingName {
    pub name: String,
    pub ext: String,
    /// How many reference rows cite this name.
    pub citations: usize,
    /// How many distinct assets cite it.
    pub sources: usize,
    /// The catalog's own classification for the name (`shared` / ...).
    pub class: String,
}

/// The refs/relations split the product is trusted on.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct RelationCensus {
    /// Every row in `refs`, before any filter. Forensics only.
    pub raw_refs: usize,
    /// `from_hash = to_hash` — an asset citing itself.
    pub self_refs: usize,
    /// Both ends inside one group: internal composition, not usage.
    pub internal_group_edges: usize,
    /// `refs` rows whose name resolved to a real hash.
    pub located: usize,
    /// `model-part` + `same-stem`: naming inference, never usage.
    pub inferred: usize,
    /// `use-*` + `ref`: content forensics.
    pub forensic: usize,
    /// Every row in `relations`.
    pub all_relations: usize,
}

pub struct Catalog {
    con: Connection,
}

impl Catalog {
    pub fn open_ro(path: impl AsRef<Path>) -> Result<Self> {
        let con = Connection::open_with_flags(
            path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(|e| Error::Open(e.to_string()))?;
        con.busy_timeout(std::time::Duration::from_secs(5))
            .map_err(|e| Error::Open(e.to_string()))?;
        // The workbench opens one of these per warm-up shard (up to 16) and each one then
        // walks a sixth of the library. rusqlite's default page cache is far smaller than
        // the hot working set (`amembers` × `resources` lookups), so shards evict each
        // other's pages and the same B-tree pages are read over and over. 16 MiB per
        // handle is ~256 MiB across a full 16-lane run on a database that is only 145 MiB,
        // which makes the whole catalog effectively resident without a special setup step.
        con.execute_batch("PRAGMA cache_size = -16384;")
            .map_err(|e| Error::Open(e.to_string()))?;
        Ok(Self { con })
    }

    fn rows<T>(&self, sql: &str, p: &[&dyn rusqlite::ToSql], mut f: impl FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<T>) -> Result<Vec<T>> {
        let mut st = self.con.prepare(sql).map_err(|e| Error::Sql(e.to_string()))?;
        let mut out = Vec::new();
        for row in st.query_map(p, |r| f(r)).map_err(|e| Error::Sql(e.to_string()))? {
            out.push(row.map_err(|e| Error::Sql(e.to_string()))?);
        }
        Ok(out)
    }

    pub fn asset(&self, hash: u64) -> Result<Option<Asset>> {
        let key = format!("{hash:016x}");
        let sql = format!("SELECT {ASSET_COLS} FROM resources WHERE hash = ?1");
        Ok(self.rows(&sql, &[&key], Asset::from_row)?.pop())
    }

    pub fn groups(&self, limit: usize) -> Result<Vec<Group>> {
        let sql = "SELECT id, hub, hub_path, dir, stem, kind, n, n_mesh, n_mtl, n_ani, n_ske, n_tex                    FROM agroups ORDER BY n DESC LIMIT ?1";
        self.rows(sql, &[&(limit.min(i64::MAX as usize) as i64)], |r| {
            let hub: String = r.get(1)?;
            Ok(Group {
                id: r.get(0)?,
                hub: u64::from_str_radix(&hub, 16).unwrap_or(0),
                hub_path: r.get(2)?,
                dir: r.get(3)?,
                stem: r.get(4)?,
                kind: r.get(5)?,
                n: r.get(6)?,
                n_mesh: r.get(7)?,
                n_mtl: r.get(8)?,
                n_ani: r.get(9)?,
                n_ske: r.get(10)?,
                n_tex: r.get(11)?,
            })
        })
    }

    /// Members of a group, joined to `resources` so each one carries its pak location.
    pub fn members(&self, gid: i64) -> Result<Vec<Member>> {
        self.rows(
            "SELECT m.hash, m.role, r.path, r.type, r.pak, r.offset, r.original, r.ver              FROM amembers m LEFT JOIN resources r ON r.hash = m.hash WHERE m.gid = ?1              ORDER BY m.role, r.path",
            &[&gid],
            |r| {
                let h: String = r.get(0)?;
                Ok(Member {
                    hash: u64::from_str_radix(&h, 16).unwrap_or(0),
                    role: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                    path: r.get(2)?,
                    rtype: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                    pak: r.get::<_, Option<String>>(4)?.unwrap_or_default(),
                    offset: r.get::<_, Option<i64>>(5)?.unwrap_or(0),
                    original: r.get::<_, Option<i64>>(6)?.unwrap_or(0),
                    ver: r.get::<_, Option<i64>>(7)?.unwrap_or(0),
                })
            },
        )
    }

    pub fn tags(&self, gid: i64) -> Result<Vec<(String, String)>> {
        self.rows(
            "SELECT tag, confidence FROM asset_tags WHERE gid = ?1 ORDER BY confidence, tag",
            &[&gid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
    }

    pub fn group_names(&self, gid: i64) -> Result<Vec<(String, String)>> {
        self.rows(
            "SELECT name, cls FROM agroup_names WHERE gid = ?1 ORDER BY name",
            &[&gid],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
    }

    /// Textures that live in the same virtual directory — the fallback when a material's
    /// own texture reference dangles.
    pub fn textures_in_dir(&self, dir: &str) -> Result<Vec<(u64, String)>> {
        // An empty directory means "this asset has no recorded path at all". Matching on
        // it would return arbitrary textures and let a card show somebody else's image.
        if dir.trim().is_empty() {
            return Ok(Vec::new());
        }
        self.rows(
            "SELECT hash, path FROM resources WHERE type = 'texture' AND dir = ?1              ORDER BY original DESC LIMIT 8",
            &[&dir],
            |r| {
                let h: String = r.get(0)?;
                Ok((u64::from_str_radix(&h, 16).unwrap_or(0), r.get(1)?))
            },
        )
    }

    /// Texture references raised by any member of the group, not just the hub file:
    /// the shipped materials hang their texture names off member `.mtl` rows.
    pub fn refs_from_many(&self, hashes: &[u64]) -> Result<Vec<(String, Option<u64>)>> {
        let mut out = Vec::new();
        for h in hashes.iter().take(400) {
            for r in self.refs_from(*h)? {
                out.push((r.name, r.to));
            }
        }
        Ok(out)
    }

    /// Counts for the whole library, in one place, so a README and the workbench cannot
    /// disagree about how big the catalog is.
    pub fn totals(&self) -> Result<Totals> {
        let one = |sql: &str| -> i64 {
            self.con.query_row(sql, [], |r| r.get::<_, i64>(0)).unwrap_or(0)
        };
        Ok(Totals {
            groups: one("SELECT count(*) FROM agroups") as usize,
            members: one("SELECT count(*) FROM amembers") as usize,
            resources: one("SELECT count(*) FROM resources") as usize,
            names: one("SELECT count(*) FROM agroup_names") as usize,
            dangling: one("SELECT count(*) FROM dangling") as usize,
            refs: one("SELECT count(*) FROM refs") as usize,
            relations: one("SELECT count(*) FROM relations") as usize,
        })
    }

    /// Every texture row, as `(hash, dir)`. One query rather than one per directory: the
    /// directory fallback is asked for every asset, and 13,080 round trips is not a
    /// measurement, it is a crawl.
    pub fn textures_all(&self) -> Result<Vec<(u64, String)>> {
        self.rows(
            "SELECT hash, dir FROM resources WHERE type = 'texture'",
            &[] as &[&dyn rusqlite::ToSql],
            |r| {
                let h: String = r.get(0)?;
                Ok((u64::from_str_radix(&h, 16).unwrap_or(0), r.get::<_, Option<String>>(1)?.unwrap_or_default()))
            },
        )
    }

    /// Table sizes, so the baseline document carries its own evidence.
    pub fn table_counts(&self) -> Result<Vec<(String, usize)>> {
        let names: Vec<String> = self
            .rows(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
                &[] as &[&dyn rusqlite::ToSql],
                |r| r.get(0),
            )?;
        let mut out = Vec::new();
        for n in names {
            let sql = format!("SELECT count(*) FROM \"{n}\"");
            if let Ok(c) = self.con.query_row(&sql, [], |r| r.get::<_, i64>(0)) {
                out.push((n, c as usize));
            }
        }
        Ok(out)
    }

    /// The relationship census behind `refs` / `relations`. These are the numbers the
    /// product is trusted on, so they are derived here rather than counted by whichever
    /// script happens to be reporting.
    ///
    /// The split that matters is `relations.rel`: `use-*` edges are content forensics,
    /// `model-part` / `same-stem` are naming inference and must never be read as usage.
    pub fn relation_census(&self) -> Result<RelationCensus> {
        let one = |sql: &str| -> usize {
            self.con
                .query_row(sql, [], |r| r.get::<_, i64>(0))
                .unwrap_or(0) as usize
        };
        Ok(RelationCensus {
            raw_refs: one("SELECT count(*) FROM refs"),
            self_refs: one("SELECT count(*) FROM refs WHERE from_hash = to_hash"),
            internal_group_edges: one(
                "SELECT count(*) FROM refs r WHERE EXISTS ( \
                   SELECT 1 FROM amembers a JOIN amembers b ON a.gid = b.gid \
                   WHERE a.hash = r.from_hash AND b.hash = r.to_hash)",
            ),
            located: one("SELECT count(*) FROM refs WHERE to_hash IS NOT NULL"),
            inferred: one("SELECT count(*) FROM relations WHERE rel IN ('model-part','same-stem')"),
            forensic: one("SELECT count(*) FROM relations WHERE rel LIKE 'use-%' OR rel = 'ref'"),
            all_relations: one("SELECT count(*) FROM relations"),
        })
    }

    /// Evidence health of the reference graph. Both halves are counted from the catalog
    /// itself so a viewer never has to trust a script's arithmetic.
    pub fn ref_health(&self) -> Result<RefHealth> {
        let one = |sql: &str| -> usize {
            self.con
                .query_row(sql, [], |r| r.get::<_, i64>(0))
                .unwrap_or(0) as usize
        };
        let mut by_ext: Vec<RefExt> = self.rows(
            "SELECT COALESCE(kind, ''), count(*), \
                    sum(CASE WHEN to_hash IS NOT NULL THEN 1 ELSE 0 END) \
             FROM refs GROUP BY kind ORDER BY count(*) DESC",
            &[] as &[&dyn rusqlite::ToSql],
            |r| {
                Ok(RefExt {
                    ext: r.get(0)?,
                    total: r.get::<_, i64>(1)? as usize,
                    resolved: r.get::<_, Option<i64>>(2)?.unwrap_or(0) as usize,
                    dangling_names: 0,
                })
            },
        )?;
        // Fold in the dangling-name count per extension, so one row can state both "how
        // many citation edges" and "how many distinct names never landed". Two different
        // denominators that must not be conflated: `.tga` has 30,585 edges but only
        // 8,672 distinct dangling names.
        for row in by_ext.iter_mut() {
            row.dangling_names = self
                .con
                .query_row(
                    "SELECT count(*) FROM dangling WHERE COALESCE(ext,'') = ?1",
                    [&row.ext],
                    |r| r.get::<_, i64>(0),
                )
                .unwrap_or(0) as usize;
        }
        Ok(RefHealth {
            refs_total: one("SELECT count(*) FROM refs"),
            refs_resolved: one("SELECT count(*) FROM refs WHERE to_hash IS NOT NULL"),
            dangling_names: one("SELECT count(*) FROM dangling"),
            assets_citing: one("SELECT count(DISTINCT from_hash) FROM refs"),
            assets_citing_resolved: one(
                "SELECT count(DISTINCT from_hash) FROM refs WHERE to_hash IS NOT NULL",
            ),
            by_ext,
        })
    }

    /// Names the client cites that land on nothing we hold, most-cited first. A name
    /// cited many times and resolving nowhere is a fact about the shipped package, not a
    /// gap in the parser, so it is listed rather than hidden.
    pub fn top_dangling(&self, limit: usize) -> Result<Vec<DanglingName>> {
        self.rows(
            "SELECT name, COALESCE(ext, ''), n_refs, n_src, COALESCE(cls, '') \
             FROM dangling ORDER BY n_refs DESC, name LIMIT ?1",
            &[&(limit as i64)],
            |r| {
                Ok(DanglingName {
                    name: r.get(0)?,
                    ext: r.get(1)?,
                    citations: r.get::<_, Option<i64>>(2)?.unwrap_or(0) as usize,
                    sources: r.get::<_, Option<i64>>(3)?.unwrap_or(0) as usize,
                    class: r.get(4)?,
                })
            },
        )
    }

    /// How many groups carry a stem at all — the denominator for every "named" claim.
    pub fn stem_counts(&self) -> Result<(usize, usize)> {
        let with: i64 = self
            .con
            .query_row("SELECT count(*) FROM agroups WHERE stem <> ''", [], |r| r.get(0))
            .unwrap_or(0);
        let total: i64 = self
            .con
            .query_row("SELECT count(*) FROM agroups", [], |r| r.get(0))
            .unwrap_or(0);
        Ok((with as usize, total as usize))
    }

    /// `fp_asset` alone — the packing-sensitive content digest, for "did the content move".
    pub fn fingerprint(&self, gid: i64) -> Result<Option<String>> {
        Ok(self
            .con
            .query_row(
                "SELECT fp_asset FROM asset_fingerprint WHERE gid = ?1",
                [&gid],
                |r| r.get::<_, Option<String>>(0),
            )
            .unwrap_or(None))
    }

    /// All eight fingerprint columns, for callers that print the per-role breakdown.
    pub fn fingerprints(&self, gid: i64) -> Result<Option<Fingerprints>> {
        let mut got = self.rows(
            "SELECT fp_asset, fp_model, fp_skeleton, fp_mesh, fp_material, fp_animation, \
                    fp_texture, fp_names FROM asset_fingerprint WHERE gid = ?1",
            &[&gid],
            |r| {
                let t = |i: usize| r.get::<_, Option<String>>(i).map(|x| x.unwrap_or_default());
                Ok(Fingerprints {
                    asset: t(0)?,
                    model: t(1)?,
                    skeleton: t(2)?,
                    mesh: t(3)?,
                    material: t(4)?,
                    animation: t(5)?,
                    texture: t(6)?,
                    names: t(7)?,
                })
            },
        )?;
        Ok(got.pop())
    }

    /// The group's content and packing identity. Absent for groups that were never
    /// identified, which is a normal state and not an error.
    pub fn identity(&self, gid: i64) -> Result<Option<Identity>> {
        let mut got = self.rows(
            "SELECT id_asset, id_pack FROM asset_identity WHERE gid = ?1",
            &[&gid],
            |r| {
                let t = |i: usize| r.get::<_, Option<String>>(i).map(|x| x.unwrap_or_default());
                Ok(Identity { id_asset: t(0)?, id_pack: t(1)? })
            },
        )?;
        Ok(got.pop())
    }

    /// Members with their content digest and stored-record checksum, dropping any member
    /// the catalog cannot name — an unnamed row would print as an empty line.
    pub fn member_digests(&self, gid: i64) -> Result<Vec<MemberDigest>> {
        self.rows(
            "SELECT m.role, x.name, b.sha, x.filecrc FROM amembers m \
             LEFT JOIN resources x ON x.hash = m.hash \
             LEFT JOIN blobs b ON b.hash = x.hash WHERE m.gid = ?1",
            &[&gid],
            |r| {
                Ok(MemberDigest {
                    role: r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                    name: r.get::<_, Option<String>>(1)?.unwrap_or_default(),
                    sha: r.get::<_, Option<String>>(2)?.unwrap_or_default(),
                    crc: match r.get::<_, Option<i64>>(3)? {
                        Some(c) => format!("{c:08x}"),
                        None => String::new(),
                    },
                })
            },
        )
        .map(|v| v.into_iter().filter(|m| !m.name.is_empty()).collect())
    }

    /// Resolve a virtual path to its resource hash.
    pub fn hash_by_path(&self, path: &str) -> Result<Option<u64>> {
        let found: Option<String> = self
            .con
            .query_row(
                "SELECT hash FROM resources WHERE path = ?1 LIMIT 1",
                [path],
                |r| r.get::<_, Option<String>>(0),
            )
            .unwrap_or(None);
        found.map(|h| hash_of(&h)).transpose()
    }

    /// 有哪些地图（按 `.scene` 格子文件数排序的目录清单）。
    ///
    /// 口径：**有至少一个格子文件的目录**，不是"客户端承认存在的地图全集"——
    /// 两者在本机是否相等未证，界面引用这条时必须带上"按下过东西的格子数"这句
    /// 分母说明（红线：统计数字要有口径）。
    pub fn map_dirs(&self, limit: usize) -> Result<Vec<(String, usize)>> {
        let lim = limit.min(i64::MAX as usize) as i64;
        self.rows(
            "SELECT dir, COUNT(*) FROM resources              WHERE ext = '.scene' AND dir LIKE 'mobile_maps/%'              GROUP BY dir ORDER BY COUNT(*) DESC, dir LIMIT ?1",
            &[&lim],
            |r| {
                let n: i64 = r.get(1)?;
                Ok((r.get::<_, String>(0)?, n as usize))
            },
        )
    }

    /// 一张地图下的全部格子文件。空的 `dir` 一律不查：那等于"没有任何路径"，
    /// 按它匹配会把别人的格子当成这张图的（同 `textures_in_dir` 的理由）。
    pub fn scene_grids(&self, dir: &str) -> Result<Vec<(u64, String)>> {
        if dir.trim().is_empty() {
            return Ok(Vec::new());
        }
        self.rows(
            "SELECT hash, name FROM resources WHERE dir = ?1 AND ext = '.scene' ORDER BY name",
            &[&dir],
            |r| {
                let h: String = r.get(0)?;
                Ok((hash_of(&h).unwrap_or(0), r.get::<_, String>(1)?))
            },
        )
    }

    /// 按**裸文件名**在指定目录里解析哈希。
    ///
    /// 格子里的物件名是 `w1351_dl_bajiao_001.mesh` 这种裸名（带扩展名、不带目录），
    /// 而 `hash_by_path` 要整路径，直接喂必查空——实测 256 条里只有 1 条能对上的
    /// 差异就出在这。所以地图这条路必须按 `dir + name` 查。
    pub fn hash_by_name_in(&self, dir: &str, name: &str) -> Result<Option<u64>> {
        if dir.trim().is_empty() || name.trim().is_empty() {
            return Ok(None);
        }
        let found: Option<String> = self
            .con
            .query_row(
                "SELECT hash FROM resources WHERE dir = ?1 AND name = ?2 LIMIT 1",
                [&dir, &name],
                |r| r.get::<_, Option<String>>(0),
            )
            .unwrap_or(None);
        found.map(|h| hash_of(&h)).transpose()
    }

    /// 骨架静态区反解（`preview::rest`）要用的同组动作：`<网格目录>/ani/` 下的
    /// 第一条 `.ani`（按名排序取一；静态区跨动作共享，任取一条即可）。
    /// 没有动作文件的组返回 `None`——调用方维持「无动画」的现状，不算错。
    pub fn first_ani_in(&self, dir: &str) -> Result<Option<(u64, String)>> {
        if dir.trim().is_empty() {
            return Ok(None);
        }
        match self.con.query_row(
            "SELECT hash, name FROM resources WHERE dir = ?1 AND ext = '.ani' ORDER BY name LIMIT 1",
            [&dir],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
        ) {
            Ok((h, name)) => Ok(Some((hash_of(&h).unwrap_or(0), name))),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(Error::Sql(e.to_string())),
        }
    }

    pub fn by_type(&self, rtype: &str, limit: usize) -> Result<Vec<Asset>> {        let sql = format!("SELECT {ASSET_COLS} FROM resources WHERE type = ?1 ORDER BY hash LIMIT ?2");
        let lim = limit.min(i64::MAX as usize) as i64;
        self.rows(&sql, &[&rtype, &lim], Asset::from_row)
    }

    pub fn named_of_type(&self, rtype: &str) -> Result<(usize, usize)> {
        let total: i64 = self
            .con
            .query_row("SELECT count(*) FROM resources WHERE type = ?1", [rtype], |r| {
                r.get::<_, i64>(0)
            })
            .map_err(|e| Error::Sql(e.to_string()))?;
        let named: i64 = self
            .con
            .query_row(
                "SELECT count(*) FROM resources WHERE type = ?1 AND named = 1",
                [rtype],
                |r| r.get::<_, i64>(0),
            )
            .map_err(|e| Error::Sql(e.to_string()))?;
        Ok((named as usize, total as usize))
    }

    pub fn counts(&self) -> Result<Vec<KindCount>> {
        let mut v = self.rows(
            "SELECT type, count(*) FROM resources GROUP BY type",
            &[] as &[&dyn rusqlite::ToSql],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)? as usize)),
        )?;
        v.sort_by(|a, b| b.1.cmp(&a.1));
        Ok(v)
    }

    /// What a resource references, with each name resolved back to a hash when the
    /// catalog could do so unambiguously.
    pub fn refs_from(&self, hash: u64) -> Result<Vec<Reference>> {
        let key = format!("{hash:016x}");
        self.rows(
            "SELECT r.name, r.kind, r.to_hash, x.path, r.ambig FROM refs r \
             LEFT JOIN resources x ON x.hash = r.to_hash WHERE r.from_hash = ?1 \
             ORDER BY r.kind, r.name",
            &[&key],
            |r| {
                let to: Option<String> = r.get(2)?;
                Ok(Reference {
                    name: r.get(0)?,
                    kind: r.get(1)?,
                    to: match &to {
                        Some(s) => hash_of(s).ok(),
                        None => None,
                    },
                    to_path: r.get(3)?,
                    ambiguous: r.get::<_, i64>(4)? != 0,
                })
            },
        )
    }

    /// Unfiltered inbound edges. Forensic only: 26,328 of the 98,504 rows in `refs`
    /// point from an asset to its own members, so this must never back a panel.
    pub fn raw_refs_to(&self, hash: u64) -> Result<Vec<(String, String)>> {
        let key = format!("{hash:016x}");
        self.rows(
            "SELECT r.from_path, r.kind FROM refs r WHERE r.to_hash = ?1 ORDER BY r.from_path LIMIT 200",
            &[&key],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
        )
    }

    /// Every file whose *content* cites this hash by name, as `(from_path, kind)`.
    ///
    /// Deliberately separate from `external_users`: that one strips self-edges and
    /// same-group members to answer "who uses this", which is a usage claim. This one
    /// answers the narrower, always-true question "whose text mentions this" — so a
    /// group's own members are kept. The two must never be conflated, which is why they
    /// are two functions rather than one with a flag.
    ///
    /// Rows with a path sort first. 5,350 of 98,504 edges have no recorded path — they
    /// are group-internal, and an entry with nothing to name is not evidence worth
    /// showing, so a truncated list must not spend its slots on them.
    pub fn cited_by(&self, hash: u64, limit: usize) -> Result<Vec<(String, String)>> {
        let key = format!("{hash:016x}");
        self.rows(
            "SELECT COALESCE(r.from_path, ''), COALESCE(r.kind, '') FROM refs r \
             WHERE r.to_hash = ?1 \
             ORDER BY (COALESCE(r.from_path, '') = '') ASC, r.from_path LIMIT ?2",
            &[&key, &(limit as i64)],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
        )
    }

    /// Who wrote this exact name into their file.悬空名字没有 hash，只能按名字反查；
    /// 结果仍是「提到」这一事实，不代表它们共用了同一份资源。
    pub fn cited_by_name(&self, name: &str, limit: usize) -> Result<Vec<(String, String)>> {
        self.rows(
            "SELECT COALESCE(r.from_path, ''), COALESCE(r.kind, '') FROM refs r \
             WHERE r.name = ?1 \
             ORDER BY (COALESCE(r.from_path, '') = '') ASC, r.from_path LIMIT ?2",
            &[&name, &(limit as i64)],
            |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
        )
    }

    /// How many distinct assets cite at least one name we resolved. The usable graph's
    /// size, as opposed to the raw row count.
    pub fn assets_citing_resolved(&self) -> Result<usize> {
        self.con
            .query_row(
                "SELECT count(DISTINCT from_hash) FROM refs WHERE to_hash IS NOT NULL",
                [],
                |r| r.get::<_, i64>(0),
            )
            .map(|n| n as usize)
            .map_err(|e| Error::Sql(e.to_string()))
    }

    /// The most-cited hashes that *do* resolve, with how many distinct files mention each.
    /// The mirror of `top_dangling`: what the citation graph actually holds, most-evidenced
    /// first. Every row is a resolved edge, so this is a fact, not an inference.
    pub fn top_cited(&self, limit: usize) -> Result<Vec<(u64, String, usize)>> {
        self.rows(
            "SELECT r.to_hash, max(COALESCE(r.name, '')), count(DISTINCT r.from_hash) \
             FROM refs r WHERE r.to_hash IS NOT NULL \
             GROUP BY r.to_hash ORDER BY count(DISTINCT r.from_hash) DESC LIMIT ?1",
            &[&(limit as i64)],
            |r| {
                let key: String = r.get(0)?;
                Ok((
                    hash_of(&key).unwrap_or(0),
                    r.get(1)?,
                    r.get::<_, i64>(2)? as usize,
                ))
            },
        )
    }

    /// Who else uses this asset, with the evidence-polluting edges removed.
    ///
    /// This is the single implementation the report and the workbench both call — there
    /// used to be a second one in `asset_report.rs` that filtered `from_path` while this
    /// one backfilled it with the referrer's stem, so the same asset could read as having
    /// users in one product and none in the other.
    ///
    /// Inbound edges are taken against this group's own member hashes, then dropped when
    /// they are self-edges (1,595 `.ske` rows point at themselves) or come from any
    /// member of the same group (26,328 rows, which is what made an NPC read as "used by
    /// its own texture"). The member test, not the hub test, is the load-bearing one: a
    /// referrer can sit inside the group without being its hub.
    ///
    /// `from_path` must be non-empty. A referrer with no recorded path is not evidence
    /// that can be shown — substituting the stem would invent a filename the catalog
    /// never had, which is exactly the guess the rest of this tool refuses to make.
    pub fn external_users(&self, gid: i64) -> Result<Vec<UseEdge>> {
        self.rows(
            "SELECT DISTINCT r.from_hash, r.from_path, r.kind, ag.id FROM refs r \
             JOIN amembers m ON m.hash = r.to_hash AND m.gid = ?1 \
             LEFT JOIN agroups ag ON ag.hub = r.from_hash \
             WHERE r.from_hash <> r.to_hash \
               AND r.from_path IS NOT NULL AND r.from_path <> '' \
               AND NOT EXISTS (SELECT 1 FROM amembers x WHERE x.gid = ?1 AND x.hash = r.from_hash) \
               AND (ag.id IS NULL OR ag.id <> ?1) \
             ORDER BY r.from_path LIMIT 200",
            &[&gid],
            |r| {
                let fh: String = r.get(0)?;
                Ok(UseEdge {
                    from_hash: u64::from_str_radix(&fh, 16).unwrap_or(0),
                    from_path: r.get(1)?,
                    kind: r.get(2)?,
                    from_gid: r.get(3)?,
                })
            },
        )
    }

    /// The texture references of one group: `(distinct names, names that resolve)`.
    ///
    /// This is the single definition both the workbench and the baseline grade with.
    /// They used to compute it differently — the workbench filtered rows whose *display
    /// label* was `贴图`, the baseline counted `agroup_names` rows ending in a texture
    /// extension — and the two disagreed about two wardrobe icons (`gid` 1994 and 2118),
    /// enough to make the baseline report grade A where the workbench reported none.
    ///
    /// Distinct by name because a group can cite one texture from several members. The
    /// resolution flag is `max(...)`: a name counts as located when *any* citation of it
    /// landed, which is what "we hold this texture" means.
    pub fn texture_refs(&self, gid: i64) -> Result<(usize, usize)> {
        self.con
            .query_row(
                "SELECT count(*), COALESCE(sum(res), 0) FROM ( \
                   SELECT r.name, max(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END) AS res \
                   FROM refs r JOIN amembers m ON m.hash = r.from_hash AND m.gid = ?1 \
                   WHERE r.kind IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp') \
                   GROUP BY r.name)",
                [&gid],
                |r| {
                    Ok((
                        r.get::<_, i64>(0)? as usize,
                        r.get::<_, i64>(1)? as usize,
                    ))
                },
            )
            .map_err(|e| Error::Sql(e.to_string()))
    }

    /// Every outbound reference raised by any member of the group, not just the hub.
    ///
    /// The shipped materials hang their texture names off member `.mtl` rows, so a
    /// texture reachable only through the hub's own `refs` is the exception, not the
    /// rule. Deduplicated by name, first writer wins.
    pub fn refs_from_group(&self, gid: i64) -> Result<Vec<Reference>> {
        self.rows(
            "SELECT r.name, r.kind, r.to_hash, x.path, r.ambig FROM refs r \
             JOIN amembers m ON m.hash = r.from_hash AND m.gid = ?1 \
             LEFT JOIN resources x ON x.hash = r.to_hash \
             GROUP BY r.name ORDER BY r.kind, r.name",
            &[&gid],
            |r| {
                let to: Option<String> = r.get(2)?;
                Ok(Reference {
                    name: r.get(0)?,
                    kind: r.get(1)?,
                    to: match &to {
                        Some(s) => hash_of(s).ok(),
                        None => None,
                    },
                    to_path: r.get(3)?,
                    ambiguous: r.get::<_, i64>(4)? != 0,
                })
            },
        )
    }

}
