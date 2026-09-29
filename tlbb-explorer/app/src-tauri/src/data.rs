//! The workbench's whole knowledge of the shipped client: one read-only catalog handle,
//! the containers mapped in once, a hash→index-record map, and the progressively warmed
//! card list.
//!
//! Two rules drive the design. Nothing is written outside this `app/` tree — every
//! container and `resources.db` handle is opened read-only. And nothing is presented as
//! resolved unless it was actually read back and decoded, so `hub_decoded` is the result
//! of a real decode, not a heuristic.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Instant;

use base64::Engine;
use tlbb_core::catalog::evidence::{self, Grade, Signals};
use tlbb_core::catalog::{labels, search, Asset, Catalog, Group, Member, Reference};
use tlbb_core::jpak::index::Record;
use tlbb_core::jpak::Pak;
use tlbb_core::jmt1::{self, Codec};
use tlbb_core::payload;
use tlbb_core::preview;

use crate::mesh_view::{self, MeshOutline};
use crate::model::{
    Card, CitedByView, CitationView, Count, Detail, DanglingView, Filter, Image, MemberItem,
    Option2, Page, RefExtView, RefView, RefItem, Stats, Tech,
};
use crate::present;

/// Groups per warm-up batch: small enough that the grid fills progressively, large
/// enough that the per-batch thread scope stays cheap.
pub const BATCH: usize = 256;
/// Shards in the background pass. The catalog queries dominate (see `refs_from`), so the
/// shell spreads them over the machine instead of serialising on one read handle.
pub fn shards() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .clamp(4, 16)
}

pub const SCENARIOS: &[&str] = &["角色", "场景", "特效", "界面", "物品", "其他"];
pub const GRADES: &[&str] = &["A", "B", "C", "D"];

/// 三张解码缓存的顶格条数。超过就整体清空——这些全是「再算一遍就有」的
/// 纯缓存，清空不损正确性，只多付一次冷解码；换来的是内存有顶，
/// 不会「用一晚上越用越胀」。量级：blobs 顶格 512 张长边 512 的 PNG ≈ 百 MB。
const BLOB_CAP: usize = 512;
const GROUP_BLOB_CAP: usize = 1024;
const OUTLINE_CAP: usize = 8192;

/// 带顶的插入。不做真 LRU：整体清空的实现是十行，收益（内存封顶）一样。
fn capped_insert<K: Eq + std::hash::Hash, V>(m: &mut HashMap<K, V>, k: K, v: V, cap: usize) {
    if m.len() >= cap {
        m.clear();
    }
    m.insert(k, v);
}

/// Display order of the composition chips, mirrored from the card report.
const ROLE_RANK: &[&str] = &[
    "model",
    "mesh",
    "material",
    "skeleton",
    "animation",
    "texture",
    "scene",
    "map",
    "effect",
    "config",
    "audio",
    "other",
];

/// A catalog query that must not take a card down with it: a group whose rows cannot be
/// read is still listed, it simply says so.
fn one<T: Default>(r: tlbb_core::catalog::sqlite::Result<T>) -> T {
    match r {
        Ok(v) => v,
        Err(e) => {
            eprintln!("清单查询失败：{e}");
            T::default()
        }
    }
}

fn hex(h: u64) -> String {
    format!("{h:016x}")
}

pub fn unhex(s: &str) -> Option<u64> {
    u64::from_str_radix(s.trim().trim_start_matches("0x"), 16).ok()
}

/// A resource's payload, rendered to pixels.
pub struct Blob {
    bytes: Vec<u8>,
    pub width: u32,
    pub height: u32,
    kind: &'static str,
}

impl Blob {
    fn image(&self) -> Image {
        Image {
            url: format!(
                "data:image/{};base64,{}",
                self.kind,
                base64::engine::general_purpose::STANDARD.encode(&self.bytes)
            ),
            width: self.width,
            height: self.height,
            format: self.kind.to_string(),
        }
    }
}

/// Everything learned about one group. Warmed once, then cloned into the view models.
#[derive(Clone)]
pub struct Lite {
    pub group: Group,
    pub name: String,
    pub subtitle: String,
    pub scenario: &'static str,
    pub kind_zh: String,
    pub tags: Vec<String>,
    pub parts: Vec<Count>,
    pub placeholder: &'static str,
    pub grade: Grade,
    pub gaps: Vec<&'static str>,
    pub refs: Vec<RefItem>,
    pub located: usize,
    pub ref_total: usize,
    pub preview_candidates: Vec<u64>,
    pub hub_decoded: bool,
    pub rules: Vec<String>,
    pub members: Vec<Member>,
}

impl Lite {
    fn card(&self) -> Card {
        let label = self.grade.label();
        let letter = label.chars().next().unwrap_or('D');
        let (word, note) = present::grade_words(label);
        Card {
            gid: self.group.id,
            name: self.name.clone(),
            subtitle: self.subtitle.clone(),
            kind: self.kind_zh.clone(),
            scenario: self.scenario.to_string(),
            grade: letter.to_string(),
            grade_word: word.to_string(),
            grade_note: note.to_string(),
            tags: self.tags.clone(),
            parts: self.parts.clone(),
            placeholder: self.placeholder.to_string(),
            member_total: self.members.len(),
            ref_total: self.ref_total,
            located_total: self.located,
            named: present::is_named(&self.group),
            preview_hash: self.preview_candidates.first().copied().map(hex),
        }
    }
}

/// What one warm-up batch learned from the catalog, before the decode pass.
struct Row {
    group: Group,
    base: Signals,
    members: Vec<Member>,
    refs: Vec<RefItem>,
    parts: Vec<Count>,
    tags: Vec<String>,
    rules: Vec<String>,
    preview_candidates: Vec<u64>,
}

impl Row {
    /// A row with nothing in it. The card still lists, and every part of it says 未读到
    /// rather than being filled in with a guess.
    fn empty(group: Group) -> Row {
        Row {
            base: Signals::default(),
            group,
            members: Vec::new(),
            refs: Vec::new(),
            parts: Vec::new(),
            tags: Vec::new(),
            rules: Vec::new(),
            preview_candidates: Vec::new(),
        }
    }
}

/// `refs.kind` is the shipped extension. Words the player can read, and never a guess
/// about what the file contains.
fn ref_kind_word(kind: &str) -> &'static str {
    match kind.rsplit('.').next().unwrap_or("").to_ascii_lowercase().as_str() {
        "tga" | "dds" | "png" | "jpg" | "jpeg" | "bmp" | "webp" => "贴图",
        "mtl" => "材质",
        "mdl" => "模型",
        "mesh" => "网格",
        "ske" => "骨骼",
        "ani" | "anis" => "动作",
        "scene" | "map" => "场景",
        "pu" => "特效",
        _ => "其他文件",
    }
}

pub struct Container {
    pak: Pak,
}

pub struct AppData {
    root: PathBuf,
    catalog_file: PathBuf,
    cat: Mutex<Catalog>,
    containers: Vec<Container>,
    by_name: HashMap<String, usize>,
    by_hash: HashMap<u64, Vec<(usize, Record)>>,
    groups: Vec<Group>,
    total: usize,
    lite: Mutex<HashMap<i64, Arc<Lite>>>,
    scanned: AtomicUsize,
    ready: AtomicBool,
    warming: AtomicBool,
    /// Where the warm-up's wall time went, summed across shards.
    pub t_collect: AtomicUsize,
    pub t_decode: AtomicUsize,
    blobs: Mutex<HashMap<u64, Option<Arc<Blob>>>>,
    group_blobs: Mutex<HashMap<i64, Option<Arc<Blob>>>>,
    outlines: Mutex<HashMap<i64, Option<Arc<MeshOutline>>>>,
}

