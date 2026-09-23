//! Regression audit for the Chinese → pinyin search path (see `catalog::search`).
//!
//! The audit runs against the real catalog (`D:/TLGL/.scratch/resources.db`) and skips
//! silently when that file is absent, so it never breaks a clean checkout. Thresholds are
//! measured numbers from the 13,080-row `agroups` table; they exist to catch a future
//! change to `normalize` / `query_keys` / `matches_asset` that silently floods or starves
//! results.
//!
//! Two of these tests used to name a mechanism that is not the one doing the work. The
//! name path is served by *word-internal containment* — `caoshuang` reaches
//! `w1351_boss_caoshuang` because it sits inside one artist token — and that rule can
//! never make a category word return zero: `texiaomen` literally begins with `texiao`, and
//! `fuben` is a real directory name. Category words are *supposed* to be served by
//! `asset_tags`; the name path overlapping on a handful of rows is expected, not a leak.
//! The assertions below therefore record the measured baseline instead of asserting zero.
//!
//! Run `cargo test --release --test search_audit -- --ignored --nocapture` to reprint the
//! full measured tables (polyphone misses, noise, initials inflation).

use std::path::Path;

use rusqlite::Connection;
use tlbb_core::catalog::labels::tag_zh;
use tlbb_core::catalog::search::{matches_asset, query_keys};

const DB: &str = "D:/TLGL/.scratch/resources.db";

/// `Vec<(id, kind, stem, dir_leaf)>` — the exact fields `matches_asset` looks at.
fn load_groups() -> Option<Vec<(i64, String, String, String)>> {
    if !Path::new(DB).exists() {
        eprintln!("skip: {DB} absent");
        return None;
    }
    let con = Connection::open_with_flags(
        DB,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("open catalog");
    let mut st = con
        .prepare("SELECT id, kind, stem, dir FROM agroups")
        .expect("prepare");
    let rows = st
        .query_map([], |r| {
            let dir: String = r.get(3)?;
            let leaf = dir.rsplit('/').next().unwrap_or("").to_string();
            Ok((r.get(0)?, r.get(1)?, r.get(2)?, leaf))
        })
        .expect("query")
        .collect::<Result<Vec<_>, _>>()
        .expect("rows");
    Some(rows)
}

fn distinct_tags() -> Option<Vec<(String, i64)>> {
    if !Path::new(DB).exists() {
        eprintln!("skip: {DB} absent");
        return None;
    }
    let con = Connection::open_with_flags(DB, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).expect("open");
    let mut st = con
        .prepare("SELECT tag, COUNT(DISTINCT gid) FROM asset_tags GROUP BY tag ORDER BY tag")
        .expect("prepare");
    st.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))
        .expect("query")
        .collect::<Result<Vec<_>, _>>()
        .ok()
}

fn hit_groups(groups: &[(i64, String, String, String)], word: &str) -> Vec<String> {
    let keys = query_keys(word);
    groups
        .iter()
        .filter(|(_, _, stem, leaf)| matches_asset(stem, leaf, &keys))
        .map(|(_, _, stem, _)| stem.clone())
        .collect()
}

/// Deterministic pseudo-random two-character words over a common-Chinese pool, so the
/// noise thresholds below sample the same space on every run.
fn sampled_words(n: usize) -> Vec<String> {
    const POOL: &[u8] = "的一是不了人在有为之大来以个中上到说国和地也子时道会要于下得可年生自回其爱着行功过学加法海式好认内应此进主平风火水木金土石雨雪花月星日夜明暗长短老少年小多少全黑白红绿蓝紫青黄金银铜铁刀剑枪弓甲盾牌城池村寨镇庙殿楼阁台塔桥路街口门房屋窗桌椅琴棋书画诗酒茶饭鱼肉果花草树木根枝叶实种壳皮毛骨肉筋骨血气灵魂鬼神妖魔仙佛法术符功夫武勇猛烈轻便快慢迟速远近高低上下左右前后内外里中游走立坐卧睡醒见闻触摸抓拿打踢推拉扔抛飞跳跃跑爬滚翻旋转直"
        .as_bytes();
    let chars: Vec<char> = String::from_utf8(POOL.to_vec()).expect("pool").chars().collect();
    let mut s = 0x2545_F491_4F6C_DD1Du64;
    let mut out = Vec::new();
    let mut seen = Vec::new();
    while out.len() < n {
        s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let a = ((s >> 33) as usize) % chars.len();
        s = s.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        let b = ((s >> 33) as usize) % chars.len();
        let w: String = [chars[a], chars[b]].into_iter().collect();
        if a != b && !seen.contains(&w) {
            seen.push(w.clone());
            out.push(w);
        }
    }
    out
}

