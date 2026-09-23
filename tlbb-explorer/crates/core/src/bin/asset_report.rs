// Single-asset HTML report: one file, no external resources, safe to hand to an artist.
//
// Port of .scratch/report.py::asset_report, rebuilt on the Rust card contract
// (src/bin/asset_cards.rs) rather than on the Python column layout, because that is
// what the browser and the cards already agree on:
//
// * nothing is shown as a preview unless it was decoded out of the container, and the
//   image is inlined as base64 so the file survives being mailed;
// * the display name is the shipped stem verbatim, with a mechanically derived subtitle;
// * every visible sentence is plain Chinese - identifiers, fingerprints and hashes live
//   in one collapsed block at the bottom;
// * 谁在使用它 counts only edges whose from_hash is not a member of this very asset,
//   which is the bug the Python report has just fixed.
//
// placeholder_for / subtitle / display_name / scenario_of / civil_from_days / b64 are
// duplicated from asset_cards.rs on purpose: that file is a binary, its items are
// private, and binaries cannot import one another. They belong in a shared catalog::card.
//
// The header stays a plain comment rather than a module doc comment, because
// tests/asset_report.rs pulls this file in with include! and inner doc comments cannot
// survive macro expansion.
//
// usage:
//   asset_report --gid 1280 [--out DIR] [--all N] [--db FILE] [--root DIR]
//                [--snapshots DIR] [--max-side 512] [--max-b64-kib 400]

use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};

use tlbb_core::catalog::evidence;
use tlbb_core::catalog::{labels, Catalog, Fingerprints as CatalogFingerprints, Group};
use tlbb_core::jmt1::{self, Codec, Texture};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;

/* ------------------------------------------------------------------ text helpers */

const B64: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/// Standard base64 with padding, spelled out by hand: the dependency list is frozen and
/// `base64` is not on it, and `Cargo.toml` is not ours to touch.
pub fn b64(input: &[u8]) -> String {
    let mut out = String::with_capacity(input.len().div_ceil(3) * 4);
    for chunk in input.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = *chunk.get(1).unwrap_or(&0) as u32;
        let b2 = *chunk.get(2).unwrap_or(&0) as u32;
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(B64[(n >> 18 & 63) as usize] as char);
        out.push(B64[(n >> 12 & 63) as usize] as char);
        out.push(if chunk.len() > 1 { B64[(n >> 6 & 63) as usize] as char } else { '=' });
        out.push(if chunk.len() > 2 { B64[(n & 63) as usize] as char } else { '=' });
    }
    out
}

/// The five characters that can break markup. Applied to every echoed value, including
/// the ones that only ever land inside a `<pre>`.
pub fn esc(v: &str) -> String {
    let mut out = String::with_capacity(v.len());
    for c in v.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(c),
        }
    }
    out
}

/// Byte counts the way a person reads them.
pub fn human(n: i64) -> String {
    let n = n.max(0) as f64;
    for (unit, lim) in [("GB", 1e9), ("MB", 1e6), ("KB", 1e3)] {
        if n >= lim {
            return format!("{:.1} {}", n / lim, unit);
        }
    }
    format!("{} 字节", n as i64)
}

/// Every shipped path carries the build tag `w1351_`; dropping it is a literal cut, not a
/// rename.
pub fn nice(s: &str) -> String {
    s.strip_prefix("w1351_").unwrap_or(s).to_string()
}

fn basename(p: &str) -> &str {
    p.rsplit(['/', '\\']).next().unwrap_or(p)
}

/* --------------------------------------------- card contract (see header note) */

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

pub fn scenario_of(kind: &str) -> &'static str {
    match kind {
        "npc" | "player" => "角色",
        "map-prop" => "场景",
        "effect" => "特效",
        "ui" => "界面",
        "shared-material" => "物品",
        _ => "其他",
    }
}

/// Silhouette drawn when no image decodes — the same seven keys the cards use.
pub fn placeholder_for(scenario: &str, tags: &[String]) -> &'static str {
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