impl AppData {
    /// Open everything that can fail loudly, before the window is shown.
    pub fn open(root: impl Into<PathBuf>, db: impl Into<PathBuf>) -> Result<Arc<Self>, String> {
        let (root, catalog_file) = (root.into(), db.into());
        if !catalog_file.exists() {
            return Err(format!("找不到资源清单文件：{}", catalog_file.display()));
        }
        let t0 = Instant::now();
        let cat = Catalog::open_ro(&catalog_file).map_err(|e| e.to_string())?;
        let groups = cat.groups(50_000).map_err(|e| e.to_string())?;
        let total = groups.len();

        let mut containers: Vec<Container> = Vec::new();
        let mut by_name: HashMap<String, usize> = HashMap::new();
        if let Ok(entries) = std::fs::read_dir(&root) {
            for e in entries.flatten() {
                let p = e.path();
                if p.extension().map(|x| !x.eq_ignore_ascii_case("pak")).unwrap_or(true) {
                    continue;
                }
                let Some(stem) = p.file_stem().map(|s| s.to_string_lossy().to_string()) else {
                    continue;
                };
                if let Ok(pak) = Pak::open(&p) {
                    by_name.insert(stem, containers.len());
                    containers.push(Container { pak });
                }
            }
        }
        let mut by_hash: HashMap<u64, Vec<(usize, Record)>> = HashMap::new();
        for (i, c) in containers.iter().enumerate() {
            for rec in c.pak.records() {
                if rec.original == 0 {
                    continue;
                }
                by_hash.entry(rec.hash).or_default().push((i, rec));
            }
        }
        eprintln!(
            "open: {} groups · {} containers · {} index records in {:.1}s",
            total,
            containers.len(),
            by_hash.values().map(|v| v.len()).sum::<usize>(),
            t0.elapsed().as_secs_f64()
        );

        let app = Arc::new(Self {
            root,
            catalog_file,
            cat: Mutex::new(cat),
            containers,
            by_name,
            by_hash,
            groups,
            total,
            lite: Mutex::new(HashMap::new()),
            scanned: AtomicUsize::new(0),
            ready: AtomicBool::new(false),
            warming: AtomicBool::new(false),
            t_collect: AtomicUsize::new(0),
            t_decode: AtomicUsize::new(0),
            blobs: Mutex::new(HashMap::new()),
            group_blobs: Mutex::new(HashMap::new()),
            outlines: Mutex::new(HashMap::new()),
        });
        // 上次预热的成果还在就直取：资产侧秒级就绪，浏览侧照旧零等待。
        app.try_load_warm_cache();
        Ok(app)
    }

    pub fn triage(&self) -> (usize, usize, usize) {
        (
            self.total,
            self.containers.len(),
            self.by_hash.values().map(|v| v.len()).sum(),
        )
    }