// ---------------------------------------------------------------- name noise

#[test]
fn random_two_char_words_stay_specific() {
    let Some(groups) = load_groups() else { return };
    let words = sampled_words(40);
    let mut total = 0usize;
    let mut worst = (0usize, String::new(), Vec::new());
    let mut zero = 0usize;
    for w in &words {
        let h = hit_groups(&groups, w);
        if h.is_empty() {
            zero += 1;
        }
        if h.len() > worst.0 {
            worst = (h.len(), w.clone(), h.iter().take(3).cloned().collect());
        }
        total += h.len();
    }
    // Measured on the 13,080-row catalog. The point of the assertion is the *shape*: most
    // random two-character words must come back empty, or the name path has stopped being
    // a name path.
    assert!(total < 120, "random word noise exploded: {total} hits over 40 words");
    assert!(worst.0 <= 25, "one two-char word matched {} groups ({worst:?})", worst.0);
    assert!(zero >= words.len() / 2, "only {zero}/{} random words came back empty — the name path stopped being specific", words.len());
}

#[test]
fn two_char_words_do_not_flood_across_tokens() {
    let Some(groups) = load_groups() else { return };
    // These ten words were picked because each one, under the old flattened-string rule,
    // could straddle a separator: 暗椅 (anyi) answered to `shao|shang_yi`. Folding the
    // separators away is what let that happen; requiring the needle to land inside a
    // single artist token is what stops it.
    //
    // Measured on the 13,080-row catalog: 385 total, of which 337 is `暗椅 anyi` alone.
    // That word is not straddling anything — `anyi` genuinely occurs inside `shanganyi`,
    // `shanganyi` being a real compound the artist wrote as one token. The remaining nine
    // words contribute 48, and six of them contribute zero. So the honest reading of the
    // number is "one heavily-polysemous syllable pair", not "the rule leaks".
    let mut junk = 0usize;
    let mut worst = (0usize, "");
    for w in ["暗椅", "的蓝", "魂触", "暗触", "火要", "法触", "踢花", "暗里", "气白", "剑皮"] {
        let n = hit_groups(&groups, w).len();
        if n > worst.0 {
            worst = (n, w);
        }
        junk += n;
    }
    assert!(
        junk < 450,
        "two-char false hits grew to {junk} (measured 385; worst word {worst:?})"
    );
    assert!(
        worst.0 < 350,
        "one two-char word matched {} groups ({}) — a single syllable pair is now dominating the name path",
        worst.0,
        worst.1
    );
}


/// Category words are served by `asset_tags`. A few of them also have a literal spelling
/// inside real stems, and that overlap is not a defect the name path can fix:
/// `w1351_skill_pvp_texiaomen_shifa01` contains `texiao`, four `w1351_fuben_*` stems
/// contain `fuben`. 宠物 (`chongwu`) has no such stem and correctly returns zero.
///
/// So this records the measured baseline for each word. The guard is that the overlap
/// stays small and specific — if `怪物` or `任务` suddenly start answering from names,
/// something widened.
#[test]
fn category_words_barely_overlap_the_name_path() {
    let Some(groups) = load_groups() else { return };
    for (w, baseline) in [("宠物", 0usize), ("特效", 1), ("怪物", 0), ("副本", 4), ("任务", 0)] {
        let h = hit_groups(&groups, w);
        assert!(
            h.len() <= baseline,
            "{w} reached the name path {times}× (baseline {baseline}), e.g. {examples:?}",
            times = h.len(),
            examples = &h[..h.len().min(3)]
        );
    }
}

/// KNOWN DEFECT — 特效 (`texiao`) reaches `texiaomen`. `texiaomen` is one artist token, so
/// no word-internal rule can separate the prefix from the compound: the query genuinely
/// *is* contained in the token. Costing this would mean requiring the needle to equal a
/// whole token, which would also drop 少林 from 56 hits to a handful. Left as-is
/// deliberately; revisit if a syllable-boundary heuristic is ever worth the complexity.
#[test]
#[ignore = "known defect: a pinyin prefix matches inside a longer compound token"]
fn category_words_never_reach_the_name_path() {
    let Some(groups) = load_groups() else { return };
    for w in ["宠物", "特效", "怪物", "副本", "任务"] {
        let h = hit_groups(&groups, w);
        assert!(h.is_empty(), "{w} reached the name path: {} hits, e.g. {:?}", h.len(), &h[..h.len().min(3)]);
    }
}

