//! M3: emit user-facing asset cards plus a self-contained viewer, so the information
//! structure can be reviewed before any UI shell is built.
//!
//! Presentation rules enforced here, because they are what makes the tool trustworthy:
//! nothing is shown as a preview unless it was decoded from the container; the display
//! name is the shipped stem verbatim with a mechanically derived subtitle (no word
//! guessing — the client carries no Chinese names); and every card states its evidence
//! grade, so a name-level match never reads like a resolved asset.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use serde::Serialize;
use tlbb_core::catalog::evidence;
use tlbb_core::catalog::{labels, search, Catalog, Group};
use tlbb_core::jmt1::{self, Codec};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

#[derive(Serialize)]
struct Count {
    #[serde(rename = "类型")]
    kind: &'static str,
    #[serde(rename = "数量")]
    n: usize,
}

#[derive(Serialize)]
struct Ref {
    #[serde(rename = "类型")]
    kind: &'static str,
    #[serde(rename = "名称")]
    name: String,
    #[serde(rename = "状态")]
    status: &'static str,
}

#[derive(Serialize)]
struct Evidence {
    #[serde(rename = "定位等级")]
    grade: String,
    #[serde(rename = "等级说明")]
    note: String,
    #[serde(rename = "缺口")]
    gaps: Vec<&'static str>,
    #[serde(rename = "名称来源")]
    name_source: &'static str,
}

#[derive(Serialize)]
struct Tech {
    #[serde(rename = "标识")]
    hash: String,
    #[serde(rename = "所在包")]
    pak: String,
    #[serde(rename = "成员数")]
    members: usize,
    #[serde(rename = "名称数")]
    names: usize,
    #[serde(rename = "资产指纹")]
    fingerprint: Option<String>,
    #[serde(rename = "判定依据")]
    rules: Vec<String>,
}

#[derive(Serialize)]
struct Card {
    #[serde(rename = "名称")]
    name: String,
    #[serde(rename = "副标题")]
    subtitle: String,
    #[serde(rename = "类型")]
    kind: &'static str,
    #[serde(rename = "场景")]
    scenario: &'static str,
    #[serde(rename = "所在目录")]
    dir: String,
    #[serde(rename = "预览")]
    preview: Option<String>,
    #[serde(rename = "预览说明")]
    preview_note: Option<String>,
    /// Which evidence put this picture on the card; absent when there is no picture.
    #[serde(rename = "预览依据")]
    preview_source: Option<String>,
    /// Silhouette key used when no image can be decoded. Never a fake preview.
    #[serde(rename = "占位")]
    placeholder: &'static str,
    #[serde(rename = "组成")]
    parts: Vec<Count>,
    #[serde(rename = "引用名称")]
    refs: Vec<Ref>,
    #[serde(rename = "标签")]
    tags: Vec<String>,
    #[serde(rename = "证据")]
    evidence: Evidence,
    #[serde(rename = "技术信息")]
    tech: Tech,
}

/// Display order of the composition chips; anything absent lands last, merged by label.
const ROLE_ORDER: &[&str] = &[
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

/// The review scenarios the UI is judged against, derived from `kind` alone so sampling
/// never depends on a guessed label.
fn scenario_of(kind: &str) -> &'static str {
    match kind {
        "npc" | "player" => "角色",
        "map-prop" => "场景",
        "effect" => "特效",
        "ui" => "界面",
        "shared-material" => "物品",
        _ => "其他",
    }
}

/// Which silhouette to draw when no image can be decoded.
fn placeholder_for(scenario: &str, tags: &[String]) -> &'static str {
    let has = |t: &str| tags.iter().any(|x| x == t);
    if has("宠物") || has("坐骑") {
        "beast"
    } else if has("武器") || has("配饰") || has("物品图标") {
        "item"
    } else if has("建筑") || has("地表贴图组") || has("地图摆件") {
        "building"
    } else {
        match scenario {
            "角色" => "character",
            "场景" => "building",
            "特效" => "effect",
            "界面" => "panel",
            "物品" => "item",
            _ => "node",
        }
    }
}