    /// One catalog query, failures swallowed into the type's default: a card that is
    /// merely thin must still render.
    fn q<T: Default>(&self, f: impl FnOnce(&Catalog) -> tlbb_core::catalog::sqlite::Result<T>) -> T {
        match self.cat.lock() {
            Ok(c) => match f(&c) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("catalog: {e}");
                    T::default()
                }
            },
            Err(_) => T::default(),
        }
    }

    /// 和 `q` 同一把锁，但**失败如实报出来**。`q` 把错误吞成 Default 是为了「卡片再薄
    /// 也要能渲染」；地图命令照它做就会把一次 SQL 失败显示成「这张图一个格子都没有」，
    /// 那是假空不是空（红线：加载失败不许伪成功）。
    pub(crate) fn try_q<T>(
        &self,
        f: impl FnOnce(&Catalog) -> tlbb_core::catalog::sqlite::Result<T>,
    ) -> Result<T, String> {
        let c = self.cat.lock().map_err(|_| "目录锁被一次 panic 占着，查不了".to_string())?;
        f(&c).map_err(|e| format!("查目录失败：{e}"))
    }

    pub(crate) fn asset(&self, hash: u64) -> Option<Asset> {
        self.q(|c| c.asset(hash))
    }

    /// Locate and read one resource: the catalog says which container and payload offset,
    /// the container's own index record says how to decrypt and expand it.
    pub(crate) fn read(&self, hash: u64) -> Option<Vec<u8>> {
        let asset = self.asset(hash)?;
        let slot = *self.by_name.get(&asset.pak)?;
        let recs = self.by_hash.get(&hash)?;
        let same = recs.iter().filter(|(i, _)| *i == slot).collect::<Vec<_>>();
        let rec = same
            .iter()
            .copied()
            .find(|(_, r)| r.offset as i64 == asset.offset)
            .or_else(|| same.first().copied())
            .map(|(_, r)| *r)?;
        payload::decode(&self.containers[slot].pak, &rec).ok().map(|d| d.bytes)
    }

    /// Decode a resource into pixels, or `None` when it is not an image we can render.
    /// Negative results are cached so a card without pixels is probed once.
    fn texture(&self, hash: u64) -> Option<Arc<Blob>> {
        if let Ok(c) = self.blobs.lock() {
            if let Some(hit) = c.get(&hash) {
                return hit.clone();
            }
        }
        let blob = self
            .read(hash)
            .and_then(|raw| jmt1::decode(&raw).ok())
            .and_then(|tex| match tex.codec {
                Codec::Webp => tex.webp.map(|w| Blob {
                    bytes: w,
                    width: tex.width as u32,
                    height: tex.height as u32,
                    kind: "webp",
                }),
                Codec::Unknown => None,
                _ => {
                    // 一律先降到长边 512 再编码：这张图的归宿是预览和缩略图，
                    // 原尺寸 2048² 的 RGBA 是 16MB 位图、PNG 编码后还有几 MB，
                    // 为一个 48px 的格子付这笔账，滚几屏内存就能上 GB。
                    let (rgba, w, h) =
                        preview::scale_rgba(&tex.rgba, tex.width as usize, tex.height as usize, 512);
                    preview::png_bytes(w as u16, h as u16, &rgba, true)
                        .ok()
                        .map(|b| Blob {
                            bytes: b,
                            width: w as u32,
                            height: h as u32,
                            kind: "png",
                        })
                }
            })
            .map(Arc::new);
        if let Ok(mut c) = self.blobs.lock() {
            capped_insert(&mut c, hash, blob.clone(), BLOB_CAP);
        }
        blob
    }

    fn first_image(&self, candidates: &[u64]) -> Option<Arc<Blob>> {
        candidates.iter().take(6).find_map(|h| self.texture(*h))
    }

    /// The group's own image, resolving candidates on first sight and remembering it.
    pub fn group_image(&self, gid: i64) -> Option<Image> {
        if let Ok(c) = self.group_blobs.lock() {
            if let Some(hit) = c.get(&gid) {
                return hit.as_ref().map(|b| b.image());
            }
        }
        let found = self
            .lite_of(gid)
            .and_then(|l| self.first_image(&l.preview_candidates));
        if let Ok(mut c) = self.group_blobs.lock() {
            capped_insert(&mut c, gid, found.clone(), GROUP_BLOB_CAP);
        }
        found.map(|b| b.image())
    }

    /// 列表行的几何缩略图：组里第一个真能解出几何的网格成员，投影成 48×48 格子。
    /// 与 `group_image` 同一套「负结果也缓存」的理由：没几何的行滚回视口不能再解一遍。
    pub fn group_outline(&self, gid: i64) -> Result<Option<Arc<MeshOutline>>, String> {
        if let Ok(c) = self.outlines.lock() {
            if let Some(hit) = c.get(&gid) {
                return Ok(hit.clone());
            }
        }
        let found = self.first_outline(gid)?;
        if let Ok(mut c) = self.outlines.lock() {
            capped_insert(&mut c, gid, found.clone(), OUTLINE_CAP);
        }
        Ok(found)
    }

    fn first_outline(&self, gid: i64) -> Result<Option<Arc<MeshOutline>>, String> {
        let Some(l) = self.lite_of(gid) else {
            return Ok(None);
        };
        // 只试前 6 个网格成员，和 first_image 同一个数：组里成员再多，
        // 缩略图也只是「有没有几何」的证据，不是成员普查。
        for m in l.members.iter().filter(|m| m.role == "mesh").take(6) {
            let Some(raw) = self.read(m.hash) else {
                continue;
            };
            let Ok(g) = preview::parse_geometry(&raw) else {
                continue;
            };
            if g.positions.is_empty() {
                continue;
            }
            let path = m
                .path
                .clone()
                .unwrap_or_else(|| hex(m.hash));
            return Ok(Some(Arc::new(mesh_view::outline_of(&g, path))));
        }
        Ok(None)
    }

    pub fn image_of(&self, hash: u64) -> Option<Image> {
        self.texture(hash).map(|b| b.image())
    }

    /// Resolve a client mesh and decode only its verified geometry fields.
    /// The Inspector already resolved the slot to a hash, so that is the preferred key:
    /// `.mdl` string tables carry bare file names while `resources.path` is the full
    /// client path, and matching one against the other is how a preview ends up empty.
    /// Anything unresolved comes back as a human-readable error rather than a guess.
    pub fn mesh_geometry(
        &self,
        requested: &str,
        hash: Option<&str>,
    ) -> Result<(String, preview::MeshGeometry), String> {
        let input = requested.trim();
        let label = if input.is_empty() { "这个网格" } else { input };
        let key = match hash.map(str::trim).filter(|s| !s.is_empty()).and_then(unhex) {
            Some(h) => h,
            None => {
                let mut candidates = vec![label.to_string()];
                if !label.to_ascii_lowercase().ends_with(".mesh") {
                    candidates.push(format!("{label}.mesh"));
                }
                candidates
                    .iter()
                    .find_map(|path| self.q(|c| c.hash_by_path(path)))
                    .ok_or_else(|| format!("资源清单里没有找到网格文件：{label}"))?
            }
        };
        let asset = self
            .asset(key)
            .ok_or_else(|| format!("资源清单里没有找到网格内容：{label}"))?;
        let path = asset.path.clone().unwrap_or_else(|| label.to_string());
        let raw = self
            .read(key)
            .ok_or_else(|| format!("无法从客户端容器读取网格：{path}"))?;
        let geometry =
            preview::parse_geometry(&raw).map_err(|e| format!("网格几何解析失败：{e}"))?;
        Ok((path, geometry))
    }

    pub fn lite_of(&self, gid: i64) -> Option<Arc<Lite>> {
        self.lite.lock().ok()?.get(&gid).cloned()
    }

    pub fn scanned(&self) -> usize {
        self.scanned.load(Ordering::Relaxed)
    }

    pub fn ready(&self) -> bool {
        self.ready.load(Ordering::Relaxed)
    }

    /// Build the card list in parallel shards so the window never waits on I/O. Each
    /// shard opens its own read-only handle on the catalog: nothing writes to
    /// `resources.db` from here, so the extra handles cost nothing and let the queries
    /// and the decodes run side by side.
    pub fn warm(self: &Arc<Self>) -> Arc<Self> {
        // 已就绪就别再跑一遍：懒预热后 stats/list/search 都会顺手调 warm()，
        // 这里必须便宜到可以无脑调。
        if self.ready.load(Ordering::SeqCst) {
            return Arc::clone(self);
        }
        if self
            .warming
            .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .is_err()
        {
            return Arc::clone(self);
        }
        let me = Arc::clone(self);
        std::thread::spawn(move || {
            let t0 = Instant::now();
            let lanes = shards();
            let per = me.total.div_ceil(lanes).max(BATCH);
            std::thread::scope(|scope| {
                for shard in me.groups.chunks(per) {
                    let me = &me;
                    scope.spawn(move || {
                        let owned = Catalog::open_ro(&me.catalog_file).ok();
                        for chunk in shard.chunks(BATCH) {
                            let tc = Instant::now();
                            let rows: Vec<Row> = match &owned {
                                Some(cat) => chunk.iter().map(|g| me.collect(cat, g)).collect(),
                                // A shard that could not open its own handle falls back
                                // to the shared one instead of dropping groups.
                                None => chunk.iter().map(|g| me.collect_locked(g)).collect(),
                            };
                            let td = Instant::now();
                            let pairs = chunk
                                .iter()
                                .zip(rows)
                                .map(|(g, row)| {
                                    let decoded = me.read(g.hub).is_some();
                                    me.build(row, decoded)
                                })
                                .collect();
                            me.t_collect.fetch_add(tc.elapsed().as_micros() as usize, Ordering::Relaxed);
                            me.t_decode.fetch_add(td.elapsed().as_micros() as usize, Ordering::Relaxed);
                            me.publish(pairs);
                        }
                    });
                }
            });
            // 预热成果落盘：下次启动直接载入，不再重付这两三分钟。
            me.save_warm_cache();
            me.ready.store(true, Ordering::SeqCst);
            eprintln!(
                "warm: {} 组 / {} 路 / 总 {:.1}s（清单查询 {:.1}s · 主体回读 {:.1}s，均为各分片累计）",
                me.total,
                lanes,
                t0.elapsed().as_secs_f64(),
                me.t_collect.load(Ordering::Relaxed) as f64 / 1e6,
                me.t_decode.load(Ordering::Relaxed) as f64 / 1e6,
            );
        });
        Arc::clone(self)
    }

    /// Read the rows a search needs before the background pass has reached them, so a
    /// Chinese query works at once rather than only after the warm-up finished.
    pub fn ensure(&self, gids: &[i64]) {
        let mut pairs: Vec<(i64, Arc<Lite>)> = Vec::new();
        if let Ok(cat) = self.cat.lock() {
            for gid in gids {
                let known = self.lite.lock().map(|l| l.contains_key(gid)).unwrap_or(true);
                let Some(g) = self.groups.iter().find(|g| g.id == *gid) else {
                    continue;
                };
                if known {
                    continue;
                }
                let row = self.collect(&cat, g);
                pairs.push(self.build(row, self.read(g.hub).is_some()));
            }
        }
        self.publish(pairs);
    }

    fn collect_locked(&self, g: &Group) -> Row {
        match self.cat.lock() {
            Ok(cat) => self.collect(&cat, g),
            Err(_) => Row::empty(g.clone()),
        }
    }

    fn build(&self, row: Row, hub_decoded: bool) -> (i64, Arc<Lite>) {
        let g = &row.group;
        // Signals come from the shared constructor so this and the baseline cannot drift.
        // `roles` are the raw `amembers.role` values in `row.members`; the display labels
        // in `row.parts` are for the UI only and would under-count distinct roles.
        let facts = evidence::EvidenceFacts {
            hub_decoded: if hub_decoded { evidence::Decode::Decoded } else { evidence::Decode::Failed },
            roles: row.members.iter().map(|m| m.role.clone()).collect(),
            members: row.members.len(),
            refs_total: row.base.refs_total,
            refs_located: row.base.refs_located,
        };
        let sig = facts.signals();
        let name = present::display_name(g);
        let tags = row.tags.clone();
        let scenario = present::scenario_of(&g.kind);
        let placeholder = present::placeholder_for(scenario, &tags);
        let lite = Arc::new(Lite {
            group: g.clone(),
            name: name.clone(),
            subtitle: present::subtitle(&name, &g.kind),
            scenario,
            kind_zh: labels::kind_zh(&g.kind).to_string(),
            tags,
            placeholder,
            parts: row.parts,
            grade: evidence::grade(&sig),
            gaps: evidence::gaps(&sig),
            refs: row.refs,
            located: sig.refs_located,
            ref_total: sig.refs_total,
            preview_candidates: row.preview_candidates,
            hub_decoded,
            rules: row.rules,
            members: row.members,
        });
        (g.id, lite)
    }

    fn publish(&self, pairs: Vec<(i64, Arc<Lite>)>) {
        if pairs.is_empty() {
            return;
        }
        let n = match self.lite.lock() {
            Ok(mut lite) => {
                for (gid, row) in pairs {
                    lite.insert(gid, row);
                }
                lite.len()
            }
            Err(_) => return,
        };
        self.scanned.store(n, Ordering::Relaxed);
    }

    /// Catalog-only half of a card: the members, the named dependencies, the tags.
    /// Everything else on the card is derived from those three, or belongs to the
    /// detail pane (`extras`).
    fn collect(&self, cat: &Catalog, g: &Group) -> Row {
        let members = one(cat.members(g.id));
        let refs: Vec<Reference> = one(cat.refs_from(g.hub));
        let names = one(cat.group_names(g.id));
        let tags_raw = one(cat.tags(g.id));

        // The group's declared names (materials *and* the textures they mention) plus
        // what the body itself references. `to` is set only where the catalog could
        // resolve a name onto a resource we actually hold — an unresolved name stays
        // 只有名字 rather than being dressed up as located.
        let hits: HashMap<String, (Option<u64>, bool)> = refs
            .iter()
            .map(|r| (r.name.to_ascii_lowercase(), (r.to, r.ambiguous)))
            .collect();
        let mut seen: Vec<String> = Vec::new();
        let mut items: Vec<RefItem> = names
            .iter()
            .map(|(n, _)| n)
            .chain(refs.iter().map(|r| &r.name))
            .filter(|n| {
                let k = n.to_ascii_lowercase();
                !seen.contains(&k) && {
                    seen.push(k);
                    true
                }
            })
            .map(|name| RefItem {
                located: hits.get(&name.to_ascii_lowercase()).map(|(t, _)| t.is_some()).unwrap_or(false),
                kind: ref_kind_word(name).to_string(),
                status: match hits.get(&name.to_ascii_lowercase()) {
                    Some((Some(_), false)) => "已找到",
                    Some((Some(_), true)) => "同名有多份",
                    _ => "只有名字",
                }
                .to_string(),
                name: name.clone(),
            })
            .collect();
        items.sort_by(|a, b| {
            b.located
                .cmp(&a.located)
                .then(a.kind.cmp(&b.kind))
                .then(a.name.cmp(&b.name))
        });
        // The texture count comes from the catalog query the baseline also uses, not from
        // `items` above. `items` is chained from `group_names` plus the hub's own refs and
        // labels each entry with a Chinese kind word, so counting it produced a different
        // answer than the baseline's for the same group (gid 1994/2118). One query, one
        // number.
        let (tex_total, tex_located) = one(cat.texture_refs(g.id));
        let base = Signals {
            refs_total: tex_total,
            refs_located: tex_located,
            ..Default::default()
        };

        let mut counted: HashMap<&'static str, usize> = HashMap::new();
        for m in &members {
            *counted.entry(labels::role_zh(&m.role)).or_default() += 1;
        }
        let mut ordered: Vec<(usize, &'static str, usize)> = counted
            .iter()
            .map(|(label, n)| {
                let rank = ROLE_RANK
                    .iter()
                    .position(|r| labels::role_zh(r) == *label)
                    .unwrap_or(ROLE_RANK.len());
                (rank, *label, *n)
            })
            .collect();
        ordered.sort();
        let parts = ordered
            .into_iter()
            .map(|(_, label, count)| Count { label: label.to_string(), count })
            .collect();

        let mut tags: Vec<String> = Vec::new();
        for (t, _conf) in &tags_raw {
            let zh = labels::tag_zh(t).into_owned();
            if !tags.contains(&zh) {
                tags.push(zh);
            }
        }

        // Where pixels can come from, in order of how much we actually hold.
        //
        // A `texture`-role member is a resource the catalog really registered against
        // this asset — the client packaged it under this group, so its hash points at
        // bytes we can decode. That is the only source that can be trusted.
        //
        // A `.tga` name in `refs` is a *string the material file contains*. The shipper
        // kept the material's name table but replaced its assets with content hashes, so
        // these names mostly map onto nothing (30,585 such refs, 25 resolve). They stay
        // as a low-priority fallback and never outrank a registered member.
        let mut preview_candidates: Vec<u64> = members
            .iter()
            .filter(|m| m.role == "texture" && m.hash != 0)
            .map(|m| m.hash)
            .collect();
        if preview_candidates.is_empty() {
            preview_candidates.extend(
                refs.iter()
                    .filter(|r| labels::is_texture_name(&r.name))
                    .filter_map(|r| r.to),
            );
        }
        if preview_candidates.is_empty() {
            preview_candidates
                .extend(one(cat.textures_in_dir(&g.dir)).into_iter().map(|(h, _)| h));
        }

        Row {
            group: g.clone(),
            base,
            members,
            refs: items,
            parts,
            tags,
            rules: tags_raw.iter().take(6).map(|(t, c)| format!("{t} ({c})")).collect(),
            preview_candidates,
        }
    }

    /// The detail pane's extras: only fetched for the one card being looked at.
    fn extras(&self, gid: i64, hub: u64) -> (Option<String>, Option<Asset>, usize) {
        let fp = self.q(|c| c.fingerprint(gid));
        let asset = self.q(|c| c.asset(hub));
        let names = self.q(|c| c.group_names(gid)).len();
        (fp, asset, names)
    }

    /// The citation graph's health, and the names it fails to resolve. Every figure is
    /// read from the catalog; nothing here is derived from a card, so the panel states
    /// the library's condition rather than a sample of it.
    pub fn ref_view(&self, dangling_limit: usize) -> RefView {
        let health = self.q(|c| c.ref_health());
        let pct = if health.refs_total == 0 {
            0
        } else {
            ((health.refs_resolved as f64 / health.refs_total as f64) * 100.0).round() as u32
        };
        RefView {
            refs_total: health.refs_total,
            refs_resolved: health.refs_resolved,
            resolved_pct: pct,
            dangling_names: health.dangling_names,
            by_ext: health
                .by_ext
                .iter()
                .map(|e| RefExtView {
                    kind: ref_kind_word(&format!("x{}", e.ext)).to_string(),
                    ext: e.ext.clone(),
                    total: e.total,
                    resolved: e.resolved,
                    dangling_names: e.dangling_names,
                    resolved_pct: pct_of(e.resolved, e.total),
                })
                .collect(),
            top_dangling: self
                .q(|c| c.top_dangling(dangling_limit))
                .into_iter()
                .map(|d| DanglingView {
                    kind: ref_kind_word(&format!("x{}", d.ext)).to_string(),
                    name: d.name,
                    citations: d.citations,
                    sources: d.sources,
                    hash: None,
                })
                .collect(),
            assets_citing: health.assets_citing,
            assets_citing_resolved: self.q(|c| c.assets_citing_resolved()),
            top_cited: self
                .q(|c| c.top_cited(12))
                .into_iter()
                .map(|(hash, name, citations)| DanglingView {
                    kind: ref_kind_word(&format!("x{}", ext_of(&name))).to_string(),
                    name,
                    citations,
                    sources: 0,
                    hash: Some(hex(hash)),
                })
                .collect(),
        }
    }

    /// Every asset whose file content cites this resource *by name*. Membership is a fact
    /// about the citing file, so it is reported as such — never as sharing.
    /// `key` is either a 16-digit hash or a client name: the dangling names have no hash
    /// at all, and refusing them here would make the one list that needs this lookup
    /// the only one that cannot use it.
    pub fn cited_by(&self, key: &str, limit: usize) -> CitedByView {
        let key = key.trim();
        let hash = if key.len() == 16 { unhex(key) } else { None };
        let (rows, hash_out) = match hash {
            Some(h) => (self.q(move |c| c.cited_by(h, limit)), hex(h)),
            None => (self.q(|c| c.cited_by_name(key, limit)), String::new()),
        };
        // refs 主键是 (from_hash, name)：同一份文件用裸名和全路径名各写一条边就会出两行，
        // 「N 个文件提到了它」于是变成行数而不是文件数。按路径去重，无路径的留给脚注计数。
        let mut seen: std::collections::HashSet<String> = std::collections::HashSet::new();
        let rows: Vec<(String, String)> = rows
            .into_iter()
            .filter(|(p, _)| p.is_empty() || seen.insert(p.clone()))
            .collect();
        let truncated = rows.len() == limit;
        CitedByView {
            hash: hash_out,
            citations: rows
                .into_iter()
                .map(|(from_path, kind)| CitationView {
                    kind: ref_kind_word(&format!("x{kind}")).to_string(),
                    grouped: !from_path.is_empty(),
                    from_path,
                })
                .collect(),
            truncated,
        }
    }

    /// The most-mentioned resources that actually resolve — the counterpart to the
    /// dangling list, so the panel can show both halves of the citation graph.
    pub fn top_cited(&self, limit: usize) -> Vec<(u64, String, usize)> {
        self.q(|c| c.top_cited(limit))
    }

}