pub fn display_name(g: &Group) -> String {
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

/// Subtitle built only by cutting the name apart; the tail is always a literal substring.
pub fn subtitle(stem: &str, kind: &str) -> String {
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

/// Days since the epoch → (year, month, day), Howard Hinnant's civil_from_days.
pub fn civil_from_days(days: i64) -> (i64, u32, u32) {
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

pub fn stamp() -> String {
    let t = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    let (y, mo, da) = civil_from_days(t.div_euclid(86400));
    let s = t.rem_euclid(86400);
    format!("{y:04}-{mo:02}-{da:02} {:02}:{:02}", s / 3600 % 24, s / 60 % 60)
}

/* ------------------------------------------------------------------- report model */

/// One line of "谁在使用它".
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct User {
    pub file: String,
    pub via: &'static str,
    pub what: String,
}

/// `.ske` / `.tga` / ... → the word an artist uses.
pub fn ext_zh(raw: &str) -> &'static str {
    let low = raw.trim_start_matches('.').to_ascii_lowercase();
    match low.as_str() {
        "ani" | "anis" => "动作",
        "ske" => "骨骼",
        "mesh" => "网格",
        "mtl" => "材质",
        "mdl" => "模型",
        "tga" | "dds" | "png" | "jpg" | "jpeg" | "bmp" | "webp" => "贴图",
        "pu" => "特效",
        "scene" | "map" | "sfl" => "场景",
        _ => "文件",
    }
}

/// Card contract: the type of a referenced name, decided by its literal extension.
pub fn ref_kind(name: &str) -> &'static str {
    ext_zh(name.rsplit('.').next().unwrap_or(""))
}

#[derive(Debug, Clone)]
pub struct RefRow {
    pub kind: &'static str,
    pub name: String,
    pub status: &'static str,
}

#[derive(Debug, Clone)]
pub struct Chip {
    pub label: String,
    pub n: usize,
}

#[derive(Debug, Clone, Default)]
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

impl Fingerprints {
    /// Label/value pairs, in the order the digest was assembled. `-` means the asset holds
    /// no member of that kind, which is a fact rather than a failure.
    pub fn rows(&self) -> [(&'static str, &str); 8] {
        [
            ("整份资源", show(&self.asset)),
            ("模型", show(&self.model)),
            ("骨骼", show(&self.skeleton)),
            ("网格", show(&self.mesh)),
            ("材质", show(&self.material)),
            ("动作", show(&self.animation)),
            ("贴图", show(&self.texture)),
            ("引用名清单", show(&self.names)),
        ]
    }
}

fn show(s: &str) -> &str {
    if s.is_empty() || s == "-" {
        "（无此类文件）"
    } else {
        s
    }
}

#[derive(Debug, Clone)]
pub struct Pic {
    pub data_url: String,
    pub note: String,
}

#[derive(Debug, Clone)]
pub struct VerRow {
    pub snap: String,
    pub verdict: &'static str,
    pub detail: String,
}

#[derive(Debug, Clone, Default)]
pub struct Report {
    pub gid: i64,
    pub name: String,
    pub subtitle: String,
    pub kind: &'static str,
    pub scenario: &'static str,
    pub dir: String,
    pub tags: Vec<String>,
    pub placeholder: &'static str,
    pub pic: Option<Pic>,
    /// Why there is no picture, in plain Chinese. Never an empty `<img>`.
    pub no_pic: Option<String>,
    pub grade: &'static str,
    pub grade_note: String,
    pub gaps: Vec<&'static str>,
    pub name_source: &'static str,
    pub ident: String,
    pub pak: String,
    pub members: usize,
    pub names: usize,
    pub fps: Option<Fingerprints>,
    pub parts: Vec<Chip>,
    pub refs: Vec<RefRow>,
    pub users: Vec<User>,
    pub users_total: usize,
    pub versions: Vec<VerRow>,
    pub snap_note: String,
    pub tech: Vec<(&'static str, String)>,
    pub built: String,
}

impl Report {
    pub fn title(&self) -> String {
        format!("资源报告 · {}", self.name)
    }

    pub fn grade_letter(&self) -> &str {
        self.grade.get(..1).unwrap_or("D")
    }
}

/* ---------------------------------------------------------------------- rendering */

const CSS: &str = r##"
:root{--bg:#f5f6f8;--fg:#1b1f27;--dim:#697180;--line:#dfe3ea}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:14px/1.7 "Microsoft YaHei","PingFang SC",system-ui,sans-serif}
header{background:#101318;color:#eef1f6;padding:14px 26px}
header b{font-size:16px}header span{color:#98a2b3;font-size:12px;margin-left:12px}
main{max-width:940px;margin:0 auto;padding:20px 24px 56px}
section{background:#fff;border:1px solid var(--line);border-radius:10px;padding:15px 18px;margin:13px 0}
h2{font-size:13px;color:var(--dim);margin:0 0 10px;font-weight:600;letter-spacing:.05em}
h1{font-size:22px;margin:0 0 2px;word-break:break-all}
.sub{color:var(--dim);font-size:13px}
.kv{display:grid;grid-template-columns:112px 1fr;gap:2px 12px;font-size:13px}
.kv b{color:var(--dim);font-weight:400}
.chip{display:inline-block;background:#eef2f8;border:1px solid var(--line);border-radius:20px;
 padding:1px 10px;font-size:12px;margin:2px 5px 2px 0;color:#33415c}
.badge{display:inline-block;font-size:11px;padding:1px 9px;border-radius:4px;margin-left:8px;
 vertical-align:3px;font-weight:400}
.gA{background:#e3f3e8;color:#1c6b3f;border:1px solid #b6dcc3}
.gB{background:#e6eff9;color:#1f5fa8;border:1px solid #bcd6f0}
.gC{background:#fbf1d9;color:#8a6100;border:1px solid #ecdca8}
.gD{background:#fbe6e1;color:#a1401e;border:1px solid #f0c6bc}
.pv{display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap}
.pv img{width:220px;height:220px;object-fit:contain;background:#12141a;border:1px solid var(--line);
 border-radius:8px;display:block}
.ph{width:220px;height:220px;display:flex;flex-direction:column;align-items:center;justify-content:center;
 gap:6px;background:#f0f2f5;border:1px dashed var(--line);border-radius:8px;color:#98a2b3}
.ph b{font-size:12px;color:#697180;font-weight:400}.ph span{font-size:11px}
.mono{font-family:Consolas,Menlo,monospace;font-size:12px;word-break:break-all}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:500;font-size:12px}
.mut{color:var(--dim);font-size:12px}
.bad{color:#a1401e}.ok{color:#1c6b3f}
ul.plain{list-style:none;margin:0;padding:0;font-size:13px}
ul.plain li{padding:1px 0}
.gap{color:#8a6100;font-size:13px}
details{margin-top:10px}summary{color:var(--dim);cursor:pointer;font-size:12px}
footer{color:var(--dim);font-size:12px;padding:16px 24px;max-width:940px;margin:0 auto}
"##;

/// The seven silhouettes, copied from the card viewer so a report and a card never
/// disagree about what 特效 looks like.
const SPRITES: &str = r##"<svg style="display:none"><defs>
<symbol id="i-character" viewBox="0 0 48 48"><circle cx="24" cy="13" r="8" fill="currentColor"/>
<path d="M8 44c0-11 7-17 16-17s16 6 16 17z" fill="currentColor"/></symbol>
<symbol id="i-beast" viewBox="0 0 48 48"><path d="M6 30c0-9 8-14 18-14s18 5 18 14c0 6-5 8-9 8l-3 6-4-6h-6l-4 6-3-6c-4 0-7-2-7-8z" fill="currentColor"/>
<circle cx="17" cy="26" r="2.5" fill="#f0f2f5"/><circle cx="31" cy="26" r="2.5" fill="#f0f2f5"/></symbol>
<symbol id="i-building" viewBox="0 0 48 48"><path d="M8 42V18l16-9 16 9v24h-12V28H24v14z" fill="currentColor"/></symbol>
<symbol id="i-effect" viewBox="0 0 48 48"><circle cx="24" cy="24" r="5" fill="currentColor"/>
<circle cx="24" cy="24" r="13" fill="none" stroke="currentColor" stroke-width="2" opacity=".7"/>
<circle cx="24" cy="24" r="20" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".35"/></symbol>
<symbol id="i-panel" viewBox="0 0 48 48"><rect x="7" y="10" width="34" height="28" rx="3" fill="none"
stroke="currentColor" stroke-width="2.5"/><path d="M7 18h34" stroke="currentColor" stroke-width="2.5"/></symbol>
<symbol id="i-item" viewBox="0 0 48 48"><path d="M24 4l5 12 12 5-12 5-5 12-5-12-12-5 12-5z" fill="currentColor"/></symbol>
<symbol id="i-node" viewBox="0 0 48 48"><rect x="18" y="18" width="12" height="12" fill="currentColor"/>
<path d="M24 4v14M24 30v14M4 24h14M30 24h14" stroke="currentColor" stroke-width="2"/></symbol>
</defs></svg>"##;

fn cell(v: &str) -> String {
    format!("<td>{}</td>", esc(v))
}

fn kv(label: &str, value: &str, mono: bool) -> String {
    let span = if mono {
        format!("<span class=\"mono\">{}</span>", esc(value))
    } else {
        esc(value)
    };
    format!("<b>{}</b><span>{span}</span>", esc(label))
}

pub fn render(rep: &Report) -> String {
    let mut h = String::new();
    h.push_str("<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n");
    h.push_str("<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n<title>");
    h.push_str(&esc(&rep.title()));
    h.push_str("</title>\n<style>");
    h.push_str(CSS);
    h.push_str("</style>\n</head>\n<body>\n");
    h.push_str(SPRITES);
    h.push_str("<header><b>天龙资源浏览器 · 资源报告</b><span>生成于 ");
    h.push_str(&esc(&rep.built));
    h.push_str(" · 报告编号 ");
    h.push_str(&rep.gid.to_string());
    h.push_str(" · 只读解析，未修改任何包文件</span></header>\n<main>\n");

    // 1 · title block: shipped stem, mechanical subtitle, evidence badge.
    h.push_str("<section><h1>");
    h.push_str(&esc(&rep.name));
    h.push_str("<span class=\"badge g");
    h.push_str(rep.grade_letter());
    h.push_str("\">");
    h.push_str(&esc(rep.grade));
    h.push_str("</span></h1><div class=\"sub\">");
    h.push_str(&esc(&format!(
        "{} · {} · {}类 · 由 {} 个文件组成",
        rep.subtitle, rep.kind, rep.scenario, rep.members
    )));
    h.push_str("</div><div class=\"sub\">");
    h.push_str(&esc(&rep.dir));
    h.push_str("</div><div>");
    for t in &rep.tags {
        h.push_str("<span class=\"chip\">");
        h.push_str(&esc(t));
        h.push_str("</span>");
    }
    h.push_str("</div></section>\n");

    // 2 · preview: a decoded image, or a silhouette. Never an empty <img>.
    h.push_str("<section><h2>预览</h2><div class=\"pv\">");
    match &rep.pic {
        Some(p) => {
            h.push_str("<img alt=\"");
            h.push_str(&esc(&rep.name));
            h.push_str("\" src=\"");
            h.push_str(&p.data_url);
            h.push_str("\"><div><div class=\"mut\">");
            h.push_str(&esc(&p.note));
            h.push_str("</div></div>");
        }
        None => {
            h.push_str("<div class=\"ph\"><svg width=\"62\" height=\"62\"><use href=\"#i-");
            h.push_str(rep.placeholder);
            h.push_str("\"/></svg><b>暂无可解析预览</b><span>类型轮廓，依据组成与标签</span></div>");
            if let Some(why) = &rep.no_pic {
                h.push_str("<div><div class=\"mut\">");
                h.push_str(&esc(why));
                h.push_str("</div></div>");
            }
        }
    }
    h.push_str("</div></section>\n");

    // 3 · identity card.
    h.push_str("<section><h2>资源身份证</h2><div class=\"kv\">");
    h.push_str(&kv("标识", &rep.ident, true));
    h.push_str(&kv("所在包", if rep.pak.is_empty() { "未记录" } else { &rep.pak }, false));
    h.push_str(&kv("成员数", &format!("{} 个文件", rep.members), false));
    h.push_str(&kv("名称数", &format!("{} 个引用名", rep.names), false));
    h.push_str(&kv("名称来源", rep.name_source, false));
    h.push_str("</div>");
    match &rep.fps {
        Some(f) => {
            h.push_str(
                "<details><summary>资产指纹 · 判断这份内容有没有变过的 8 个编号</summary>\
                 <table><tr><th>指纹</th><th>编号</th></tr>",
            );
            for (label, value) in f.rows() {
                h.push_str(&format!("<tr><td>{}</td><td>{}</td></tr>", cell(label), cell(value)));
            }
            h.push_str("</table></details>");
        }
        None => h.push_str("<div class=\"mut\">本次未能取出指纹，见下方缺口说明。</div>"),
    }
    h.push_str("</section>\n");

    // 4 · composition, aggregated by Chinese label.
    h.push_str("<section><h2>组成</h2><div>");
    if rep.parts.is_empty() {
        h.push_str("<span class=\"mut\">无</span>");
    }
    for c in &rep.parts {
        h.push_str("<span class=\"chip\">");
        h.push_str(&esc(&c.label));
        h.push(' ');
        h.push_str(&c.n.to_string());
        h.push_str("</span>");
    }
    h.push_str("</div></section>\n");

    // 5 · referenced names.
    h.push_str(&format!(
        "<section><h2>引用名称 · {} 个</h2>",
        rep.refs.len()
    ));
    if rep.refs.is_empty() {
        h.push_str("<div class=\"mut\">这个资源没有登记任何引用名。</div>");
    } else {
        h.push_str("<table><tr><th>类型</th><th>名称</th><th>状态</th></tr>");
        for r in rep.refs.iter().take(200) {
            h.push_str("<tr>");
            h.push_str(&cell(r.kind));
            h.push_str(&cell(&r.name));
            h.push_str(&format!(
                "<td class=\"{}\">{}</td>",
                if r.status == "已定位" { "ok" } else { "bad" },
                esc(r.status)
            ));
            h.push_str("</tr>");
        }
        h.push_str("</table>");
        if rep.refs.len() > 200 {
            h.push_str(&format!(
                "<div class=\"mut\">…另有 {} 个未列出。</div>",
                rep.refs.len() - 200
            ));
        }
        h.push_str(
            "<div class=\"mut\">「仅有名称」= 包内确实找不到对应文件，属于安装缺失，不是解析失败。</div>",
        );
    }
    h.push_str("</section>\n");

    // 6 · who uses it (external edges only).
    h.push_str(&format!(
        "<section><h2>谁在使用它 · {} 项</h2>",
        rep.users_total
    ));
    if rep.users.is_empty() {
        h.push_str(
            "<div class=\"mut\">没有发现本资产以外的文件引用它。本资产内部文件之间的互相引用\
             已排除，不计入。</div>",
        );
    } else {
        h.push_str("<ul class=\"plain\">");
        for u in &rep.users {
            h.push_str("<li>");
            h.push_str(&esc(&u.file));
            h.push_str(" <span class=\"mut\">以");
            h.push_str(&esc(u.via));
            h.push_str("方式引用 · ");
            h.push_str(&esc(&u.what));
            h.push_str("</span></li>");
        }
        h.push_str("</ul>");
        if rep.users_total > rep.users.len() {
            h.push_str(&format!(
                "<div class=\"mut\">…共 {} 项，此处列出前 {} 项。</div>",
                rep.users_total,
                rep.users.len()
            ));
        }
    }
    h.push_str("</section>\n");

    // 7 · what is missing, then version comparison.
    h.push_str("<section><h2>还缺什么</h2>");
    if rep.gaps.is_empty() {
        h.push_str("<div class=\"ok\">主体与全部依赖均已定位。</div>");
    } else {
        for g in &rep.gaps {
            h.push_str("<div class=\"gap\">· ");
            h.push_str(&esc(g));
            h.push_str("</div>");
        }
    }
    h.push_str("<div class=\"mut\">");
    h.push_str(&esc(&rep.grade_note));
    h.push_str("</div><h2 style=\"margin-top:14px\">版本比较</h2>");
    if rep.versions.is_empty() {
        h.push_str("<div class=\"mut\">");
        h.push_str(&esc(&rep.snap_note));
        h.push_str("</div>");
    } else {
        h.push_str("<table><tr><th>对照快照</th><th>判定</th><th>变化内容</th></tr>");
        for v in &rep.versions {
            h.push_str("<tr>");
            h.push_str(&cell(&v.snap));
            h.push_str(&format!(
                "<td class=\"{}\">{}</td>",
                if v.verdict == "相同" { "ok" } else { "bad" },
                esc(v.verdict)
            ));
            h.push_str(&cell(&v.detail));
            h.push_str("</tr>");
        }
        h.push_str("</table>");
    }
    h.push_str("</section>\n");

    // 8 · everything technical, collapsed.
    h.push_str("<section><details><summary>技术信息（给程序看的）</summary><div class=\"kv\">");
    for (k, v) in &rep.tech {
        h.push_str(&kv(k, v, true));
    }
    h.push_str("</div></details></section>\n</main>\n");
    h.push_str(
        "<footer>数据来源：只读解析 data*.pak 与 catalog（未修改任何包文件）。\
         预览图由本工具从容器里解码后以 base64 内嵌，本页可离线打开、可直接转发。</footer>\n</body></html>",
    );
    h
}

/// Attribute values that would make the page depend on anything outside itself.
/// `#fragment` (the sprite sheet) is local to the document; everything else must be a
/// `data:` URL.
pub fn outside_refs(html: &str) -> Vec<String> {
    let mut out = Vec::new();
    for attr in ["src=\"", "src='", "href=\"", "href='", "url("] {
        let mut hay = html;
        while let Some(i) = hay.find(attr) {
            let rest = &hay[i + attr.len()..];
            let quote = rest.as_bytes().first().copied();
            let (body, end) = match quote {
                Some(b'"') | Some(b'\'') => {
                    let q = quote.unwrap() as char;
                    (rest, rest.find(q).unwrap_or(rest.len()))
                }
                _ => (rest, rest.find(' ').unwrap_or(rest.len())),
            };
            let v = body[..end].trim().to_string();
            if !v.is_empty() && !v.starts_with("data:") && !v.starts_with('#') {
                out.push(format!("{attr}{v}"));
            }
            hay = &body[end + 1..];
        }
    }
    out
}

/* ------------------------------------------------------------------------- images */

/// Box-filter shrink, so a 2048x1024 terrain sheet does not become a 3 MB attachment.
pub fn rescale(rgba: &[u8], w: usize, h: usize, max_side: usize) -> (usize, usize, Vec<u8>) {
    if max_side == 0 || w == 0 || h == 0 || (w <= max_side && h <= max_side) {
        return (w.max(1), h.max(1), rgba.to_vec());
    }
    let m = w.max(h);
    let nw = ((w * max_side + m / 2) / m).max(1);
    let nh = ((h * max_side + m / 2) / m).max(1);
    let mut out = vec![0u8; nw * nh * 4];
    for y in 0..nh {
        let y0 = y * h / nh;
        let y1 = ((y + 1) * h / nh).max(y0 + 1).min(h);
        for x in 0..nw {
            let x0 = x * w / nw;
            let x1 = ((x + 1) * w / nw).max(x0 + 1).min(w);
            // Alpha-weighted, or transparent padding averages into visible black.
            let (mut a, mut r, mut g, mut b, mut n) = (0u64, 0u64, 0u64, 0u64, 0u64);
            for yy in y0..y1 {
                for xx in x0..x1 {
                    let o = (yy * w + xx) * 4;
                    if o + 3 >= rgba.len() {
                        continue;
                    }
                    let al = rgba[o + 3] as u64;
                    a += al;
                    r += rgba[o] as u64 * al;
                    g += rgba[o + 1] as u64 * al;
                    b += rgba[o + 2] as u64 * al;
                    n += 1;
                }
            }
            let o = (y * nw + x) * 4;
            if a == 0 || n == 0 {
                out[o..o + 4].copy_from_slice(&[0, 0, 0, 0]);
            } else {
                out[o] = (r / a).min(255) as u8;
                out[o + 1] = (g / a).min(255) as u8;
                out[o + 2] = (b / a).min(255) as u8;
                out[o + 3] = (a / n).min(255) as u8;
            }
        }
    }
    (nw, nh, out)
}

/// A shipped WebP bitstream only embeds if it really is one; a raw chunk would render as
/// a broken icon and read as a lie.
fn webp_frame(bytes: &[u8]) -> bool {
    bytes.len() > 12 && &bytes[..4] == b"RIFF" && &bytes[8..12] == b"WEBP"
}

/// PNG/WebP ready to inline, downscaled and size-capped. `Err` carries the plain-Chinese
/// reason shown next to the silhouette.
///
/// Block-compressed game art is close to incompressible: measured on an incompressible
/// 2048x1024 sheet, a full-size inline is 10.9 MB of base64 and a 512px one is still 595
/// KB. So the cap is a ladder - keep shrinking until the bytes fit rather than giving up at
/// the first size that is too big, and only fall back to the silhouette when even a
/// postage-stamp thumbnail would not fit.
pub fn inline_image(tex: &Texture, max_side: usize, max_kib: usize) -> Result<Pic, String> {
    let tail = " · 由容器解码得到，非推测图像";
    if tex.codec == Codec::Webp {
        let raw = tex.webp.clone().unwrap_or_default();
        if !webp_frame(&raw) {
            return Err("这种贴图是未打包好的 WebP 码流，浏览器无法直接显示。".into());
        }
        let b = b64(&raw);
        if b.len() > max_kib * 1024 {
            return Err(format!(
                "原始贴图 {}，为控制单文件体积已省略。",
                human(raw.len() as i64)
            ));
        }
        return Ok(Pic {
            data_url: format!("data:image/webp;base64,{b}"),
            note: format!("WEBP {}x{}{}", tex.width, tex.height, tail),
        });
    }
    let base = if max_side == 0 {
        usize::from(tex.width.max(tex.height))
    } else {
        max_side
    };
    let budget = max_kib.saturating_mul(1024);
    let mut tried: Vec<(u16, u16)> = Vec::new();
    let mut least: Option<(usize, u16, u16)> = None;
    for frac in [1.0f64, 0.75, 0.5, 0.375, 0.25, 0.125] {
        let side = (base as f64 * frac).round() as usize;
        let (w, h, buf) = rescale(&tex.rgba, tex.width as usize, tex.height as usize, side);
        let (w, h) = (w as u16, h as u16);
        if w == 0 || h == 0 || tried.contains(&(w, h)) {
            continue;
        }
        tried.push((w, h));
        let png = tlbb_core::preview::png_bytes(w, h, &buf, true)
            .map_err(|e| format!("图片编码失败：{e}"))?;
        let b = b64(&png);
        if b.len() <= budget {
            let shown = if (w, h) == (tex.width, tex.height) {
                String::new()
            } else {
                format!("（显示 {w}x{h}）")
            };
            return Ok(Pic {
                data_url: format!("data:image/png;base64,{b}"),
                note: format!("{} {}x{}{}{}", tex.codec.as_str(), tex.width, tex.height, shown, tail),
            });
        }
        if least.as_ref().map(|(n, _, _)| b.len() < *n).unwrap_or(true) {
            least = Some((b.len(), w, h));
        }
    }
    let (n, w, h) = least.unwrap_or((0, tex.width, tex.height));
    Err(format!(
        "贴图 {w}x{h} 内嵌后仍有 {}，已超过单文件上限，改为只列信息不放图。",
        human(n as i64)
    ))
}

/* ------------------------------------------------------------------------ catalog */

#[derive(Debug, Clone)]
pub struct Args {
    pub gid: i64,
    pub all: Option<usize>,
    pub db: PathBuf,
    pub root: PathBuf,
    pub out: PathBuf,
    pub snapshots: PathBuf,
    pub max_side: usize,
    pub max_kib: usize,
}

impl Default for Args {
    fn default() -> Self {
        Self {
            gid: 0,
            all: None,
            db: PathBuf::from("D:/TLGL/.scratch/resources.db"),
            root: PathBuf::from("D:/TLGL"),
            out: PathBuf::from("D:/TLGL/.scratch/rust_reports"),
            snapshots: PathBuf::new(),
            max_side: 512,
            max_kib: 400,
        }
    }
}

pub fn parse_args(raw: &[String]) -> Args {
    let mut a = Args::default();
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
            "--gid" => a.gid = take().parse().unwrap_or(a.gid),
            "--all" => a.all = Some(take().parse().unwrap_or(50usize)),
            "--db" => a.db = PathBuf::from(take()),
            "--root" => a.root = PathBuf::from(take()),
            "--out" => a.out = PathBuf::from(take()),
            "--snapshots" => a.snapshots = PathBuf::from(take()),
            "--max-side" => a.max_side = take().parse().unwrap_or(a.max_side),
            "--max-b64-kib" => a.max_kib = take().parse().unwrap_or(a.max_kib),
            _ => {}
        }
        i += 1;
    }
    if a.snapshots.as_os_str().is_empty() {
        // Version samples live next to the catalog they were dumped from.
        a.snapshots = a.db.parent().unwrap_or(Path::new(".")).join("versions");
    }
    a
}

/// `谁在使用它` for one asset, taken from the catalog's single implementation.
///
/// This used to be a private SQL here plus a private filter, which meant the report and
/// the workbench could disagree about the same asset. The rules now live in exactly one
/// place (`Catalog::external_users`): no self-edge, no referrer from inside the group, and
/// no referrer without a recorded path. The report's only job is to phrase the answer.
pub fn external_users(cat: &Catalog, gid: i64, limit: usize) -> Vec<User> {
    let edges = cat.external_users(gid).unwrap_or_default();
    let mut seen: HashSet<(String, String)> = HashSet::new();
    let mut out = Vec::new();
    for e in edges {
        if e.from_path.is_empty() {
            continue;
        }
        let via = ext_zh(&e.kind);
        if !seen.insert((e.from_path.clone(), via.to_string())) {
            continue;
        }
        out.push(User {
            file: nice(basename(&e.from_path)),
            via,
            what: basename(&e.from_path).to_string(),
        });
        if out.len() >= limit {
            break;
        }
    }
    out
}

/// The catalog's fingerprint row, in this report's display shape.
///
/// The report no longer reads `asset_fingerprint` itself — [`Catalog::fingerprints`] is the
/// one reader, so a report and the workbench can never print different digests for the same
/// asset. All that lives here is the Chinese labelling.
pub fn into_fps(f: CatalogFingerprints) -> Fingerprints {
    Fingerprints {
        asset: f.asset,
        model: f.model,
        skeleton: f.skeleton,
        mesh: f.mesh,
        material: f.material,
        animation: f.animation,
        texture: f.texture,
        names: f.names,
    }
}

/* ------------------------------------------------------------------ version compare */

/// What one snapshot says about one asset — enough to diff without re-reading the paks.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Snap {
    pub dir: String,
    pub stem: String,
    pub hub_path: String,
    pub id_asset: String,
    pub id_pack: String,
    /// (role, file name) → (content digest, stored-bytes digest).
    pub members: BTreeMap<(String, String), (String, String)>,
}

pub fn snap_from_json(v: &serde_json::Value) -> Option<Snap> {
    let text = |x: Option<&serde_json::Value>| {
        x.and_then(|y| y.as_str())
            .unwrap_or("")
            .to_string()
    };
    Some(Snap {
        dir: text(v.get("dir")),
        stem: text(v.get("stem")),
        hub_path: text(v.get("hub_path")),
        id_asset: text(v.get("id_asset")),
        id_pack: text(v.get("id_pack")),
        members: v
            .get("members")?
            .as_array()?
            .iter()
            .map(|m| {
                (
                    (text(m.get("role")), text(m.get("name"))),
                    (text(m.get("sha")), text(m.get("crc"))),
                )
            })
            .collect(),
    })
}

/// Verdicts in the same vocabulary `identity.py` uses, so a single report and the
/// fleet-wide census never say different things about the same pair.
pub fn diff_snap(cur: &Snap, old: &Snap) -> (&'static str, String) {
    if !cur.id_asset.is_empty() && cur.id_asset == old.id_asset {
        return if cur.id_pack == old.id_pack {
            ("相同", "内容与打包都没有变化".into())
        } else {
            ("仅重新打包", "内容完全一致，只有压缩结果不同".into())
        };
    }
    let only_now: Vec<&(String, String)> = cur.members.keys().filter(|k| !old.members.contains_key(k)).collect();
    let only_then: Vec<&(String, String)> = old.members.keys().filter(|k| !cur.members.contains_key(k)).collect();
    let changed: Vec<&(String, String)> = cur
        .members
        .iter()
        .filter(|(k, v)| match old.members.get(k) {
            Some(o) => !v.0.is_empty() && !o.0.is_empty() && v.0 != o.0,
            None => false,
        })
        .map(|(k, _)| k)
        .collect();
    if only_now.is_empty() && only_then.is_empty() && changed.is_empty() {
        return (
            "仅名称变化",
            "文件清单一致，引用名或内部关系有变动".into(),
        );
    }
    // Read from the reader's side: what does this build hold that the snapshot did not?
    let mut bits = Vec::new();
    for (set, words) in [(only_now, "多了"), (only_then, "少了")] {
        if set.is_empty() {
            continue;
        }
        let mut by_role: BTreeMap<&'static str, usize> = BTreeMap::new();
        for (role, _) in set.iter() {
            *by_role.entry(labels::role_zh(role)).or_default() += 1;
        }
        let txt: Vec<String> = by_role
            .into_iter()
            .map(|(r, n)| format!("{words}{r} {n} 个"))
            .collect();
        bits.push(txt.join("、"));
    }
    if !changed.is_empty() {
        bits.push(format!("{} 个文件内容变了", changed.len()));
    }
    ("成员变化", bits.join("；"))
}

fn pick_match(list: &[Snap], cur: &Snap) -> Option<Snap> {
    // A key shared by two candidate rows proves nothing: 792 assets carry no name at all,
    // so only unique keys may pair assets.
    let unique = |f: &dyn Fn(&Snap) -> bool| {
        let hits: Vec<&Snap> = list.iter().filter(|x| f(x)).collect();
        (hits.len() == 1).then(|| hits[0].clone())
    };
    if !cur.dir.is_empty() && !cur.stem.is_empty() {
        if let Some(x) = unique(&|s| s.dir == cur.dir && s.stem == cur.stem) {
            return Some(x);
        }
    }
    if !cur.hub_path.is_empty() {
        if let Some(x) = unique(&|s| s.hub_path == cur.hub_path) {
            return Some(x);
        }
    }
    if !cur.id_asset.is_empty() {
        if let Some(x) = unique(&|s| s.id_asset == cur.id_asset) {
            return Some(x);
        }
    }
    None
}

/// Every `*.json` next to the catalog. Missing directory, no files, unreadable files: the
/// report says so in words instead of printing an empty table.
pub fn versions_for(dir: &Path, cur: &Snap) -> (Vec<VerRow>, String) {
    if !dir.is_dir() {
        return (
            Vec::new(),
            format!("无历史快照：版本样例目录不存在（{}）。", dir.display()),
        );
    }
    let mut files: Vec<PathBuf> = std::fs::read_dir(dir)
        .map(|rd| {
            rd.flatten()
                .filter(|e| e.path().extension().map(|x| x == "json").unwrap_or(false))
                .map(|e| e.path())
                .collect()
        })
        .unwrap_or_default();
    files.sort();
    if files.is_empty() {
        return (Vec::new(), "无历史快照：样例目录里还没有任何快照文件。".into());
    }
    let mut out = Vec::new();
    let mut broken = 0usize;
    for p in files {
        let name = p
            .file_name()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_default();
        let doc = std::fs::read_to_string(&p)
            .ok()
            .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok());
        let Some(doc) = doc else {
            broken += 1;
            continue;
        };
        let list: Vec<Snap> = doc
            .get("assets")
            .and_then(|a| a.as_array())
            .map(|arr| arr.iter().filter_map(snap_from_json).collect())
            .unwrap_or_default();
        match pick_match(&list, cur) {
            None => out.push(VerRow {
                snap: name,
                verdict: "资产消失",
                detail: format!("那份快照里没有这项资源（本次 {} 个文件）", cur.members.len()),
            }),
            Some(old) => {
                let (verdict, detail) = diff_snap(cur, &old);
                out.push(VerRow { snap: name, verdict, detail });
            }
        }
    }
    if broken > 0 {
        out.push(VerRow {
            snap: format!("（{} 个快照文件读不了）", broken),
            verdict: "无法比较",
            detail: "文件格式不认识".into(),
        });
    }
    if out.is_empty() {
        return (Vec::new(), "无历史快照：没有可读取的快照文件。".into());
    }
    (out, String::new())
}

/// The live side of the comparison, read straight out of the catalog.
///
/// Every fact here comes from [`Catalog`] — identity and member digests are properties of
/// the asset, not of this report, so the workbench reads the same rows through the same
/// methods. What remains report-specific is only the *shape* (`Snap`), which exists so a
/// version file and the live catalog can be compared field by field.
pub fn current_snap(cat: &Catalog, g: &Group) -> Snap {
    let mut s = Snap {
        dir: g.dir.clone(),
        stem: g.stem.clone(),
        hub_path: g.hub_path.clone(),
        ..Default::default()
    };
    if let Some(id) = cat.identity(g.id).unwrap_or_default() {
        s.id_asset = id.id_asset;
        s.id_pack = id.id_pack;
    }
    for m in cat.member_digests(g.id).unwrap_or_default() {
        s.members.insert(
            (m.role, m.name),
            (m.sha.chars().take(16).collect(), m.crc),
        );
    }
    s
}

/* ----------------------------------------------------------------------- assembly */

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

fn decode_one(
    hash: u64,
    cat: &Catalog,
    paks: &HashMap<String, Pak>,
    cache: &mut AssetCache,
) -> Option<Vec<u8>> {
    if !cache.contains_key(&hash) {
        cache.insert(hash, cat.asset(hash).ok().flatten());
    }
    let a = cache.get(&hash)?.clone()?;
    let pak = paks.get(&a.pak)?;
    let rec = pak.records().find(|r| r.hash == hash)?;
    payload::decode(pak, &rec).ok().map(|d| d.bytes)
}

/// Texture candidates: the names every member references, then anything of type texture
/// sharing its directory.
///
/// Reading only the hub's own `refs` was the old bug: the shipped materials hang their
/// texture names off the member `.mtl` row, so a hub whose references are just
/// `.ske`/`.mesh`/`.mtl` never yielded a candidate even though the asset plainly holds a
/// texture. Group-wide is also what the workbench does, so both products pick the same
/// image for the same asset.
fn texture_candidates(cat: &Catalog, g: &Group) -> Vec<u64> {
    let mut out = Vec::new();
    if let Ok(refs) = cat.refs_from_group(g.id) {
        for r in &refs {
            if labels::is_texture_name(&r.name) {
                if let Some(h) = r.to {
                    out.push(h);
                }
            }
        }
    }
    if out.is_empty() {
        if let Ok(dirs) = cat.textures_in_dir(&g.dir) {
            out.extend(dirs.into_iter().map(|(h, _)| h));
        }
    }
    out.sort();
    out.dedup();
    out
}

pub fn pick_preview(
    cat: &Catalog,
    g: &Group,
    paks: &HashMap<String, Pak>,
    cache: &mut AssetCache,
    max_side: usize,
    max_kib: usize,
) -> (Option<Pic>, Option<String>) {
    let mut refused: Option<String> = None;
    for hash in texture_candidates(cat, g).into_iter().take(6) {
        let Some(bytes) = decode_one(hash, cat, paks, cache) else {
            continue;
        };
        let Ok(tex) = jmt1::decode(&bytes) else {
            continue;
        };
        match inline_image(&tex, max_side, max_kib) {
            Ok(pic) => return (Some(pic), None),
            Err(why) => {
                if refused.is_none() {
                    refused = Some(why);
                }
            }
        }
    }
    (None, refused)
}

pub fn build(
    cat: &Catalog,
    g: &Group,
    paks: &HashMap<String, Pak>,
    cache: &mut AssetCache,
    a: &Args,
) -> Report {
    let members = cat.members(g.id).unwrap_or_default();

    // Aggregated by the Chinese label, so two roles that read the same can never appear
    // as two separate chips.
    let mut counted: BTreeMap<String, (usize, usize)> = BTreeMap::new(); // label → (rank, n)
    for m in &members {
        let label = labels::role_zh(&m.role).to_string();
        let rank = ROLE_ORDER
            .iter()
            .position(|r| labels::role_zh(r) == label)
            .unwrap_or(ROLE_ORDER.len());
        let e = counted.entry(label).or_insert((rank, 0));
        e.1 += 1;
        e.0 = e.0.min(rank);
    }
    let mut ordered: Vec<(usize, String, usize)> = counted
        .into_iter()
        .map(|(label, (rank, n))| (rank, label, n))
        .collect();
    ordered.sort();
    let parts: Vec<Chip> = ordered.into_iter().map(|(_, label, n)| Chip { label, n }).collect();

    let hub_decoded = decode_one(g.hub, cat, paks, cache).is_some();
    let pak = cat.asset(g.hub).ok().flatten().map(|x| x.pak).unwrap_or_default();

    let located: HashMap<String, Option<u64>> = cat
        .refs_from(g.hub)
        .unwrap_or_default()
        .into_iter()
        .map(|r| (r.name.to_ascii_lowercase(), r.to))
        .collect();
    let mut refs: Vec<RefRow> = Vec::new();
    for (name, _cls) in cat.group_names(g.id).unwrap_or_default() {
        let hit = located.get(&name.to_ascii_lowercase()).copied().flatten();
        refs.push(RefRow {
            kind: ref_kind(&name),
            status: if hit.is_some() { "已定位" } else { "仅有名称" },
            name,
        });
    }
    refs.sort_by(|x, y| {
        x.status
            .cmp(y.status)
            .then(x.kind.cmp(y.kind))
            .then(x.name.cmp(&y.name))
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
    let grade = evidence::grade(&sig);

    let mut tags: Vec<String> = Vec::new();
    for (t, _c) in cat.tags(g.id).unwrap_or_default() {
        let zh = labels::tag_zh(&t).into_owned();
        if !tags.contains(&zh) {
            tags.push(zh);
        }
    }

    let users = external_users(cat, g.id, usize::MAX);
    let users_total = users.len();
    let users: Vec<User> = users.into_iter().take(40).collect();

    let named = !g.stem.is_empty() || !g.dir.is_empty();
    let (pic, refused) = pick_preview(cat, g, paks, cache, a.max_side, a.max_kib);
    let cur = current_snap(cat, g);
    let (versions, snap_note) = versions_for(&a.snapshots, &cur);
    let scenario = scenario_of(&g.kind);
    let name = display_name(g);

    let tech: Vec<(&'static str, String)> = vec![
        ("资源组编号", g.id.to_string()),
        ("主体标识", format!("{:016x}", g.hub)),
        ("主体路径", g.hub_path.clone()),
        ("成员清单", members.iter().take(200).map(|m| format!("{:016x}.{};", m.hash, m.role)).collect()),
        ("分类", g.kind.clone()),
        ("场景", scenario.to_string()),
    ];

    Report {
        gid: g.id,
        ident: format!("{:016x}", g.hub),
        subtitle: subtitle(&name, &g.kind),
        name: name.clone(),
        kind: labels::kind_zh(&g.kind),
        scenario,
        dir: g.dir.clone(),
        placeholder: placeholder_for(scenario, &tags),
        pic,
        no_pic: refused,
        grade: grade.label(),
        grade_note: grade.note().to_string(),
        gaps: evidence::gaps(&sig),
        name_source: if named {
            "客户端茎名（原文展示，未翻译）"
        } else {
            "无路径记录，仅以标识区分"
        },
        pak,
        members: members.len(),
        names: refs.len(),
        fps: cat.fingerprints(g.id).unwrap_or_default().map(into_fps),
        tags,
        parts,
        refs,
        users,
        users_total,
        versions,
        snap_note,
        tech,
        built: stamp(),
    }
}

fn main() {
    let raw: Vec<String> = std::env::args().skip(1).collect();
    let a = parse_args(&raw);
    if !a.db.exists() {
        eprintln!("catalog not found: {}", a.db.display());
        std::process::exit(2);
    }
    let cat = match Catalog::open_ro(&a.db) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(2);
        }
    };
    if let Err(e) = std::fs::create_dir_all(&a.out) {
        eprintln!("cannot write {}: {e}", a.out.display());
        std::process::exit(2);
    }
    let t0 = std::time::Instant::now();
    let paks = open_paks(&a.root);
    let groups = match cat.groups(20_000) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(2);
        }
    };
    let total_groups = groups.len();
    let chosen: Vec<Group> = match a.all {
        Some(n) => groups.into_iter().take(n).collect(),
        None => groups.into_iter().filter(|g| g.id == a.gid).take(1).collect(),
    };
    if chosen.is_empty() {
        eprintln!("资源组 {} 不存在", a.gid);
        std::process::exit(1);
    }
    println!(
        "{} 个包 · {} 个资源组 · 生成 {} 份报告（打开耗时 {}ms）",
        paks.len(),
        total_groups,
        chosen.len(),
        t0.elapsed().as_millis()
    );
    let mut cache: AssetCache = HashMap::new();
    let mut total = 0u64;
    let mut biggest = (0u64, String::new());
    let mut with_pic = 0usize;
    let t1 = std::time::Instant::now();
    for g in &chosen {
        let rep = build(&cat, g, &paks, &mut cache, &a);
        let html = render(&rep);
        if rep.pic.is_some() {
            with_pic += 1;
        }
        let path = a.out.join(format!("资源报告_{}.html", g.id));
        if let Err(e) = std::fs::write(&path, &html) {
            eprintln!("write failed {}: {e}", path.display());
            continue;
        }
        let size = html.len() as u64;
        total += size;
        if size > biggest.0 {
            biggest = (size, path.file_name().unwrap_or_default().to_string_lossy().into_owned());
        }
        if chosen.len() <= 5 {
            println!(
                "  {} · {} · 预览 {} · 使用者 {} 项 · {}",
                path.display(),
                human(size as i64),
                if rep.pic.is_some() { "内嵌图" } else { "占位" },
                rep.users_total,
                rep.grade,
            );
        }
    }
    println!(
        "写毕 {} 份 · 合计 {} · 平均 {} · 最大 {}（{}）· 有内嵌预览 {} 份 · 用时 {}ms",
        chosen.len(),
        human(total as i64),
        human((total / chosen.len() as u64) as i64),
        human(biggest.0 as i64),
        biggest.1,
        with_pic,
        t1.elapsed().as_millis()
    );
}
