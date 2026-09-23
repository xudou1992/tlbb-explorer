//! Presentation rules that the card builder also enforces. They are duplicated here on
//! purpose — `crates/core` must stay untouched — but they must stay byte-for-byte
//! compatible with `src/bin/asset_cards.rs`, otherwise the shell and the report would
//! describe the same asset differently.

use tlbb_core::catalog::Group;

/// Review scenario, derived from the group kind alone so sampling never depends on a
/// guessed label.
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

/// Silhouette to draw when no image can be decoded. Same seven keys as the card report.
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

/// 792 of the 8,537 groups carry no path at all; those fall back to their identifier
/// rather than showing an empty title or an invented name.
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

/// 有没有能对人说的名字。既没茎名又没路径的组只能靠 16 位编号区分——这类组
/// 一律不进默认列表：用户不该在首屏看到编号，更不该拿编号当标题。
pub fn is_named(g: &Group) -> bool {
    if !g.stem.is_empty() {
        return true;
    }
    g.hub_path
        .rsplit('/')
        .next()
        .and_then(|base| base.split('.').next())
        .map(|b| !b.is_empty())
        .unwrap_or(false)
}

/// Subtitle built only by cutting the name apart, so it can never invent a translation.
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

/// Grade worded for a player: the letter stays (it is the ladder's name), the plain
/// phrase carries the meaning. No storage or format terms.
pub fn grade_words(letter: &str) -> (&'static str, &'static str) {
    match letter.chars().next() {
        Some('A') => ("完整定位", "主体和它用到的零件都找到了"),
        Some('B') => ("主体定位", "主体能打开，部分零件只有名字"),
        Some('C') => ("仅有名称", "只拿到主体，零件关系来自名字推断"),
        _ => ("只是线索", "主体没能打开，这条记录只能当作线索"),
    }
}

#[cfg(test)]
mod tests {
    use super::{display_name, placeholder_for, scenario_of, subtitle};
    use tlbb_core::catalog::Group;

    fn group(stem: &str, hub_path: &str, kind: &str) -> Group {
        Group {
            id: 1,
            hub: 7,
            hub_path: hub_path.into(),
            dir: String::new(),
            stem: stem.into(),
            kind: kind.into(),
            n: 1,
            n_mesh: 0,
            n_mtl: 0,
            n_ani: 0,
            n_ske: 0,
            n_tex: 0,
        }
    }

    #[test]
    fn scenarios_match_the_card_report() {
        assert_eq!(scenario_of("npc"), "角色");
        assert_eq!(scenario_of("map-prop"), "场景");
        assert_eq!(scenario_of("shared-material"), "物品");
        assert_eq!(scenario_of("weird"), "其他");
    }

    #[test]
    fn placeholders_stay_within_the_seven_sprites() {
        let known = ["character", "beast", "building", "effect", "panel", "item", "node"];
        for kind in ["npc", "player", "map-prop", "effect", "ui", "shared-material", "other"] {
            let p = placeholder_for(scenario_of(kind), &[]);
            assert!(known.contains(&p), "{kind} -> {p}");
        }
        assert_eq!(placeholder_for("npc", &["坐骑".into()]), "beast");
        assert_eq!(placeholder_for("other", &["武器".into()]), "item");
        assert_eq!(placeholder_for("map-prop", &["建筑".into()]), "building");
    }

    #[test]
    fn names_are_never_invented() {
        assert_eq!(display_name(&group("w1351_a_b01", "x/y/w1351_a_b01.mdl", "npc")), "w1351_a_b01");
        assert_eq!(display_name(&group("", "data/ui/icon_mr.psd", "ui")), "icon_mr");
        assert_eq!(subtitle("w1351_boss_caoshuang", "npc"), "角色 · caoshuang");
        // The subtitle tail is always a literal substring of the shown name.
        for stem in ["w1351_nan_s_yifu_mjrmdz", "", "x"] {
            let n = display_name(&group(stem, "", "other"));
            let tail = subtitle(&n, "other").split('·').last().unwrap().trim().to_string();
            assert!(!tail.is_empty() && n.contains(&tail), "{stem} -> {n} / {tail}");
        }
    }
}
