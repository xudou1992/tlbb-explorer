//! The catalog's query plans are part of its contract, not an implementation detail.
//!
//! `textures_in_dir` runs once per group during a workbench cold start — 12,159 times on
//! the shipped library. Each call asks for
//! `dir = ? AND type = 'texture' ORDER BY original DESC LIMIT 8`. When the only index on
//! `resources` was `ix_res_dir(dir)`, SQLite had to fetch every row of the directory and
//! sort it in a temp B-tree; measured over the full library that made cold start 114.6s.
//! The covering index `ix_res_dir_type_original(dir, type, original DESC)` answers the
//! whole query inside the index and took it to 2.2s — a 52x change produced by one index
//! and no code change at all.
//!
//! That means the failure mode here is silent: drop the index, or add it to the builder
//! but forget to run `ANALYZE`, and nothing breaks — the product just gets 50x slower.
//! So the plan is asserted, and the assertion is written against the *plan*, not a
//! timing, so it stays meaningful on any machine and under any load.

use rusqlite::{Connection, OpenFlags};

fn db_path() -> Option<std::path::PathBuf> {
    let p = std::path::PathBuf::from(
        std::env::var("TLBB_DB").unwrap_or_else(|_| "D:/TLGL/.scratch/resources.db".to_string()),
    );
    p.exists().then_some(p)
}

fn plan(con: &Connection, sql: &str, args: &[&dyn rusqlite::ToSql]) -> Vec<String> {
    let mut st = con.prepare(&format!("EXPLAIN QUERY PLAN {sql}")).expect("prepare plan");
    st.query_map(args, |r| r.get::<_, String>(3))
        .expect("plan rows")
        .collect::<rusqlite::Result<Vec<_>>>()
        .expect("collect plan")
}

/// The exact statement `Catalog::textures_in_dir` issues, character for character.
const TEXTURES_IN_DIR: &str =
    "SELECT hash, path FROM resources WHERE type = 'texture' AND dir = ?1 ORDER BY original DESC LIMIT 8";

#[test]
fn textures_in_dir_is_answered_by_a_covering_index() {
    let Some(db) = db_path() else {
        eprintln!("跳过：找不到 resources.db");
        return;
    };
    let con = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("open read-only");

    let steps = plan(&con, TEXTURES_IN_DIR, &[&"ui/icon/skill"]);

    assert!(
        steps.iter().any(|s| s.contains("ix_res_dir_type_original")),
        "textures_in_dir 不再走覆盖索引，冷启动会退回 50 倍慢。实际计划：{steps:?}"
    );
    assert!(
        !steps.iter().any(|s| s.contains("TEMP B-TREE")),
        "textures_in_dir 又出现了临时 B 树排序——说明索引列序被改坏了。实际计划：{steps:?}"
    );
}

/// The other three hot queries must keep *an* index on the group id. They are cheap
/// individually (0.4–0.9s across the whole library even before the fix) but they run once
/// per group, so losing the index turns each into a 13,080-iteration full scan.
///
/// The assertion is written as "an index seek on the group column", not "this exact index
/// name": for `group_names` SQLite correctly prefers the `(gid, name)` primary-key
/// autoindex over the narrower `ix_an_g(gid)`, because the wider one also satisfies
/// `ORDER BY name` and avoids a temp B-tree. Pinning the narrower index by name would have
/// been asserting a worse plan.
#[test]
fn the_per_group_queries_all_stay_index_backed() {
    let Some(db) = db_path() else {
        eprintln!("跳过：找不到 resources.db");
        return;
    };
    let con = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("open read-only");

    // (label, sql, the alias SQLite will name in the plan, the indexed column)
    //
    // EXPLAIN QUERY PLAN prints the *alias*, not the table name ("SEARCH m USING INDEX
    // ix_am_g"), so the expectation has to be written against the alias.
    let cases: &[(&str, &str, &str, &str)] = &[
        (
            "members",
            "SELECT m.hash, m.role, r.path, r.type, r.pak, r.offset, r.original, r.ver \
             FROM amembers m LEFT JOIN resources r ON r.hash = m.hash \
             WHERE m.gid = ?1 ORDER BY m.role, r.path",
            "m",
            "gid",
        ),
        (
            "refs_from",
            "SELECT r.name, r.kind, r.to_hash, x.path, r.ambig FROM refs r \
             LEFT JOIN resources x ON x.hash = r.to_hash \
             WHERE r.from_hash = ?1 ORDER BY r.kind, r.name",
            "r",
            "from_hash",
        ),
        (
            "group_names",
            "SELECT name, cls FROM agroup_names WHERE gid = ?1 ORDER BY name",
            "agroup_names",
            "gid",
        ),
        (
            "tags",
            "SELECT tag, confidence FROM asset_tags WHERE gid = ?1 ORDER BY confidence, tag",
            "asset_tags",
            "gid",
        ),
    ];

    for (label, sql, alias, column) in cases {
        let steps = plan(&con, sql, &[&1i64]);
        let seek = format!("SEARCH {alias} USING INDEX");
        assert!(
            steps
                .iter()
                .any(|s| s.starts_with(&seek) && s.contains(&format!("({column}=?"))),
            "{label} 不再按 {alias}.{column} 走索引寻找，每次冷启动会变成 13080 次全表扫。\
             实际计划：{steps:?}"
        );
        assert!(
            !steps.iter().any(|s| s.contains("SCAN ")),
            "{label} 退化成全表扫描。实际计划：{steps:?}"
        );
    }
}

/// `ANALYZE` must have been run: without `sqlite_stat1` the planner falls back to
/// guessed row counts, and a wrong estimate is what lets two structurally identical
/// queries plan differently — the exact class of bug that had the workbench and the
/// report disagreeing about the same asset before P3-C.
#[test]
fn the_planner_has_real_statistics() {
    let Some(db) = db_path() else {
        eprintln!("跳过：找不到 resources.db");
        return;
    };
    let con = Connection::open_with_flags(&db, OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("open read-only");

    let has_stat: bool = con
        .query_row(
            "SELECT COUNT(*) > 0 FROM sqlite_master WHERE name = 'sqlite_stat1'",
            [],
            |r| r.get(0),
        )
        .expect("look for sqlite_stat1");
    assert!(
        has_stat,
        "resources.db 没有 sqlite_stat1 —— dbbuild.py 末尾的 analyze() 没跑，\
         规划器只能靠猜行数，同一个查询在不同入口可能选中不同计划。"
    );

    let n: i64 = con
        .query_row("SELECT COUNT(*) FROM sqlite_stat1", [], |r| r.get(0))
        .expect("count stats");
    assert!(n > 10, "sqlite_stat1 只有 {n} 行，统计不完整");
}