/// `refs_resolved / refs_total` as a 0-100 integer, so every surface rounds identically.
fn pct_of(part: usize, whole: usize) -> u32 {
    if whole == 0 {
        0
    } else {
        ((part as f64 / whole as f64) * 100.0).round() as u32
    }
}

/// The extension off a bare filename, as a dotted string. `ref_kind_word` matches on
/// `rsplit('.')`, so this only has to produce something it can match.
fn ext_of(name: &str) -> String {
    match name.rsplit_once('.') {
        Some((_, e)) if !e.is_empty() && !e.contains('/') => format!(".{e}"),
        _ => String::new(),
    }
}

// ---- queries the commands expose ------------------------------------------------------

impl AppData {
    fn keeps(&self, l: &Lite, f: &Filter, keys: &[String], ql: &str) -> bool {
        if !is_none_or(&f.scenario, |s| l.scenario == s) {
            return false;
        }
        if !is_none_or(&f.kind, |s| l.kind_zh == *s) {
            return false;
        }
        if !is_none_or(&f.grade, |s| l.grade.label().starts_with(s)) {
            return false;
        }
        if f.only_with_image.unwrap_or(false) && l.preview_candidates.is_empty() {
            return false;
        }
        if let Some(want) = f.named {
            if present::is_named(&l.group) != want {
                return false;
            }
        }
        if ql.is_empty() {
            return true;
        }
        // Chinese queries are transliterated in Rust; tags are already Chinese, so they
        // match the query as typed. Name hits never look at the whole path.
        search::matches_asset(&l.group.stem, &l.group.dir, keys)
            || l.tags.iter().any(|t| t.to_lowercase().contains(ql))
            || l.refs.iter().any(|r| r.name.to_lowercase().contains(ql))
    }