/// What a card is called. 792 of the 8,537 groups carry no path at all, and those fall
/// back to their identifier rather than showing an empty title or an invented name.
fn display_name(g: &Group) -> String {
    if !g.stem.is_empty() {
        return g.stem.clone();
    }
    if let Some(base) = g.hub_path.rsplit('/').next() {
        let b = base.split('.').next().unwrap_or("");
        if !b.is_empty() {
            return b.to_string();
        }
    }
    format!("{:016x}", g.hub)
}

/// Subtitle built only by cutting the name apart. The tail is always a literal substring
/// of the name, so no translation can be invented here.
fn subtitle(stem: &str, kind: &str) -> String {
    let tail = stem
        .split(['_', '-', '.'])
        .filter(|t| {
            !t.is_empty()
                && t.len() > 1
                && !t.chars().all(|c| c.is_ascii_digit())
                && !t.eq_ignore_ascii_case("w1351")
        })
        .last()
        .unwrap_or(stem);
    format!("{} · {}", scenario_of(kind), tail)
}

fn parse() -> (PathBuf, PathBuf, PathBuf, usize, Option<String>) {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let mut root = PathBuf::from("D:/TLGL");
    let mut db = PathBuf::from("D:/TLGL/.scratch/resources.db");
    let mut out = PathBuf::from("D:/TLGL/.scratch/cards");
    let mut limit = 100usize;
    let mut find = None;
    let mut i = 0;
    while i < raw.len() {
        let (k, v) = match raw[i].split_once('=') {
            Some((k, v)) => (k.to_string(), Some(v.to_string())),
            None => {
                let k = raw[i].clone();
                let v = raw.get(i + 1).filter(|s| !s.starts_with("--")).cloned();
                if v.is_some() {
                    i += 1;
                }
                (k, v)
            }
        };
        let take = || v.clone().unwrap_or_default();
        match k.as_str() {
            "--root" => root = PathBuf::from(take()),
            "--db" => db = PathBuf::from(take()),
            "--out" => out = PathBuf::from(take()),
            "--limit" => limit = take().parse().unwrap_or(100),
            "--find" => find = Some(take()),
            _ => {}
        }
        i += 1;
    }
    (root, db, out, limit, find)
}

fn open_paks(root: &Path) -> HashMap<String, Pak> {
    let mut out = HashMap::new();
    let Ok(entries) = std::fs::read_dir(root) else {
        return out;
    };
    for e in entries.flatten() {
        let p = e.path();
        if p.extension().map(|x| x != "pak").unwrap_or(true) {
            continue;
        }
        if let (Some(stem), Ok(pak)) = (p.file_stem(), Pak::open(&p)) {
            out.insert(stem.to_string_lossy().to_string(), pak);
        }
    }
    out
}

type AssetCache = HashMap<u64, Option<tlbb_core::catalog::Asset>>;

/// Decode one resource by hash, remembering catalog lookups across cards.
fn decode_one(hash: u64, cat: &Catalog, paks: &HashMap<String, Pak>, cache: &mut AssetCache) -> Option<Vec<u8>> {
    if !cache.contains_key(&hash) {
        cache.insert(hash, cat.asset(hash).ok().flatten());
    }
    let a = cache.get(&hash)?.clone()?;
    let pak = paks.get(&a.pak)?;
    let rec = pak.records().find(|r| r.hash == hash)?;
    payload::decode(pak, &rec).ok().map(|d| d.bytes)
}

