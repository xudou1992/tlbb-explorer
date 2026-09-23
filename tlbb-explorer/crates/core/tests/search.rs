//! The Chinese-query path that shipped names require: 曹霜 must reach `caoshuang`.

use std::path::Path;
use tlbb_core::catalog::search::{matches, matches_asset, normalize, query_keys};

#[test]
fn han_query_expands_to_pinyin() {
    let keys = query_keys("曹霜");
    assert!(keys.iter().any(|k| k == "caoshuang"), "{keys:?}");
    assert!(keys.iter().any(|k| k == "曹霜"));
    assert_eq!(query_keys("boss3"), ["boss3"], "ascii passes through");
}

#[test]
fn separators_do_not_matter() {
    assert!(matches("w1351_boss-caoshuang", &query_keys("曹霜")));
    assert!(matches("Cao Shuang", &query_keys("曹霜")));
    assert_eq!(normalize("a/b_c.d"), "abcd");
}

#[test]
fn whole_path_is_not_searched() {
    // `.../npc/sifeng...` used to answer to the initials of 曹霜; the leaf must not.
    let keys = query_keys("曹霜");
    assert!(!matches_asset("w1351_npc_sifengmolinghun", "data/source/npc/quest/w1351_npc_sifengmolinghun", &keys));
    assert!(matches_asset("w1351_boss_caoshuang", "data/source/npc/quest/w1351_boss_caoshuang", &keys));
}

#[test]
fn a_two_character_word_stays_specific() {
    let groups: Vec<(String, String)> = if Path::new("D:/TLGL/.scratch/resources.db").exists() {
        let cat = tlbb_core::catalog::Catalog::open_ro("D:/TLGL/.scratch/resources.db").unwrap();
        cat.groups(20_000)
            .unwrap()
            .into_iter()
            .map(|g| (g.stem, g.dir))
            .collect()
    } else {
        eprintln!("skip: catalog absent");
        return;
    };
    for word in ["曹霜", "宠物", "门派", "少林"] {
        let hits = groups
            .iter()
            .filter(|(s, d)| matches_asset(s, d, &query_keys(word)))
            .count();
        assert!(hits < 120, "{word} matched {hits} of {} groups", groups.len());
    }
}