    /// Filtered page of cards over whatever has been warmed so far.
    pub fn page(&self, f: &Filter) -> Page {
        let raw = f.query.clone().unwrap_or_default();
        let ql = raw.trim().to_lowercase();
        let keys = search::query_keys(&raw);
        let mut hits: Vec<Arc<Lite>> = match self.lite.lock() {
            Ok(lite) => lite
                .values()
                .filter(|l| self.keeps(l, f, &keys, &ql))
                .cloned()
                .collect(),
            Err(_) => Vec::new(),
        };
        // A search must work in the first second, not only after the warm-up: names that
        // still have no row are read right now (name and folder only, so no guessing).
        if !ql.is_empty() && hits.len() < 40 {
            let missing: Vec<i64> = {
                let lite = match self.lite.lock() {
                    Ok(l) => l,
                    Err(_) => return Page::default(),
                };
                self.groups
                    .iter()
                    .filter(|g| {
                        !lite.contains_key(&g.id)
                            && search::matches_asset(&g.stem, &g.dir, &keys)
                    })
                    .map(|g| g.id)
                    .take(80)
                    .collect()
            };
            if !missing.is_empty() {
                self.ensure(&missing);
                if let Ok(lite) = self.lite.lock() {
                    for gid in missing {
                        if let Some(l) = lite.get(&gid) {
                            if self.keeps(l, f, &keys, &ql) && !hits.iter().any(|h| h.group.id == l.group.id) {
                                hits.push(Arc::clone(l));
                            }
                        }
                    }
                }
            }
        }
        // 第一眼要看得懂：有名字的排前面，其次是有贴图线索的，再按组成规模；
        // 只能靠编号区分的组沉到最后（默认列表不列它们，见 Filter::named）。
        let rank = |l: &Lite| {
            (
                present::is_named(&l.group),
                !l.preview_candidates.is_empty(),
                l.members.len(),
            )
        };
        hits.sort_by(|a, b| {
            rank(b)
                .cmp(&rank(a))
                .then(a.grade.cmp(&b.grade))
                .then_with(|| a.name.cmp(&b.name))
        });
        let limit = f.limit.unwrap_or(150).clamp(1, 800);
        let offset = f.offset.unwrap_or(0);
        let items = hits.iter().skip(offset).take(limit).map(|l| l.card()).collect();
        Page {
            items,
            total: hits.len(),
            scanned: self.scanned(),
            ready: self.ready(),
            query_words: keys,
        }
    }