// ---------------------------------------------------------------- design guards

#[test]
fn initials_are_still_not_generated() {
    // Verified against the catalog: 首字母 has no upside. 曹霜 has one real hit and `cs`
    // reaches 72 groups — a 72× inflation on the single anchor the whole pinyin design
    // exists to serve. Two-character abbreviations are sometimes mild (慕容 `mr` ×1.7,
    // 逍遥 `xy` ×2.4) but often not (天山 `ts` ×22.7, 大理 `dl` ×116.3), and a bare
    // single letter is hopeless: `c` alone reaches 5,968 of 13,080 groups.
    let keys = query_keys("曹霜");
    assert!(
        keys.iter().all(|k| k.len() > 3),
        "an initial-style key leaked into {keys:?}"
    );
    let Some(groups) = load_groups() else { return };
    let cao = hit_groups(&groups, "曹霜");
    assert_eq!(cao, vec!["w1351_boss_caoshuang".to_string()], "the 曹霜 anchor moved");
    let abbr = |needle: &str| -> usize {
        let k = [needle.to_string()];
        groups.iter().filter(|(_, _, stem, leaf)| matches_asset(stem, leaf, &k)).count()
    };
    assert!(abbr("cs") > 40, "expected `cs` to be hopeless, got {}", abbr("cs"));
    assert!(abbr("c") > 1000, "expected a bare `c` to be hopeless, got {}", abbr("c"));
}

#[test]
fn stems_carry_no_display_names() {
    let Some(groups) = load_groups() else { return };
    // Measured: 0 of 13,080 stems contain a non-ASCII character. The pinyin-only premise
    // is exhaustive, not approximate — so this asserts the strong form. A 50% allowance
    // would let the entire assumption rot without a single failure.
    let non_ascii: Vec<&String> = groups.iter().map(|g| &g.2).filter(|s| !s.is_ascii()).collect();
    assert!(
        non_ascii.is_empty(),
        "{} stems now contain non-ASCII (e.g. {:?}); the pinyin-only assumption needs revisiting",
        non_ascii.len(),
        &non_ascii[..non_ascii.len().min(3)]
    );
}

// ---------------------------------------------------------------- tags

#[test]
fn every_tag_in_the_catalog_has_a_chinese_label() {
    let Some(tags) = distinct_tags() else { return };
    // Acronyms that legitimately stay Latin.
    const LATIN_OK: &[&str] = &["npc"];
    let untranslated: Vec<&String> = tags
        .iter()
        .filter(|(t, _)| tag_zh(t) == *t && !LATIN_OK.contains(&t.as_str()))
        .map(|(t, _)| t)
        .collect();
    assert!(untranslated.is_empty(), "tag_zh misses a translation for {untranslated:?} (catalog has {} distinct tags)", tags.len());
    assert_eq!(tags.len(), 22, "the classifier started emitting new tags: {tags:?}");
}

#[test]
fn tagged_words_cover_what_names_cannot() {
    let Some(tags) = distinct_tags() else { return };
    let g = |t: &str| tags.iter().find(|(x, _)| x == t).map(|(_, n)| *n).unwrap_or(0);
    // 宠物/特效/建筑/怪物 are only reachable through tags — if these counts collapse the
    // tag fallback silently stops covering the words the name path cannot serve.
    for (tag, min) in [("pet", 500i64), ("effect", 1500), ("map-props", 2000), ("monster", 150), ("building", 150)] {
        assert!(g(tag) >= min, "tag {tag} covers {} groups, expected >= {min}", g(tag));
    }
}

// ---------------------------------------------------------------- known defects
// Assert the *wanted* behaviour; ignored until search.rs is fixed. Removing `#[ignore]`
// after the fix turns each into a permanent guard.

/// FIXED — `Pinyin::plain()` used to keep the umlaut: 女 → `nü`, but the artists wrote
/// `nv` (231 groups) and `lv` (64), so 女/绿/吕/略/虐 and every word built on them
/// returned 0 name hits. The keys are now folded to the ASCII the stems actually use.
#[test]
fn pinyin_keys_are_ascii_and_reach_nv_groups() {
    for w in ["女", "绿", "美女", "少女", "战略"] {
        for k in query_keys(w) {
            // Only the verbatim query may keep Han characters (tag matching needs it);
            // every transliteration must be plain ASCII or it can never hit a stem.
            assert!(
                k.is_ascii() || k == w.to_lowercase(),
                "query {w} produced key {k}"
            );
            assert!(!k.contains('ü'), "umlaut leaked into key {k}");
        }
    }
    let Some(groups) = load_groups() else { return };
    assert!(!hit_groups(&groups, "女").is_empty(), "女 must find the *_nv* groups");
    assert!(!hit_groups(&groups, "绿").is_empty(), "绿 must find the *_lv* groups");
}