/// A picture for the card, chosen by evidence strength and always labelled with where
/// it came from.
///
/// The earlier version fell back to "any texture in the same directory", which made 22
/// wardrobe groups all show one identical portrait — a fabricated preview. Directory
/// adjacency is no longer used at all: only the asset's own bytes, its own members, or a
/// reference that resolves to a concrete resource can put an image on a card.
fn make_preview(
    cat: &Catalog,
    g: &Group,
    paks: &HashMap<String, Pak>,
    cache: &mut AssetCache,
    out: &Path,
) -> (Option<String>, Option<String>, Option<String>) {
    let mut candidates: Vec<(u64, &'static str)> = vec![(g.hub, "这个文件本身就是一张图")];
    if let Ok(m) = cat.members(g.id) {
        for m in m.iter().filter(|m| m.role == "texture").take(4) {
            candidates.push((m.hash, "本资产自带的贴图"));
        }
    }
    if let Ok(hashes) = cat.members(g.id).map(|v| v.into_iter().map(|m| m.hash).collect::<Vec<_>>()) {
        if let Ok(refs) = cat.refs_from_many(&hashes) {
            for (name, to) in refs {
                if to.is_some() && labels::is_texture_name(&name) {
                    candidates.push((to.unwrap(), "本资产引用到、且已定位的贴图"));
                }
            }
        }
    }
    candidates.sort_by_key(|(h, _)| *h);
    candidates.dedup_by_key(|(h, _)| *h);
    for (hash, source) in candidates.into_iter().take(8) {
        let Some(bytes) = decode_one(hash, cat, paks, cache) else {
            continue;
        };
        let Ok(tex) = jmt1::decode(&bytes) else {
            continue;
        };
        let file = format!("{}_{:016x}", g.stem.replace(['/', '\\'], "_"), hash);
        let dir = out.join("previews");
        let res = if tex.codec == Codec::Webp {
            match &tex.webp {
                Some(w) => std::fs::create_dir_all(&dir)
                    .and_then(|_| std::fs::write(dir.join(format!("{file}.webp")), w)),
                None => continue,
            }
        } else {
            std::fs::create_dir_all(&dir).and_then(|_| {
                let (px, tw, th) =
                    tlbb_core::preview::scale_rgba(&tex.rgba, tex.width as usize, tex.height as usize, 256);
                tlbb_core::preview::write_png(&dir.join(format!("{file}.png")), tw as u16, th as u16, &px)
                    .map_err(std::io::Error::other)
            })
        };
        if res.is_ok() {
            let ext = if tex.codec == Codec::Webp { "webp" } else { "png" };
            return (
                Some(format!("previews/{file}.{ext}")),
                Some(format!("{} {}x{}", tex.codec.as_str(), tex.width, tex.height)),
                Some(source.to_string()),
            );
        }
    }
    (None, None, None)
}

fn build_card(
    cat: &Catalog,
    g: &Group,
    paks: &HashMap<String, Pak>,
    cache: &mut AssetCache,
    out: &Path,
) -> Card {
    let members = cat.members(g.id).unwrap_or_default();
    // Keyed by the Chinese label, not the raw role, so two roles that read the same can
    // never appear as two separate chips.
    let mut counted: HashMap<&'static str, usize> = HashMap::new();
    for m in &members {
        *counted.entry(labels::role_zh(&m.role)).or_default() += 1;
    }
    let mut ordered: Vec<(usize, &'static str, usize)> = counted
        .iter()
        .map(|(label, n)| {
            let rank = ROLE_ORDER
                .iter()
                .position(|r| labels::role_zh(r) == *label)
                .unwrap_or(ROLE_ORDER.len());
            (rank, *label, *n)
        })
        .collect();
    ordered.sort();
    let parts: Vec<Count> = ordered
        .into_iter()
        .map(|(_, kind, n)| Count { kind, n })
        .collect();

    let hub_decoded = decode_one(g.hub, cat, paks, cache).is_some();
    let hub_asset = cat.asset(g.hub).ok().flatten();

    // Every named dependency, not only textures: materials and models dangle too.
    let located: HashMap<String, Option<u64>> = cat
        .refs_from(g.hub)
        .unwrap_or_default()
        .into_iter()
        .map(|r| (r.name.to_ascii_lowercase(), r.to))
        .collect();
    let mut refs: Vec<Ref> = Vec::new();
    for (name, _cls) in cat.group_names(g.id).unwrap_or_default() {
        let kind = match name.rsplit('.').next().unwrap_or("").to_ascii_lowercase().as_str() {
            "tga" | "dds" | "png" | "jpg" | "jpeg" | "bmp" | "webp" => "贴图",
            "mtl" => "材质",
            "mdl" => "模型",
            "ske" => "骨骼",
            "ani" => "动作",
            "scene" | "map" => "场景",
            _ => "其他",
        };
        let hit = located.get(&name.to_ascii_lowercase()).copied().flatten();
        refs.push(Ref {
            kind,
            status: if hit.is_some() { "已定位" } else { "仅有名称" },
            name,
        });
    }
    refs.sort_by(|a, b| {
        a.status
            .cmp(&b.status)
            .then(a.kind.cmp(&b.kind))
            .then(a.name.cmp(&b.name))
    });
    // 评分口径与工作台/基线共用一条查询：按名去重、任一行定位即算定位。
    // 上面的 refs 列表只服务展示（定位源是 hub 自己的 refs），不参与评分。
    let (tex_total, tex_located) = cat.texture_refs(g.id).unwrap_or((0, 0));
    let sig = evidence::EvidenceFacts {
        hub_decoded: if hub_decoded { evidence::Decode::Decoded } else { evidence::Decode::Failed },
        roles: members.iter().map(|m| m.role.clone()).collect(),
        members: members.len(),
        refs_total: tex_total,
        refs_located: tex_located,
    }
    .signals();

    let tagged = cat.tags(g.id).unwrap_or_default();
    let mut tags: Vec<String> = Vec::new();
    for (t, _conf) in &tagged {
        let zh = labels::tag_zh(t).into_owned();
        if !tags.contains(&zh) {
            tags.push(zh);
        }
    }
    let rules = tagged
        .iter()
        .take(6)
        .map(|(t, c)| format!("{t} ({c})"))
        .collect();

    let name = display_name(g);
    let named = !g.stem.is_empty() || !g.dir.is_empty();
    let (preview, preview_note, preview_source) = make_preview(cat, g, paks, cache, out);
    let grade = evidence::grade(&sig);
    let scenario = scenario_of(&g.kind);

    Card {
        subtitle: subtitle(&name, &g.kind),
        name: name.clone(),
        kind: labels::kind_zh(&g.kind),
        scenario,
        dir: g.dir.clone(),
        placeholder: placeholder_for(scenario, &tags),
        preview,
        preview_note,
        preview_source,
        parts,
        refs,
        tags,
        evidence: Evidence {
            grade: grade.label().to_string(),
            note: grade.note().to_string(),
            gaps: evidence::gaps(&sig),
            name_source: if named {
                "客户端茎名（原文展示，未翻译）"
            } else {
                "无路径记录，仅以标识区分"
            },
        },
        tech: Tech {
            hash: format!("{:016x}", g.hub),
            pak: hub_asset.map(|a| a.pak).unwrap_or_default(),
            members: members.len(),
            names: cat.group_names(g.id).map(|v| v.len()).unwrap_or(0),
            fingerprint: cat.fingerprint(g.id).ok().flatten(),
            rules,
        },
    }
}

/// Round-robin across scenarios so a sample is not 3,463 scene props.
fn select(groups: Vec<Group>, limit: usize) -> Vec<Group> {
    let mut buckets: HashMap<&'static str, Vec<Group>> = HashMap::new();
    for g in groups {
        buckets.entry(scenario_of(&g.kind)).or_default().push(g);
    }
    let mut keys: Vec<_> = buckets.keys().cloned().collect();
    keys.sort_by(|a, b| buckets[b][0].n.cmp(&buckets[a][0].n));
    let mut out = Vec::new();
    let mut round = 0usize;
    while out.len() < limit && round < 4000 {
        let mut progressed = false;
        for k in &keys {
            if let Some(g) = buckets.get_mut(k).and_then(|v| v.get_mut(round)) {
                out.push(g.clone());
                progressed = true;
                if out.len() >= limit {
                    break;
                }
            }
        }
        if !progressed {
            break;
        }
        round += 1;
    }
    out
}

fn write_viewer(out: &Path, json: &str) -> std::io::Result<()> {
    let html = r##"<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>天龙资产卡片 · 结构预览</title><style>
:root{color-scheme:dark}body{margin:0;padding:20px 24px;background:#14161a;color:#e8eaed;
font:14px/1.55 "Microsoft YaHei",system-ui,sans-serif}
h1{font-size:19px;margin:0 0 4px}.meta{color:#9aa0a6;font-size:12px}
.bar{display:flex;gap:8px;align-items:center;margin:12px 0;flex-wrap:wrap}
input{width:240px;padding:7px 10px;background:#1d2025;border:1px solid #2c313a;border-radius:6px;color:#e8eaed}
.tab{padding:5px 12px;background:#1d2025;border:1px solid #2c313a;border-radius:20px;
cursor:pointer;font-size:12px;color:#9aa0a6}.tab.on{background:#2b3a55;color:#e8eaed;border-color:#3d5480}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}
.card{background:#1a1d22;border:1px solid #262b33;border-radius:10px;padding:13px 14px}
.nm{font-weight:600;word-break:break-all}.sub{color:#9aa0a6;font-size:12px;margin:2px 0 8px}
.badge{display:inline-block;font-size:11px;padding:1px 8px;border-radius:4px;margin-left:6px;
vertical-align:2px;font-weight:400}
.gA{background:#1e3a2b;color:#81c995}.gB{background:#1e2f45;color:#8ab4f8}
.gC{background:#3a3420;color:#fdd663}.gD{background:#3a2320;color:#f28b82}
img{width:100%;max-height:170px;object-fit:contain;background:#101215;border-radius:6px;display:block}
.ph{height:130px;display:flex;flex-direction:column;align-items:center;justify-content:center;
gap:6px;background:#101215;border-radius:6px;color:#5f6368}
.ph svg{opacity:.5}.ph b{font-size:12px;color:#9aa0a6;font-weight:400}.ph span{font-size:11px}
.row{margin-top:9px}.lbl{color:#9aa0a6;font-size:12px;margin-bottom:3px}
.chip{display:inline-block;background:#232830;border-radius:20px;padding:1px 9px;margin:2px 4px 2px 0;font-size:12px}
ul{margin:2px 0;padding-left:16px;font-size:12px}li{margin:1px 0}
.miss{color:#80868b}.hit{color:#81c995}.dir{color:#5f6368;font-size:11px;word-break:break-all}
.gap{color:#fdd663;font-size:12px}details{margin-top:9px;color:#9aa0a6;font-size:12px}
summary{cursor:pointer}pre{white-space:pre-wrap;word-break:break-all;color:#80868b;font-size:11px}
</style></head><body>
<svg style="display:none"><defs>
<symbol id="i-character" viewBox="0 0 48 48"><circle cx="24" cy="13" r="8" fill="currentColor"/>
<path d="M8 44c0-11 7-17 16-17s16 6 16 17z" fill="currentColor"/></symbol>
<symbol id="i-beast" viewBox="0 0 48 48"><path d="M6 30c0-9 8-14 18-14s18 5 18 14c0 6-5 8-9 8l-3 6-4-6h-6l-4 6-3-6c-4 0-7-2-7-8z" fill="currentColor"/>
<circle cx="17" cy="26" r="2.5" fill="#101215"/><circle cx="31" cy="26" r="2.5" fill="#101215"/></symbol>
<symbol id="i-building" viewBox="0 0 48 48"><path d="M8 42V18l16-9 16 9v24h-12V28H24v14z" fill="currentColor"/></symbol>
<symbol id="i-effect" viewBox="0 0 48 48"><circle cx="24" cy="24" r="5" fill="currentColor"/>
<circle cx="24" cy="24" r="13" fill="none" stroke="currentColor" stroke-width="2" opacity=".7"/>
<circle cx="24" cy="24" r="20" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".35"/></symbol>
<symbol id="i-panel" viewBox="0 0 48 48"><rect x="7" y="10" width="34" height="28" rx="3" fill="none"
stroke="currentColor" stroke-width="2.5"/><path d="M7 18h34" stroke="currentColor" stroke-width="2.5"/></symbol>
<symbol id="i-item" viewBox="0 0 48 48"><path d="M24 4l5 12 12 5-12 5-5 12-5-12-12-5 12-5z" fill="currentColor"/></symbol>
<symbol id="i-node" viewBox="0 0 48 48"><rect x="18" y="18" width="12" height="12" fill="currentColor"/>
<path d="M24 4v14M24 30v14M4 24h14M30 24h14" stroke="currentColor" stroke-width="2"/></symbol>
</defs></svg>
<h1>天龙资产卡片 · 结构预览</h1><div class="meta" id="m"></div>
<div class="bar"><input id="q" placeholder="搜索名称 / 目录（本页本地过滤，拼音检索在 Rust 层）">
<span id="tabs"></span></div><div class="grid" id="g"></div>
<script>
const DATA=__JSON__;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const SC=['全部','角色','场景','特效','界面','物品','其他'];let cur='全部';
function head(c){
 const pv=c["预览"]?`<img loading=lazy src="${esc(c["预览"])}">`
  :`<div class="ph"><svg width="46" height="46"><use href="#i-${esc(c["占位"])}"/></svg>
    <b>暂无可解析预览</b><span>${esc(c["类型"])} · 依据组成与标签</span></div>`;
 return `<div class="nm">${esc(c["名称"])}<span class="badge g${esc(c["证据"]["定位等级"][0])}">${esc(c["证据"]["定位等级"])}</span></div>
 <div class="sub">${esc(c["副标题"])}</div><div class="dir">${esc(c["所在目录"])}</div>${pv}
 ${c["预览说明"]?`<div class="meta">${esc(c["预览说明"])}</div>`:''}`;
}
function body(c){
 const parts=(c["组成"]||[]).map(p=>`<span class="chip">${esc(p["类型"])} ${p["数量"]}</span>`).join('');
 const refs=(c["引用名称"]||[]).slice(0,6).map(r=>
  `<li><span class="${r["状态"]=="已定位"?'hit':'miss'}">${esc(r["状态"])}</span> ${esc(r["类型"])} ${esc(r["名称"])}</li>`).join('');
 const tags=(c["标签"]||[]).map(t=>`<span class="chip">${esc(t)}</span>`).join('');
 const gaps=(c["证据"]["缺口"]||[]).map(g=>`<div class="gap">· ${esc(g)}</div>`).join('');
 return `<div class="row"><div class="lbl">组成</div>${parts||'<span class="meta">无</span>'}</div>
 <div class="row"><div class="lbl">标签</div>${tags||'<span class="meta">无</span>'}</div>
 <div class="row"><div class="lbl">引用名称 ${(c["引用名称"]||[]).length}</div>
  <ul>${refs||'<span class="meta">无</span>'}</ul>${gaps}</div>`;
}
function tech(c){return `<details><summary>技术信息 · ${esc(c["证据"]["等级说明"])}</summary>
 <pre>${esc(JSON.stringify({证据:c["证据"],技术信息:c["技术信息"]},null,1))}</pre></details>`;}
const card=c=>`<div class="card">${head(c)}${body(c)}${tech(c)}</div>`;
function render(){
 const f=q.value.trim().toLowerCase();
 const list=DATA["卡片"].filter(c=>(cur==='全部'||c["场景"]===cur)&&
   (!f||c["名称"].toLowerCase().includes(f)||c["所在目录"].toLowerCase().includes(f)));
 g.innerHTML=list.map(card).join('');
 m.textContent=`${DATA["资源组总数"]} 个资源组 · 本页 ${list.length} 张卡片 · 生成于 ${DATA["生成时间"]}`;
}
tabs.innerHTML=SC.map(s=>`<span class="tab${s===cur?' on':''}" data-s="${s}">${s}</span>`).join('');
tabs.onclick=e=>{const s=e.target.dataset.s;if(!s)return;cur=s;
 [...tabs.children].forEach(x=>x.classList.toggle('on',x.dataset.s===s));render();};
q.oninput=render;render();
</script></body></html>"##;
    std::fs::write(out.join("cards.html"), html.replace("__JSON__", json))
}

fn main() {
    let (root, db, out, limit, find) = parse();
    if !db.exists() {
        eprintln!("catalog not found: {}", db.display());
        std::process::exit(2);
    }
    let cat = Catalog::open_ro(&db).expect("open catalog");
    let groups = cat.groups(20_000).expect("groups");

    if let Some(q) = find {
        // Name hits come from the pinyin transliteration; category words (宠物/特效) live
        // in the tags, so both are searched and reported apart.
        let keys = search::query_keys(&q);
        println!("查询 {q} → 候选拼写 {keys:?}");
        let (mut by_name, mut by_tag) = (0usize, 0usize);
        for g in &groups {
            if search::matches_asset(&g.stem, &g.dir, &keys) {
                by_name += 1;
                if by_name <= 20 {
                    println!("  [名称] {:<6} {:<44} {}", scenario_of(&g.kind), g.stem, g.dir);
                }
            }
            // Tag hits use the same folded keys as name hits and are counted independently,
            // so a name match no longer hides the tagged ones (`武器` vs 159 weapon groups).
            let zh = cat
                .tags(g.id)
                .unwrap_or_default()
                .into_iter()
                .map(|(t, _)| labels::tag_zh(&t).into_owned())
                .collect::<Vec<_>>();
            if zh
                .iter()
                .any(|t| keys.iter().any(|k| t.to_lowercase().contains(k.as_str())))
            {
                by_tag += 1;
                if by_tag <= 8 {
                    println!("  [标签] {:<6} {:<44} {}", scenario_of(&g.kind), g.stem, zh.join(" "));
                }
            }
        }
        println!(
            "命中 名称 {by_name} + 标签 {by_tag} = {} / {} 个资源组",
            by_name + by_tag,
            groups.len()
        );
        return;
    }

    std::fs::create_dir_all(&out).expect("create out");
    let paks = open_paks(&root);
    let chosen = select(groups.clone(), limit);
    println!(
        "{} paks open · {} asset groups · building {} cards",
        paks.len(),
        groups.len(),
        chosen.len()
    );
    let mut cache: AssetCache = HashMap::new();
    let cards: Vec<Card> = chosen
        .iter()
        .map(|g| build_card(&cat, g, &paks, &mut cache, &out))
        .collect();

    let mut scen: HashMap<&str, usize> = HashMap::new();
    let mut grade: HashMap<&str, usize> = HashMap::new();
    for c in &cards {
        *scen.entry(c.scenario).or_default() += 1;
        *grade.entry(&c.evidence.grade).or_default() += 1;
    }
    let with_preview = cards.iter().filter(|c| c.preview.is_some()).count();
    let refs_all: usize = cards.iter().map(|c| c.refs.len()).sum();
    let refs_hit = cards.iter().flat_map(|c| c.refs.iter()).filter(|r| r.status == "已定位").count();

    let doc = serde_json::json!({
        "生成时间": chrono_free_timestamp(),
        "数据来源": "resources.db + data*.pak（只读解析）",
        "资源组总数": groups.len(),
        "卡片数": cards.len(),
        "有预览图": with_preview,
        "场景分布": scen,
        "定位等级分布": grade,
        "引用名称总数": refs_all,
        "引用可定位": refs_hit,
        "说明": "客户端不携带中文显示名，名称一律按茎名原文展示；无图卡片使用类型轮廓占位，不生成任何推测图像。",
        "卡片": cards,
    });
    let json = serde_json::to_string_pretty(&doc).expect("serialize");
    std::fs::write(out.join("cards.json"), &json).expect("write cards.json");
    write_viewer(&out, &json).expect("write cards.html");

    let mut sc: Vec<_> = scen.into_iter().collect();
    sc.sort();
    let mut gr: Vec<_> = grade.into_iter().collect();
    gr.sort();
    println!("  scenarios {sc:?}");
    println!("  grades {gr:?}");
    println!("  previews {with_preview}/{} · refs {refs_hit}/{refs_all} locatable", cards.len());
    println!("  wrote {}", out.join("cards.html").display());
}

/// Days since the epoch → (year, month, day), Howard Hinnant's civil_from_days.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = (if z >= 0 { z } else { z - 146_096 }) / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (y + i64::from(m <= 2), m as u32, d as u32)
}

/// UTC timestamp as `YYYY-MM-DD HH:MM`.
fn chrono_free_timestamp() -> String {
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let (y, mo, da) = civil_from_days(t.div_euclid(86400));
    let s = t.rem_euclid(86400);
    format!("{y:04}-{mo:02}-{da:02} {:02}:{:02} UTC", s / 3600 % 24, s / 60 % 60)
}

#[cfg(test)]
mod tests {
    use super::{civil_from_days, display_name, placeholder_for, scenario_of, subtitle};
    use tlbb_core::catalog::Group;

    #[test]
    fn epoch_days_match_the_calendar() {
        assert_eq!(civil_from_days(0), (1970, 1, 1));
        assert_eq!(civil_from_days(11_017), (2000, 3, 1));
        assert_eq!(civil_from_days(19_782), (2024, 2, 29));
        assert_eq!(civil_from_days(20_454), (2026, 1, 1));
        assert_eq!(civil_from_days(20_718), (2026, 9, 22));
        assert_eq!(civil_from_days(-1), (1969, 12, 31));
    }

    #[test]
    fn subtitle_only_cuts_the_stem_apart() {
        assert_eq!(subtitle("w1351_nan_s_moyuqianyou_001", "player"), "角色 · moyuqianyou");
        assert_eq!(subtitle("w1351_boss_caoshuang", "npc"), "角色 · caoshuang");
        assert_eq!(subtitle("w1351_fb_sxzc_001", "map-prop"), "场景 · sxzc");
        // Degenerate stems fall back to the name itself rather than inventing a token.
        assert_eq!(subtitle("w1351", "other"), "其他 · w1351");
        assert!(subtitle("anything_at_all", "ui").chars().all(|c| !char::is_uppercase(c)));
    }

    #[test]
    fn nameless_groups_fall_back_to_their_identifier() {
        let g = |stem: &str, hub_path: &str, hub: u64| Group {
            id: 1,
            hub,
            hub_path: hub_path.into(),
            dir: String::new(),
            stem: stem.into(),
            kind: "other".into(),
            n: 1,
            n_mesh: 0,
            n_mtl: 0,
            n_ani: 0,
            n_ske: 0,
            n_tex: 0,
        };
        assert_eq!(display_name(&g("w1351_a_b01", "x/y/w1351_a_b01.mdl", 7)), "w1351_a_b01");
        assert_eq!(display_name(&g("", "data/ui/icon_mr.psd", 7)), "icon_mr");
        let only_hash = display_name(&g("", "", 0xabcd));
        assert_eq!(only_hash, "000000000000abcd");
        // Whatever the source, the subtitle tail stays a substring of the shown name.
        for stem in ["w1351_nan_s_yifu_mjrmdz", "", "x"] {
            let n = display_name(&g(stem, "", 9));
            let tail = subtitle(&n, "other").split('·').last().unwrap().trim().to_string();
            assert!(!tail.is_empty() && n.contains(&tail), "{stem} → {n} / {tail}");
        }
    }

    #[test]
    fn scenarios_and_placeholders_stay_within_the_sprite_set() {
        assert_eq!(scenario_of("npc"), "角色");
        assert_eq!(scenario_of("map-prop"), "场景");
        assert_eq!(scenario_of("ui"), "界面");
        let known = ["character", "beast", "building", "effect", "panel", "item", "node"];
        for kind in ["npc", "player", "map-prop", "effect", "ui", "shared-material", "other"] {
            let p = placeholder_for(scenario_of(kind), &[]);
            assert!(known.contains(&p), "{kind} → {p}");
        }
        assert_eq!(placeholder_for("npc", &["宠物".into()]), "beast");
        assert_eq!(placeholder_for("other", &["武器".into()]), "item");
        assert_eq!(placeholder_for("map-prop", &["建筑".into()]), "building");
    }
}