    pub fn detail(&self, gid: i64) -> Option<Detail> {
        let l = self.lite_of(gid)?;
        let members = l
            .members
            .iter()
            .map(|m| (m.hash, m.role.as_str(), m.path.as_deref()))
            .map(|(hash, role, path)| MemberItem {
                role_word: labels::role_zh(role).to_string(),
                name: path
                    .and_then(|p| p.rsplit('/').next())
                    .filter(|s| !s.is_empty())
                    .map(|s| s.to_string())
                    .unwrap_or_else(|| hex(hash)),
                has_image: role == "texture" || path.map(labels::is_texture_name).unwrap_or(false),
                hash: hex(hash),
            })
            .collect();
        let (fingerprint, asset, name_total) = self.extras(gid, l.group.hub);
        // 必须和卡片上的 `named`（→ 界面标题「未命名资源」）同一个定义，
        // 否则会出现标题说未命名、下面又说有文件名。
        let named = present::is_named(&l.group);
        Some(Detail {
            card: l.card(),
            refs: l.refs.clone(),
            gaps: l.gaps.iter().map(|s| s.to_string()).collect(),
            name_source: if named {
                "客户端文件名（原文展示，未翻译）".to_string()
            } else {
                "没有记录到它所在的路径，只能以编号区分".to_string()
            },
            hub_decoded: l.hub_decoded,
            members,
            tech: Tech {
                id: hex(l.group.hub),
                container: asset.as_ref().map(|a| a.pak.clone()).unwrap_or_default(),
                offset: asset.as_ref().map(|a| a.offset).unwrap_or(0),
                bytes: asset.as_ref().map(|a| a.original).unwrap_or(0),
                codec: asset.as_ref().map(|a| a.codec.clone()).unwrap_or_default(),
                fingerprint,
                names: name_total,
                rules: l.rules.clone(),
                folder: l.group.dir.clone(),
                path: asset
                    .and_then(|a| a.path)
                    .unwrap_or_else(|| l.group.hub_path.clone()),
            },
        })
    }

    pub fn stats(&self) -> Stats {
        let mut scen: HashMap<&'static str, usize> = HashMap::new();
        let mut kinds: HashMap<String, usize> = HashMap::new();
        let mut unnamed = 0usize;
        for g in &self.groups {
            *scen.entry(present::scenario_of(&g.kind)).or_default() += 1;
            *kinds.entry(labels::kind_zh(&g.kind).to_string()).or_default() += 1;
            if !present::is_named(g) {
                unnamed += 1;
            }
        }
        let mut grades: HashMap<String, usize> = HashMap::new();
        let (mut candidates, mut lr, mut tr, mut decoded) = (0usize, 0usize, 0usize, 0usize);
        if let Ok(lite) = self.lite.lock() {
            for l in lite.values() {
                *grades
                    .entry(l.grade.label().chars().next().unwrap_or('D').to_string())
                    .or_default() += 1;
                candidates += usize::from(!l.preview_candidates.is_empty());
                lr += l.located;
                tr += l.ref_total;
                decoded += usize::from(l.hub_decoded);
            }
        }
        Stats {
            total_groups: self.total,
            scanned: self.scanned(),
            ready: self.ready(),
            scenarios: SCENARIOS
                .iter()
                .map(|s| Option2 {
                    value: s.to_string(),
                    label: s.to_string(),
                    count: scen.get(s).copied().unwrap_or(0),
                })
                .collect(),
            kinds: {
                let mut v: Vec<Option2> = kinds
                    .into_iter()
                    .map(|(label, count)| Option2 { value: label.clone(), label, count })
                    .collect();
                v.sort_by(|a, b| b.count.cmp(&a.count).then(a.label.cmp(&b.label)));
                v
            },
            grades: GRADES
                .iter()
                .map(|g| Option2 {
                    value: g.to_string(),
                    label: present::grade_words(g).0.to_string(),
                    count: grades.get(*g).copied().unwrap_or(0),
                })
                .collect(),
            image_candidates: candidates,
            decoded,
            located_refs: lr,
            total_refs: tr,
            unnamed,
            containers: self.containers.len(),
            catalog_file: self.catalog_file.display().to_string(),
            root: self.root.display().to_string(),
        }
    }
}

fn is_none_or(opt: &Option<String>, ok: impl Fn(&str) -> bool) -> bool {
    match opt {
        Some(v) if !v.is_empty() && v != "全部" => ok(v),
        _ => true,
    }
}


// ----------------------------------------------------------------------- 预热缓存
//
// 预热（warm）每次启动把 13,080 组逐个做 SQLite 查询 + pak 回读，两三分钟且
// 不持久——纯内存的缓存每次重付。这里把成品 Lite 落盘成 JSON：下次启动直接
// 载入，秒级就绪。失效策略从宽：magic/版本/库指纹/组数对不上就整个弃用重跑
// 预热，绝不部分采信。

/// 缓存结构版本。DTO 或词表（场景/占位/缺口这些 &'static str 的取值集合）变动
/// 时必须 +1，旧缓存会整体作废重预热——宁可慢一次，不能摆错数据。
const WARM_CACHE_REV: u32 = 1;
const WARM_CACHE_MAGIC: &str = "TLBWARM";

