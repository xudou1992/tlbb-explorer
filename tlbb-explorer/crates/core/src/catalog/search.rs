//! Chinese search over ASCII-only asset names.
//!
//! The shipped client carries no display names — a scan of every config, table, text and
//! XML payload found zero CJK strings — so a player's Chinese query has to be
//! transliterated and matched against the pinyin the artists already baked into the file
//! names (`w1351_boss_caoshuang` for 曹霜).
//!
//! Initial-only keys ("cs" for 曹霜) are deliberately not produced: the stems are run
//! together, so an abbreviation matches across word boundaries in directory paths and
//! drowns the real hit.
//!
//! A hit has to fall on **whole artist tokens**. Both the query and the name are split on
//! the separators the artists used, and the query's pieces must land on a contiguous run of
//! the name's tokens.
//!
//! Two simpler rules each break one direction. Collapsing separators and matching the whole
//! flattened string let a query straddle a boundary — 暗椅 (`anyi`) answered to
//! `shao|shang_yi`. Requiring the query to equal one token broke the other way — `Cao
//! Shuang` is two tokens, so the single key `caoshuang` could never reach it. Window
//! matching over tokens gets both right, and its one honest limitation is that a query may
//! still be a prefix *inside* a single token (`texiao` in `texiaomen`); separating those
//! would cost every compound name. See `matches` for the full table.

use pinyin::ToPinyin;

/// The artist's own word separators. A query may not span one of these.
const SEPARATORS: &[char] = &['_', '-', '/', '.', ' ', '\\'];

/// Collapse the separators the artists used so `cao shuang`, `cao_shuang` and
/// `caoshuang` all compare equal.
pub fn normalize(s: &str) -> String {
    s.to_lowercase().chars().filter(|c| !SEPARATORS.contains(c)).collect()
}

/// The artist tokens of a name, each already separator-free. This is the granularity a
/// query has to land in.
pub fn tokens(s: &str) -> Vec<String> {
    s.to_lowercase()
        .split(|c| SEPARATORS.contains(&c))
        .filter(|t| !t.is_empty())
        .map(|t| t.to_string())
        .collect()
}

/// Fold the input forms a Windows IME actually produces: full-width ASCII (`ＮＰＣ`,
/// `ｂｏｓｓ３`) and the ideographic space. Without this `ＮＰＣ` finds nothing while `npc`
/// matches 536 groups.
fn fold(s: &str) -> String {
    s.chars()
        .map(|c| match c {
            '\u{3000}' => ' ',
            '\u{FF01}'..='\u{FF5E}' => char::from_u32(c as u32 - 0xFEE0).unwrap_or(c),
            other => other,
        })
        .collect()
}

/// Candidate spellings of a user query: as typed, plus its pinyin.
pub fn query_keys(query: &str) -> Vec<String> {
    let q = fold(query).trim().to_lowercase();
    let mut out = Vec::new();
    if !q.is_empty() {
        out.push(q.clone());
    }
    let mut joined = String::new();
    for c in q.chars() {
        match c.to_pinyin() {
            // The library emits `nü`/`lü` while the artists wrote `nv`/`lv`; without this
            // fold, 女 (231 groups) and 绿 (64 groups) can never be reached.
            Some(p) => joined.push_str(&p.plain().replace('ü', "v")),
            // Non-Han characters pass through: "boss3" must still match.
            None => {
                if c.is_ascii() {
                    joined.push(c);
                }
            }
        }
    }
    if !joined.is_empty() && joined != q && !out.contains(&joined) {
        out.push(joined);
    }
    out
}

/// True when the query matches a **contiguous run of the name's artist tokens**.
///
/// The token is the unit the artist thought in, so the query has to be expressible in
/// whole tokens — but the *query* may be written with different spacing than the name.
/// Both sides are therefore tokenised and the query's pieces are checked against a sliding
/// window of the name's. That single rule gets all four cases right:
///
/// | query | name | result | why |
/// |---|---|---|---|
/// | `caoshuang` | `w1351_boss_caoshuang` | yes | one token, contained in one token |
/// | `caoshuang` | `Cao Shuang` | yes | one token, spans `cao`+`shuang` |
/// | `texiao` | `...pvp_texiaomen_shifa01` | **yes** | contained in `texiaomen` — see below |
/// | `caoshuang` | `...npc_sifengmolinghun` | no | no window matches |
///
/// The third row is a deliberate, documented limitation: `texiaomen` is a single artist
/// token, so `texiao` genuinely *is* a prefix of it. No word-boundary rule can separate
/// them without also requiring exact token equality, and exact equality would cost every
/// compound name (少林 drops from 56 hits to a handful). See
/// `search_audit::category_words_never_reach_the_name_path`.
pub fn matches(name: &str, keys: &[String]) -> bool {
    let toks = tokens(name);
    if toks.is_empty() {
        return false;
    }
    keys.iter().any(|k| {
        let needle = tokens(k).concat();
        if needle.is_empty() {
            return false;
        }
        // A query shorter than a whole token still has to sit inside one — matching across
        // a boundary here is what let 暗椅 (anyi) answer to `shao|shang_yi`.
        if toks.iter().any(|t| t.contains(&needle)) {
            return true;
        }
        // Otherwise the query may span several tokens, but only a contiguous run of them:
        // `cao`+`shuang` for `Cao Shuang`, never `shao`+`shang_yi` for an unrelated pair.
        if toks.len() < 2 {
            return false;
        }
        // Byte offsets where each token starts and ends; a hit is a contiguous run only if
        // both its edges land on one of these seams.
        let mut seams = Vec::with_capacity(toks.len() * 2);
        let mut off = 0usize;
        for t in &toks {
            seams.push(off);
            off += t.len();
            seams.push(off);
        }
        let joined = toks.concat();
        let mut start = 0usize;
        while let Some(at) = joined[start..].find(&needle) {
            let pos = start + at;
            if seams.contains(&pos) && seams.contains(&(pos + needle.len())) {
                return true;
            }
            start = pos + 1;
            if start >= joined.len() {
                break;
            }
        }
        false
    })
}

/// Match against the asset's own name and its containing directory leaf — not the whole
/// path, whose `npc/quest` segments create accidental substrings.
pub fn matches_asset(stem: &str, dir: &str, keys: &[String]) -> bool {
    let leaf = dir.rsplit('/').next().unwrap_or(dir);
    matches(stem, keys) || (!leaf.is_empty() && matches(leaf, keys))
}
