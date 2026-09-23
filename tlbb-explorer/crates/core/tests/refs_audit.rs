//! 反向引用（"谁在使用它"）的取证审计。
//!
//! 这一栏只在**别的资产真的引用了它**时才有意义。库里有四类边会把内部组成关系
//! 伪装成外部引用，本文件把它们钉死：
//!
//! 1. `refs` 里 `from_hash` 与 `to_hash` 同属一个 `agroup` 的**内部边**（约占全表四成）；
//! 2. `refs` 里 `from_hash = to_hash` 的**自引用**（一个 `.ske` 的文件名表里写着它自己，
//!    `dbbuild.py::add_content_refs` 把 relations 里的自引用挡了、没挡 refs）；
//! 3. `relations` 里 `same-stem` / `model-part` 这类**按目录与同名推断**出来的边
//!    （见 `.scratch/dbbuild.py::build_relations`），它们不是文件内容里的引用；
//! 4. 同目录、同文件名只差扩展名的"孪生文件"：资产拆分器把 `x.mdl` 和 `x.ske`
//!    拆进了两个 gid，于是"这个骨骼被它自己的模型使用"会从"排除本资产成员"
//!    这个口径的缝里漏出来。`AUDIT_SQL` 把这一条也堵上。
//!
//! 真实库不在时全部跳过 —— 这些断言是对**数据**立的规矩，不是对空库立的。
//! 阈值写成区间而非精确行数：`resources.db` 由别的会话重新生成。
//!
//! 只读打开，临时表只存在于本连接的内存里，绝不落盘到 `resources.db`。

use std::path::Path;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::catalog::Catalog;

const DB: &str = "D:/TLGL/.scratch/resources.db";

/// 一个资产的外部使用者：只读 `refs`（内容取证）+ 五道过滤。
/// 与 `asset_report.rs::in_edges` + `external_users` 同口径（含它对空 `from_path` 的
/// `is_empty()` 跳过），只多了第 4 条孪生过滤。参数 1 = gid。
const AUDIT_SQL: &str = "SELECT r.from_hash, r.from_path, r.to_hash, r.name, r.kind \
     FROM refs r \
     JOIN amembers tgt ON tgt.hash = r.to_hash AND tgt.gid = ?1 \
     LEFT JOIN amembers src ON src.hash = r.from_hash AND src.gid = ?1 \
     LEFT JOIN gid_of fg ON fg.hash = r.from_hash \
     LEFT JOIN agroups fgp ON fgp.id = fg.gid \
     LEFT JOIN resources fr ON fr.hash = r.from_hash \
     LEFT JOIN resources tr ON tr.hash = r.to_hash \
     WHERE r.from_hash <> r.to_hash AND src.hash IS NULL \
       AND r.from_path IS NOT NULL AND r.from_path <> '' \
       AND NOT EXISTS (SELECT 1 WHERE fr.name IS NOT NULL AND tr.name IS NOT NULL \
                AND fgp.dir IS NOT NULL \
                AND fgp.dir = (SELECT dir FROM agroups WHERE id = ?1) \
                AND substr(lower(fr.name), 1, length(fr.name) - length(fr.ext)) \
                    = substr(lower(tr.name), 1, length(tr.name) - length(tr.ext)))";