#[derive(serde::Serialize, serde::Deserialize)]
struct WarmCache {
    magic: String,
    rev: u32,
    app: String,
    /// resources.db 的长度 + 修改时间：库重建过，缓存就没意义了。
    db_len: u64,
    db_mtime: i64,
    lites: Vec<LiteDto>,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct LiteDto {
    group: GroupDto,
    name: String,
    subtitle: String,
    scenario: String,
    kind_zh: String,
    tags: Vec<String>,
    parts: Vec<CountDto>,
    placeholder: String,
    grade: String,
    gaps: Vec<String>,
    refs: Vec<RefDto>,
    located: usize,
    ref_total: usize,
    preview_candidates: Vec<u64>,
    hub_decoded: bool,
    rules: Vec<String>,
    members: Vec<MemberDto>,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct GroupDto {
    id: i64,
    hub: String,
    hub_path: String,
    dir: String,
    stem: String,
    kind: String,
    n: i64,
    n_mesh: i64,
    n_mtl: i64,
    n_ani: i64,
    n_ske: i64,
    n_tex: i64,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct CountDto {
    label: String,
    count: usize,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct RefDto {
    name: String,
    kind: String,
    status: String,
    located: bool,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct MemberDto {
    hash: String,
    role: String,
    path: Option<String>,
    rtype: String,
    pak: String,
    offset: i64,
    original: i64,
    ver: i64,
}

/// 把 String 固定成 &'static str（进程内泄漏，量级是词表那几十个词）。
/// Lite 的 scenario/placeholder/gaps 是 &'static str，来自代码里的固定词表；
/// 缓存里只有 String，回流时在这里重新扎根。
fn intern(s: &str) -> &'static str {
    use std::collections::HashMap;
    use std::sync::Mutex;
    static INTERN: OnceLock<Mutex<HashMap<Box<str>, &'static str>>> = OnceLock::new();
    let map = INTERN.get_or_init(|| Mutex::new(HashMap::new()));
    if let Ok(mut m) = map.lock() {
        if let Some(v) = m.get(s) {
            return v;
        }
        let leaked: &'static str = Box::leak(s.to_string().into_boxed_str());
        // 借用到此为止：leaked 指向泄漏的 Box，不依赖这份锁或这张表。
        m.insert(s.into(), leaked);
        return leaked;
    }
    Box::leak(s.to_string().into_boxed_str())
}

fn grade_to_letter(g: Grade) -> String {
    g.label().chars().next().unwrap_or('D').to_string()
}

fn grade_from_letter(s: &str) -> Option<Grade> {
    match s.trim().to_ascii_uppercase().as_str() {
        "A" => Some(Grade::A),
        "B" => Some(Grade::B),
        "C" => Some(Grade::C),
        "D" => Some(Grade::D),
        _ => None,
    }
}

fn lite_to_dto(l: &Lite) -> LiteDto {
    LiteDto {
        group: GroupDto {
            id: l.group.id,
            hub: format!("{:016x}", l.group.hub),
            hub_path: l.group.hub_path.clone(),
            dir: l.group.dir.clone(),
            stem: l.group.stem.clone(),
            kind: l.group.kind.clone(),
            n: l.group.n,
            n_mesh: l.group.n_mesh,
            n_mtl: l.group.n_mtl,
            n_ani: l.group.n_ani,
            n_ske: l.group.n_ske,
            n_tex: l.group.n_tex,
        },
        name: l.name.clone(),
        subtitle: l.subtitle.clone(),
        scenario: l.scenario.to_string(),
        kind_zh: l.kind_zh.clone(),
        tags: l.tags.clone(),
        parts: l
            .parts
            .iter()
            .map(|p| CountDto {
                label: p.label.clone(),
                count: p.count,
            })
            .collect(),
        placeholder: l.placeholder.to_string(),
        grade: grade_to_letter(l.grade),
        gaps: l.gaps.iter().map(|g| g.to_string()).collect(),
        refs: l
            .refs
            .iter()
            .map(|r| RefDto {
                name: r.name.clone(),
                kind: r.kind.clone(),
                status: r.status.clone(),
                located: r.located,
            })
            .collect(),
        located: l.located,
        ref_total: l.ref_total,
        preview_candidates: l.preview_candidates.clone(),
        hub_decoded: l.hub_decoded,
        rules: l.rules.clone(),
        members: l
            .members
            .iter()
            .map(|m| MemberDto {
                hash: format!("{:016x}", m.hash),
                role: m.role.clone(),
                path: m.path.clone(),
                rtype: m.rtype.clone(),
                pak: m.pak.clone(),
                offset: m.offset,
                original: m.original,
                ver: m.ver,
            })
            .collect(),
    }
}

/// 回流。任何对不上的字段（等级字母、编号格式）都返回 Err——整个缓存弃用，
/// 绝不半信半疑地摆数据。
fn lite_from_dto(d: LiteDto) -> Result<Lite, String> {
    let hub = u64::from_str_radix(&d.group.hub, 16).map_err(|_| "hub 编号坏".to_string())?;
    let grade = grade_from_letter(&d.grade).ok_or_else(|| "等级字母坏".to_string())?;
    let members = d
        .members
        .iter()
        .map(|m| {
            Ok(Member {
                hash: u64::from_str_radix(&m.hash, 16).map_err(|_| "成员编号坏".to_string())?,
                role: m.role.clone(),
                path: m.path.clone(),
                rtype: m.rtype.clone(),
                pak: m.pak.clone(),
                offset: m.offset,
                original: m.original,
                ver: m.ver,
            })
        })
        .collect::<Result<Vec<_>, String>>()?;
    Ok(Lite {
        group: Group {
            id: d.group.id,
            hub,
            hub_path: d.group.hub_path,
            dir: d.group.dir,
            stem: d.group.stem,
            kind: d.group.kind,
            n: d.group.n,
            n_mesh: d.group.n_mesh,
            n_mtl: d.group.n_mtl,
            n_ani: d.group.n_ani,
            n_ske: d.group.n_ske,
            n_tex: d.group.n_tex,
        },
        name: d.name,
        subtitle: d.subtitle,
        scenario: intern(&d.scenario),
        kind_zh: d.kind_zh,
        tags: d.tags,
        parts: d
            .parts
            .into_iter()
            .map(|p| Count {
                label: p.label,
                count: p.count,
            })
            .collect(),
        placeholder: intern(&d.placeholder),
        grade,
        gaps: d.gaps.iter().map(|g| intern(g)).collect(),
        refs: d
            .refs
            .into_iter()
            .map(|r| RefItem {
                name: r.name,
                kind: r.kind,
                status: r.status,
                located: r.located,
            })
            .collect(),
        located: d.located,
        ref_total: d.ref_total,
        preview_candidates: d.preview_candidates,
        hub_decoded: d.hub_decoded,
        rules: d.rules,
        members,
    })
}

impl AppData {
    fn warm_cache_path(&self) -> PathBuf {
        // 默认那份库沿用历史名 `warm_cache.json`：换名等于让所有人白预热一次。
        // 但同一个目录里放第二份库（比对重建结果、灰度验证）时缓存必须分开——
        // 以前不分，结果是「换个 TLBB_DB 跑一次自检」就把本机库的预热成果盖掉，
        // 界面立刻退化成重新预热几分钟，而且看不出来是谁干的。
        let dir = self.catalog_file.parent().unwrap_or_else(|| Path::new("."));
        let stem = self
            .catalog_file
            .file_stem()
            .and_then(|s| s.to_str())
            .unwrap_or("resources");
        if stem == "resources" {
            dir.join("warm_cache.json")
        } else {
            dir.join(format!("{stem}_warm_cache.json"))
        }
    }

    fn db_fingerprint(&self) -> (u64, i64) {
        match std::fs::metadata(&self.catalog_file) {
            Ok(m) => (
                m.len(),
                m.modified()
                    .ok()
                    .and_then(|t| {
                        t.duration_since(std::time::UNIX_EPOCH)
                            .ok()
                            .map(|d| d.as_secs() as i64)
                    })
                    .unwrap_or(0),
            ),
            Err(_) => (0, 0),
        }
    }

    /// 预热完成后把全部 Lite 写盘。失败只记日志——缓存是加速，不是数据源，
    /// 下次启动大不了重新预热。
    fn save_warm_cache(&self) {
        // 锁内只做浅拷贝：13,080 次 Arc clone 是微秒级。DTO 转换 + 22MB JSON
        // 序列化必须放在锁外——预热完成的一瞬间正是用户开始浏览资产的时候，
        // page/detail/stats 都要拿 lite 这把锁，握着锁序列化会把它们全部卡住
        // 几百毫秒到数秒。快照元素是 Arc<Lite>，发布之后不可变，锁外读没有竞态；
        // 此刻 warm 的全部分片已 join，lite 条数恒等于 total（ensure 只补已有
        // 组），不存在「快照漏条目」的窗口。
        let snapshot: Vec<Arc<Lite>> = match self.lite.lock() {
            Ok(lite) => lite.values().cloned().collect(),
            Err(_) => return,
        };
        let lites: Vec<LiteDto> = snapshot.iter().map(|l| lite_to_dto(l)).collect();
        let (db_len, db_mtime) = self.db_fingerprint();
        let cache = WarmCache {
            magic: WARM_CACHE_MAGIC.to_string(),
            rev: WARM_CACHE_REV,
            app: env!("CARGO_PKG_VERSION").to_string(),
            db_len,
            db_mtime,
            lites,
        };
        let path = self.warm_cache_path();
        let tmp = path.with_extension("json.tmp");
        match serde_json::to_string(&cache) {
            Ok(text) => {
                if std::fs::write(&tmp, &text).is_ok() && std::fs::rename(&tmp, &path).is_ok() {
                    eprintln!(
                        "warm-cache: saved {} lites -> {}",
                        cache.lites.len(),
                        path.display()
                    );
                }
            }
            Err(e) => eprintln!("warm-cache: 序列化失败：{e}"),
        }
    }

    /// 启动时尝试载入缓存。成功返回 true（lite 已满、ready=true，预热不再跑）。
    /// 任何一步不对就整体弃用，返回 false 走正常预热。
    ///
    /// 并发面（已核实）：全进程只有 `open()` 末尾这一个调用点，而 open 只发生
    /// 在进程启动的单一入口（run / map_dump / maps_dump / probe / 测试），全部
    /// 先于任何 IPC 命令——warm() 由命令触发，两者不可能并发；warm() 自己也
    /// 绝不调这里。所以「载入失败后另一线程正在预热、两边抢 lite 锁」的窗口
    /// 不存在。就算将来多出第二入口，最坏结果也只是载入方与预热线程往同一把
    /// 锁里各放一份等价条目（谁后到谁覆盖），不会撕裂出半条数据。
    pub fn try_load_warm_cache(self: &Arc<Self>) -> bool {
        let path = self.warm_cache_path();
        let Ok(text) = std::fs::read_to_string(&path) else {
            return false;
        };
        let cache: WarmCache = match serde_json::from_str(&text) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("warm-cache: 读不出来（{e}），重新预热");
                return false;
            }
        };
        let (db_len, db_mtime) = self.db_fingerprint();
        if cache.magic != WARM_CACHE_MAGIC
            || cache.rev != WARM_CACHE_REV
            || cache.db_len != db_len
            || cache.db_mtime != db_mtime
            || cache.lites.len() != self.total
        {
            eprintln!("warm-cache: 指纹不匹配（库变过或结构升级），重新预热");
            return false;
        }
        let mut pairs = Vec::with_capacity(cache.lites.len());
        for d in cache.lites {
            match lite_from_dto(d) {
                Ok(l) => pairs.push((l.group.id, std::sync::Arc::new(l))),
                Err(e) => {
                    eprintln!("warm-cache: 条目回流失败（{e}），重新预热");
                    return false;
                }
            }
        }
        let n = pairs.len();
        if let Ok(mut lite) = self.lite.lock() {
            for (gid, l) in pairs {
                lite.insert(gid, l);
            }
            self.scanned.store(n, Ordering::SeqCst);
            self.ready.store(true, Ordering::SeqCst);
            eprintln!("warm-cache: 载入 {n} 组，预热跳过");
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod warm_cache_tests {
    use super::*;

    /// 序列化→回流的字段保真。这是「缓存不许摆错数据」的底线测试。
    #[test]
    fn lite_dto_roundtrip() {
        let lite = Lite {
            group: Group {
                id: 42,
                hub: 0xaabbccdd11223344,
                hub_path: "data/source/npc/test.mdl".into(),
                dir: "data/source/npc".into(),
                stem: "test".into(),
                kind: "model".into(),
                n: 6,
                n_mesh: 1,
                n_mtl: 1,
                n_ani: 2,
                n_ske: 1,
                n_tex: 1,
            },
            name: "测试件".into(),
            subtitle: "test.mdl".into(),
            scenario: "角色",
            kind_zh: "模型".into(),
            tags: vec!["npc".into()],
            parts: vec![Count {
                label: "网格".into(),
                count: 1,
            }],
            placeholder: "角色",
            grade: Grade::B,
            gaps: vec!["贴图名对不上文件"],
            refs: vec![RefItem {
                name: "test_tex".into(),
                kind: "texture".into(),
                status: "只有名字".into(),
                located: false,
            }],
            located: 0,
            ref_total: 1,
            preview_candidates: vec![0x1234],
            hub_decoded: true,
            rules: vec!["规则一".into()],
            members: vec![Member {
                hash: 0xef01,
                role: "mesh".into(),
                path: Some("data/a.mesh".into()),
                rtype: "mesh".into(),
                pak: "data.pak".into(),
                offset: 7,
                original: 9,
                ver: 1,
            }],
        };
        let dto = lite_to_dto(&lite);
        let text = serde_json::to_string(&dto).unwrap();
        let back = lite_from_dto(serde_json::from_str(&text).unwrap()).unwrap();
        assert_eq!(back.group.id, 42);
        assert_eq!(back.group.hub, 0xaabbccdd11223344);
        assert_eq!(back.name, "测试件");
        assert_eq!(back.scenario, "角色");
        assert_eq!(back.placeholder, "角色");
        assert_eq!(back.gaps, vec!["贴图名对不上文件"]);
        assert!(matches!(back.grade, Grade::B));
        assert_eq!(back.members[0].hash, 0xef01);
        assert_eq!(back.preview_candidates, vec![0x1234]);
        assert!(back.hub_decoded);
        // &'static str 必须真的扎了根（能安全持有到进程结束）。
        let leaked: &'static str = back.scenario;
        assert_eq!(leaked, "角色");
    }

    #[test]
    fn grade_letter_rejects_garbage() {
        assert!(grade_from_letter("Q").is_none());
        assert!(grade_from_letter("A").is_some());
    }
}

#[cfg(test)]
mod warm_cache_e2e {
    use super::*;

    /// 端到端走一遍「全量预热 → 落盘 → 二次启动秒载」。预热要几分钟，标
    /// ignore：换机或重建 resources.db 后手动跑一次——
    ///   cargo test --release full_warm_cache_cycle -- --ignored
    #[test]
    #[ignore = "全量预热 2-4 分钟，手动验证缓存闭环时跑"]
    fn full_warm_cache_cycle() {
        let (root, db) = crate::inspector::roots();
        // 先拿到缓存路径、删掉缓存再正式 open：open 会把还在的缓存直接载成
        // ready=true，先 open 后删就永远过不了「从未就绪开始」这道闸（机器上
        // 留着上次跑出来的 warm_cache.json 时必炸）。第一次 open 只为取路径。
        let cache_path = {
            let probe = AppData::open(&root, &db).expect("open");
            probe.warm_cache_path()
        };
        let _ = std::fs::remove_file(&cache_path);
        let app = AppData::open(&root, &db).expect("open");
        assert!(!app.ready(), "删缓存后必须从未就绪开始");
        app.warm();
        let t0 = Instant::now();
        while !app.ready() {
            assert!(
                t0.elapsed() < std::time::Duration::from_secs(600),
                "预热超过 10 分钟，先查 warm 日志"
            );
            std::thread::sleep(std::time::Duration::from_millis(500));
        }
        assert!(
            app.warm_cache_path().exists(),
            "预热完成后缓存必须落盘"
        );
        let app2 = AppData::open(&root, &db).expect("reopen");
        assert!(app2.ready(), "第二次 open 必须经缓存直接就绪");
        assert_eq!(app2.scanned(), app2.total);
    }
}

#[cfg(test)]
mod page_regression {
    use super::*;
    use crate::model::Filter;

    /// 用户实测「列表 0 条、详情正常」的二分:默认筛选与 named:true 各应返回
    /// 大几千条。这个测试钉住「缓存回流的 Lite 必须能被正常列出」。
    #[test]
    fn page_default_and_named_filters_return_data() {
        let (root, db) = crate::inspector::roots();
        let app = AppData::open(&root, &db).expect("open");
        assert!(app.ready(), "本机应有 warm_cache.json(没有就先跑 full_warm_cache_cycle)");
        let all = app.page(&Filter::default());
        let named = app.page(&Filter {
            named: Some(true),
            ..Default::default()
        });
        assert!(
            all.total > 10_000,
            "默认筛选应列出绝大多数组,实际 {}",
            all.total
        );
        assert!(
            named.total > 5_000,
            "named:true 应列出有名字的几万组里的大多数,实际 {}",
            named.total
        );
        // 左栏等级之和(A+B+C+D)应等于资产组总数:等级来自 lite,总数来自 groups,
        // 两个口径对不上就是 lite 里混进了脏条目(用户实测截图出现过 13,086 > 13,080)。
        let stats = app.stats();
        let grade_sum: usize = stats.grades.iter().map(|g| {
            g.count
        }).sum();
        assert_eq!(grade_sum, app.total, "等级之和 {} 应等于资产组总数 {}", grade_sum, app.total);
    }
}