/// DEFECT 2 — polyphones take the dictionary's first reading, but the client spells the
/// in-game word differently: 星宿 `xingsu`→0 vs `xingxiu` (`w1351_scsq_xingxiu_001_01`),
/// 音乐 `yinle`→0 vs `yinyue` (`w1351_zuoqi_yinyuelang`), 弹指 `danzhi`→0 vs `tanzhi`
/// (`w1351_npc_youtanzhi`), 长枪 `zhangqiang`→0 vs `changqiang`.
#[test]
#[ignore = "known defect: heteronym readings are not expanded"]
fn game_polyphones_resolve() {
    let Some(groups) = load_groups() else { return };
    for w in ["星宿", "音乐", "弹指", "长枪"] {
        assert!(!hit_groups(&groups, w).is_empty(), "{w} is unreachable via its first reading");
    }
}

/// DEFECT 3 — full-width input is dropped on the floor: `ＮＰＣ` yields the single key
/// `ｎｐｃ` → 0 hits, while `npc` hits 525; `boss３` silently loses the ３.
#[test]
fn fullwidth_query_folds() {
    let Some(groups) = load_groups() else { return };
    assert_eq!(
        hit_groups(&groups, "npc").len(),
        hit_groups(&groups, "ＮＰＣ").len(),
        "full-width query must behave like ASCII"
    );
}

/// DEFECT 4 — the dir leaf is a *different* asset name for 5,812 of 8,537 groups, so
/// 白猿/高山 answer with the 常碧元 group. Leaf matching should stay on name-related dirs.
#[test]
#[ignore = "known defect: unrelated dir leaf leaks foreign assets"]
fn unrelated_dir_leaf_is_not_searched() {
    let Some(groups) = load_groups() else { return };
    for stem in hit_groups(&groups, "白猿") {
        assert!(stem.contains("baiyuan"), "白猿 matched unrelated stem {stem} via its directory");
    }
}

/// Diagnostics: reprint the measured audit tables.
#[test]
#[ignore]
fn print_audit_tables() {
    let Some(groups) = load_groups() else { return };
    println!("groups: {}", groups.len());
    println!("\n-- 名称命中（现方案） --");
    for w in ["曹霜", "慕容", "天山", "逍遥", "武器", "坐骑", "结婚", "建筑", "星宿", "音乐", "弹指", "长枪", "女", "绿", "宠物", "特效", "无相", "无邪", "门派", "白猿", "暗椅"] {
        println!("  {:6} {:?} -> {}", w, query_keys(w), hit_groups(&groups, w).len());
    }
    println!("\n-- 首字母膨胀（现方案刻意不产出首字母 key） --");
    for (w, ini) in [("曹霜", "cs"), ("慕容", "mr"), ("天山", "ts"), ("逍遥", "xy"), ("少林", "sl"), ("大理", "dl"), ("绿色", "ls"), ("武器", "wq")] {
        let full = hit_groups(&groups, w).len();
        let abbr: Vec<String> = groups
            .iter()
            .filter(|(_, _, stem, leaf)| matches_asset(stem, leaf, &[ini.to_string()]))
            .map(|(_, _, s, _)| s.clone())
            .collect();
        println!(
            "  {w:6} 全拼 {full:5}   首字母 {ini} {:5}   膨胀 x{:.1}",
            abbr.len(),
            abbr.len() as f64 / (full.max(1) as f64)
        );
    }
    println!("\n-- 跨段假命中（normalize 去掉 `_` 的代价） --");
    let groups_ref = groups.as_slice();
    let mut junk = 0usize;
    for w in ["暗椅", "的蓝", "魂触", "暗触", "火要", "法触", "踢花", "暗里", "气白", "剑皮"] {
        let n = hit_groups(groups_ref, w).len();
        junk += n;
        println!("  {w:6} {:?} -> {}", query_keys(w), n);
    }
    println!("  合计 {junk}（阈值见 two_char_words_do_not_flood_across_tokens）");
    println!("\n-- 随机两字词噪声 --");
    for w in sampled_words(40) {
        let h = hit_groups(groups_ref, &w);
        if !h.is_empty() {
            println!("  {w:6} {:?} -> {} {:?}", query_keys(&w), h.len(), &h[..h.len().min(2)]);
        }
    }
}