/// 打开只读连接，并把审计需要的两张派生表建成内存临时表（`amembers.hash`、
/// `resources.name` 上都没有索引，用关联子查询会退化成全表扫）。
fn db() -> Option<Connection> {
    if !Path::new(DB).exists() {
        eprintln!("skip: {DB} 不存在");
        return None;
    }
    let con = Connection::open_with_flags(
        DB,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("以只读方式打开 resources.db");
    for t in ["refs", "relations", "amembers", "agroups", "dangling", "agroup_names"] {
        let n: i64 = con
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?1",
                [t],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(n, 1, "缺少表 {t}：审计口径已失效，请同步修改本文件");
    }
    con.execute_batch(
        "CREATE TEMP TABLE gid_of AS SELECT hash, MIN(gid) gid FROM amembers GROUP BY hash;
         CREATE UNIQUE INDEX gid_of_hash ON gid_of(hash);
         CREATE TEMP TABLE res_names AS SELECT lower(name) n, COUNT(*) k FROM resources GROUP BY 1;
         CREATE INDEX res_names_n ON res_names(n);",
    )
    .expect("建临时派生表");
    Some(con)
}

fn count(con: &Connection, sql: &str, p: &[&dyn rusqlite::ToSql]) -> i64 {
    con.query_row(sql, p, |r| r.get(0)).unwrap_or(-1)
}

fn rows<T>(
    con: &Connection,
    sql: &str,
    p: &[&dyn rusqlite::ToSql],
    mut f: impl FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<T>,
) -> Vec<T> {
    let mut st = con.prepare(sql).unwrap();
    st.query_map(p, &mut f)
        .unwrap()
        .filter_map(|r| r.ok())
        .collect()
}

/// 入边最多的资产优先抽查 —— 它们最容易藏污。
fn sample_gids(con: &Connection, n: i64) -> Vec<i64> {
    rows(
        con,
        "SELECT tgt.gid, COUNT(*) c FROM refs r JOIN gid_of tgt ON tgt.hash = r.to_hash \
         GROUP BY 1 ORDER BY c DESC, 1 LIMIT ?1",
        &[&n],
        |r| r.get::<_, i64>(0),
    )
}

/// 过滤不是空转：`refs` 里确实堆着内部边和自引用。
#[test]
fn pollution_is_real_so_the_filter_is_load_bearing() {
    let Some(con) = db() else { return };
    let refs = count(&con, "SELECT COUNT(*) FROM refs", &[]);
    let internal = count(
        &con,
        "SELECT COUNT(*) FROM refs r JOIN gid_of f ON f.hash = r.from_hash \
         JOIN gid_of t ON t.hash = r.to_hash AND t.gid = f.gid",
        &[],
    );
    let selfs = count(&con, "SELECT COUNT(*) FROM refs WHERE from_hash = to_hash", &[]);
    assert!(refs > 10_000, "refs 只有 {refs} 行，样本太小");
    assert!(
        internal > refs / 10,
        "内部边只有 {internal}/{refs}（不足一成）：过滤可能已经下沉到建表阶段，口径要重估"
    );
    assert!(selfs > 0, "自引用为 0：dbbuild 的 self 分支可能已改，口径要重估");
    assert!(selfs < internal, "自引用 {selfs} 不该多于内部边 {internal}");
}

/// 核心不变量：外部使用者列表里不得出现内部边、自引用、同目录同名孪生。
#[test]
fn no_internal_edge_survives_the_filter() {
    let Some(con) = db() else { return };
    let gids = sample_gids(&con, 2000);
    assert!(!gids.is_empty(), "agroups/amembers 为空");
    let mut scanned = 0usize;
    for gid in &gids {
        let members: Vec<String> = rows(
            &con,
            "SELECT hash FROM amembers WHERE gid = ?1",
            &[gid],
            |r| r.get::<_, String>(0),
        );
        for (from_hash, from_path, to_hash, _name, kind) in rows(&con, AUDIT_SQL, &[gid], |r| {
            Ok((
                r.get::<_, String>(0)?,
                r.get::<_, String>(1)?,
                r.get::<_, String>(2)?,
                r.get::<_, String>(3)?,
                r.get::<_, String>(4)?,
            ))
        }) {
            scanned += 1;
            assert!(
                !members.contains(&from_hash),
                "gid={gid}：本资产成员 {from_hash} 被当成外部使用者"
            );
            assert_ne!(
                from_hash, to_hash,
                "gid={gid}：自引用 {from_path} 漏进了外部统计"
            );
            assert!(from_path.contains('/'), "gid={gid}：{from_path} 不像路径");
            assert!(kind.starts_with('.'), "gid={gid}：kind {kind} 不是扩展名");
        }
    }
    assert!(scanned > 0, "抽查的资产一条外部边都没有，取样或口径有问题");
}

/// 展示层拿 `from_path` 当唯一线索，于是"引用者没有路径"等于"这条证据消失"。
/// `refs` 里确实存在没有路径的引用者（未命名的 JBCF），所以展示必须有 `name` 兜底。
/// 建表把 `from_path` 补齐之后这条会失败 —— 那时连同兜底逻辑一起删。
#[test]
fn blank_from_path_swallows_real_users() {
    let Some(con) = db() else { return };
    let blank = count(
        &con,
        "SELECT COUNT(*) FROM refs r WHERE (r.from_path IS NULL OR r.from_path = '') \
         AND EXISTS (SELECT 1 FROM amembers m WHERE m.hash = r.to_hash)",
        &[],
    );
    let lost = count(
        &con,
        "SELECT COUNT(*) FROM refs r JOIN gid_of t ON t.hash = r.to_hash \
         LEFT JOIN gid_of f ON f.hash = r.from_hash \
         WHERE (r.from_path IS NULL OR r.from_path = '') AND r.from_hash <> r.to_hash \
           AND (f.hash IS NULL OR f.gid <> t.gid)",
        &[],
    );
    eprintln!("refs.from_path 为空的行 {blank}，其中会被外部使用者口径吞掉的 {lost}");
    assert!(blank > 0, "from_path 已全部补齐：连带路径的兜底显示可以删了");
    assert!(lost > 0, "空路径不再造成证据丢失：本测试该退休");
    assert!(
        lost < blank,
        "丢失 {lost} 不小于空路径 {blank}，说明 to_hash 全空的行也被算进来了"
    );
}

/// 已知的取样事实：过滤后"谁在使用它"对绝大多数资产应当是空的 —— 跨资产真实引用
/// 集中在少数共享文件（公共材质、基础骨骼）上。一栏几乎不出现的栏目才有信息量；
/// 一旦它普遍非空，八成是把内部组成又算成了使用者。
#[test]
fn external_users_are_rare_and_concentrated() {
    let Some(con) = db() else { return };
    let assets: i64 = count(&con, "SELECT COUNT(*) FROM agroups", &[]);
    let any_edge = count(
        &con,
        "SELECT COUNT(DISTINCT t.gid) FROM refs r JOIN gid_of t ON t.hash = r.to_hash",
        &[],
    );
    let external = count(
        &con,
        "SELECT COUNT(DISTINCT t.gid) FROM refs r JOIN gid_of t ON t.hash = r.to_hash \
         JOIN gid_of f ON f.hash = r.from_hash WHERE f.gid <> t.gid",
        &[],
    );
    eprintln!("谁在使用它：资产 {assets}，有任何入边 {any_edge}，有真正外部使用者 {external}");
    assert!(any_edge > 0 && assets > 0);
    assert!(
        external * 2 < any_edge,
        "有外部使用者的资产 {external} 多于有任何入边资产 {any_edge} 的一半：\
         先确认过滤条件没退化，再回来放宽本条阈值"
    );
}

/// 命名推断不等于引用；`refs` 里也不该混进推断 kind。
#[test]
fn naming_inference_is_not_a_reference() {
    let Some(con) = db() else { return };
    let inferred = count(
        &con,
        "SELECT COUNT(*) FROM relations WHERE rel IN ('same-stem','model-part')",
        &[],
    );
    let evidence = count(
        &con,
        "SELECT COUNT(*) FROM relations WHERE rel LIKE 'use-%' OR rel = 'ref'",
        &[],
    );
    assert!(inferred > 0, "relations 里没有推断边，本测试该重写");
    assert!(
        inferred > evidence / 3,
        "推断边 {inferred} 相对取证边 {evidence} 太少，报告口径可能已改"
    );
    let leaked = count(
        &con,
        "SELECT COUNT(*) FROM refs WHERE kind IN ('same-stem','model-part')",
        &[],
    );
    assert_eq!(leaked, 0, "refs 混入了命名推断的 kind");
    for rel in rows(
        &con,
        "SELECT DISTINCT rel FROM relations",
        &[],
        |r| r.get::<_, String>(0),
    ) {
        assert!(
            rel.starts_with("use-") || matches!(rel.as_str(), "ref" | "same-stem" | "model-part"),
            "未知 rel 语义：{rel}（先判定它是取证还是推断再入库）"
        );
    }
}

/// `refs` 未定位行 ⇄ `dangling` ⇄ `agroup_names` 必须严格一致：
/// 只有名字的引用绝不能在任何一栏被判成已定位。
///
/// 名字一律先 `lower()` 再比：`dangling.name` 是区分大小写的主键，而同一个虚拟文件系统
/// 里的文件名是不区分大小写的（`Material #0.tga` 与 `material #0.tga` 会占两行、
/// 互相匹配不上），直接等值比对会漏。
#[test]
fn unresolved_names_never_read_as_located() {
    let Some(con) = db() else { return };
    let orphan = count(
        &con,
        "SELECT COUNT(*) FROM refs r WHERE (r.to_hash IS NULL OR r.to_hash = '') \
         AND lower(r.name) NOT IN (SELECT lower(name) FROM dangling)",
        &[],
    );
    assert_eq!(orphan, 0, "有解析不出的引用名没进 dangling，报告会少报缺失");
    let fake = count(
        &con,
        "SELECT COUNT(*) FROM dangling d WHERE lower(d.name) IN \
         (SELECT lower(name) FROM refs WHERE to_hash IS NOT NULL AND to_hash <> '')",
        &[],
    );
    assert_eq!(fake, 0, "dangling 里有个名字其实能定位，会被误标成\"仅有名称\"");
    let locatable = count(
        &con,
        "SELECT COUNT(*) FROM dangling d JOIN res_names x ON x.n = lower(d.name)",
        &[],
    );
    assert_eq!(locatable, 0, "dangling 的名字其实对应某个真实文件");
    let wrong = count(
        &con,
        "SELECT COUNT(*) FROM agroup_names a WHERE lower(a.name) NOT IN \
         (SELECT lower(name) FROM dangling)",
        &[],
    );
    assert_eq!(
        wrong, 0,
        "报告\"引用了但没找到对应文件\"一栏有个名字不在 dangling 里"
    );
    // dangling.n_refs 合计应等于未定位引用行数：两处口径要能对上。
    let unresolved = count(
        &con,
        "SELECT COUNT(*) FROM refs WHERE to_hash IS NULL OR to_hash = ''",
        &[],
    );
    let summed = count(&con, "SELECT COALESCE(SUM(n_refs),0) FROM dangling", &[]);
    assert_eq!(
        unresolved, summed,
        "dangling.n_refs 合计 {summed} 与未定位引用 {unresolved} 不符"
    );
}

/// `ambig` 目前是死字段：要么确无歧义，要么多命中被静默压掉。
#[test]
fn ambiguous_flag_matches_reality() {
    let Some(con) = db() else { return };
    let flagged = count(&con, "SELECT COUNT(*) FROM refs WHERE ambig <> 0", &[]);
    let collisions = count(
        &con,
        "SELECT COUNT(*) FROM refs r JOIN res_names x ON x.n = lower(r.name) AND x.k > 1 \
         WHERE r.to_hash IS NOT NULL AND r.to_hash <> ''",
        &[],
    );
    if flagged == 0 {
        assert_eq!(
            collisions, 0,
            "有 {collisions} 条已定位引用其实同名多命中，却被标成无歧义"
        );
    }
    // refs 主键是 (from_hash, name)：同名多目标在这一层就被压掉了。
    let dup = count(
        &con,
        "SELECT COUNT(*) FROM (SELECT from_hash, name FROM refs GROUP BY 1,2 HAVING COUNT(*) > 1)",
        &[],
    );
    assert_eq!(dup, 0, "refs 主键失效，同一引用名出现了多行");
}

/// `Catalog::raw_refs_to` 不做任何过滤，只能当原始取证；面板必须走 `external_users`。
/// 修复前后都成立，因此不会随实现腐坏。
#[test]
fn refs_to_must_not_back_the_panel_untouched() {
    let Some(con) = db() else { return };
    let Some(cat) = Catalog::open_ro(DB).ok() else {
        eprintln!("skip: catalog 打不开");
        return;
    };
    let hash: Option<String> = con
        .query_row(
            "SELECT to_hash FROM refs WHERE from_hash = to_hash LIMIT 1",
            [],
            |r| r.get(0),
        )
        .ok();
    let Some(hash) = hash else { return };
    let Ok(raw) = cat.raw_refs_to(u64::from_str_radix(&hash, 16).unwrap()) else {
        return;
    };
    assert!(!raw.is_empty(), "refs_to 连自引用都没返回，数据变了");
    let gid = count(&con, "SELECT gid FROM amembers WHERE hash = ?1 LIMIT 1", &[&hash]);
    if gid < 0 {
        return;
    }
    let filtered = count(&con, &format!("SELECT COUNT(*) FROM ({AUDIT_SQL})"), &[&gid]);
    assert!(
        filtered < raw.len() as i64,
        "审计口径没剔掉 raw_refs_to 的任何一行（{} 条），过滤没生效",
        raw.len()
    );
}

/// The shipped API must never hand back an asset's own member as one of its users.
#[test]
fn external_users_never_reports_internal_edges() {
    let Some(con) = db() else { return };
    let cat = match Catalog::open_ro(DB) {
        Ok(c) => c,
        Err(_) => return,
    };
    let mut checked = 0usize;
    for gid in [1i64, 2, 16, 347, 1280, 1526, 1738] {
        let edges = match cat.external_users(gid) {
            Ok(e) => e,
            Err(_) => continue,
        };
        checked += 1;
        for e in &edges {
            assert_ne!(e.from_gid, Some(gid), "gid {gid} 把自己成员算成了使用者: {:?}", e.from_path);
            assert!(!e.from_path.is_empty(), "gid {gid} 有一条没有来源名的使用者");
        }
        let member_hashes: Vec<String> = con
            .prepare("SELECT hash FROM amembers WHERE gid = ?1")
            .unwrap()
            .query_map([gid], |r| r.get(0))
            .unwrap()
            .filter_map(|x| x.ok())
            .collect();
        for e in &edges {
            let hex = format!("{:016x}", e.from_hash);
            assert!(!member_hashes.contains(&hex), "gid {gid} 的使用者其实是它自己的成员 {hex}");
        }
    }
    assert!(checked > 0, "external_users 一次都没跑成");
}
