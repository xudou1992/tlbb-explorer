//! 资产版本比较：真实库与外部快照文件上的规模验证。
//!
//! `versiondiff` is included by path rather than imported from `tlbb_core::catalog` so
//! this test compiles before the module is declared in `catalog/mod.rs`. Once that one
//! line lands, the two `mod` shims below can be dropped in favour of
//! `use tlbb_core::catalog::versiondiff`.

#![allow(dead_code)]

mod catalog {
    pub use tlbb_core::catalog::{labels, sqlite};
}

#[path = "../src/catalog/versiondiff.rs"]
mod versiondiff;

use std::path::Path;
use std::time::Instant;

use versiondiff::{diff, ChangeKind, Snapshot, BASIS_PAYLOAD, FORMAT};

const DB: &str = "D:/TLGL/.scratch/resources.db";
const SAMPLE: &str = "D:/TLGL/.scratch/versions/示例_下一版.json";
/// The snapshot `.scratch/makedemo.py` derived 示例_下一版.json from, so the expected
/// verdict counts below are known ground truth rather than a self-fulfilling assertion.
const PREVIOUS: &str = "D:/TLGL/.scratch/out/versionA.json";

/// The catalog is a shared, live file: another session may be rebuilding it while these
/// tests run, so a busy database skips rather than fails.
fn catalog() -> Option<tlbb_core::catalog::Catalog> {
    if !Path::new(DB).exists() {
        eprintln!("skip: {DB} absent");
        return None;
    }
    match tlbb_core::catalog::Catalog::open_ro(DB) {
        Ok(c) => Some(c),
        Err(e) => {
            eprintln!("skip: {DB} unreadable ({e:?})");
            None
        }
    }
}

fn snapshot(cat: &tlbb_core::catalog::Catalog) -> Option<Snapshot> {
    match Snapshot::from_db(cat) {
        Ok(s) => Some(s),
        Err(e) => {
            eprintln!("skip: catalog busy or incomplete ({e})");
            None
        }
    }
}

#[test]
fn the_real_library_snapshots_and_self_diffs_to_nothing() {
    let Some(cat) = catalog() else { return };
    let t = Instant::now();
    let Some(mut snap) = snapshot(&cat) else { return };
    let build = t.elapsed();
    assert!(snap.len() > 8_000, "{} groups is not the whole library", snap.len());
    let _ = snap.with_observed_fingerprints(&cat);

    let t = Instant::now();
    let d = diff(&snap, &snap);
    let compared = t.elapsed();
    eprintln!(
        "self-diff: {} groups / {} members / build {build:?} / diff {compared:?}",
        snap.len(),
        snap.total_members()
    );
    assert!(d.is_empty(), "{}", brief(&d));
    assert_eq!(d.summary.unchanged, snap.len());
    assert_eq!(d.summary.paired, snap.len());
    assert!(d.comparable);
    assert!(d.summary.added + d.summary.removed + d.summary.content == 0);

    // A snapshot has to survive being written down and read back, at full scale.
    let t = Instant::now();
    let text = snap.to_json();
    let wrote = t.elapsed();
    let t = Instant::now();
    let back = Snapshot::from_json(&text).expect("native snapshot parses");
    let read = t.elapsed();
    eprintln!(
        "round-trip: {:.1} MB / encode {wrote:?} / decode {read:?}",
        text.len() as f64 / 1e6
    );
    assert_eq!(back.len(), snap.len());
    assert_eq!(back.total_members(), snap.total_members());
    assert!(diff(&snap, &back).is_empty(), "{:?} changed rows after a round trip", back.len());
    assert_eq!(back.format, FORMAT);

    // Composition-only snapshots stay useful and still agree with themselves.
    let t = Instant::now();
    let light = Snapshot::from_db_composition_only(&cat).expect("light snapshot");
    eprintln!("composition-only build: {:?} over {} groups", t.elapsed(), light.len());
    assert!(!light.has_member_detail());
    assert!(diff(&light, &light).is_empty());
    // ... and that the two modes see the same library. Comparing across modes may not
    // judge content (one side has no member detail), and must not pretend to.
    assert_eq!(light.len(), snap.len());
    let cross = diff(&light, &snap);
    assert_eq!(cross.summary.added, 0);
    assert_eq!(cross.summary.removed, 0);
    assert_eq!(cross.summary.paired, snap.len());
    assert_eq!(cross.summary.content, 0, "{}", brief(&cross));
    assert!(cross.scope.contains("成员明细缺失"), "{}", cross.scope);
}

#[test]
fn a_real_catalog_repack_is_not_reported_as_content() {
    let Some(cat) = catalog() else { return };
    let Some(mut a) = snapshot(&cat) else { return };
    let _ = a.with_observed_fingerprints(&cat);
    // The library on disk is one snapshot; pretend the payloads were re-packed by moving
    // every location field, which is exactly the change that must not read as art.
    let mut b = a.clone();
    for asset in &mut b.assets {
        for m in &mut asset.members {
            m.loc = m.loc.replace('@', "+");
        }
        asset.refresh();
    }
    let d = diff(&a, &b);
    assert_eq!(d.summary.content, 0, "位置变化被当成了内容变化");
    assert_eq!(d.summary.composition, 0);
    assert_eq!(d.summary.repacked, a.len());
    assert_eq!(d.summary.unchanged, 0);
}

#[test]
fn the_shipped_sample_snapshot_reads_in() {
    if !Path::new(SAMPLE).exists() {
        eprintln!("skip: {SAMPLE} absent");
        return;
    }
    let t = Instant::now();
    let s = Snapshot::from_json_file(SAMPLE).expect("sample parses");
    let took = t.elapsed();
    eprintln!("示例_下一版.json: {} assets / {} members in {took:?}", s.len(), s.total_members());
    assert_eq!(s.basis, BASIS_PAYLOAD);
    assert!(s.len() > 8_000);
    assert!(s.has_member_detail());
    // Reading the same file twice must not invent a version difference.
    let again = Snapshot::from_json_file(SAMPLE).expect("sample parses again");
    assert!(diff(&s, &again).is_empty());
    // The foreign digests are kept for traceability, and only for traceability.
    let with_ids = s.assets.iter().filter(|a| !a.fp.foreign.is_empty()).count();
    assert!(with_ids > s.len() - 20, "{with_ids} of {} carry id_* digests", s.len());
}

#[test]
fn the_synthesised_next_version_lands_on_its_ground_truth() {
    if !Path::new(PREVIOUS).exists() || !Path::new(SAMPLE).exists() {
        eprintln!("skip: needs {PREVIOUS} and {SAMPLE}");
        return;
    }
    let a = Snapshot::from_json_file(PREVIOUS).expect("versionA parses");
    let b = Snapshot::from_json_file(SAMPLE).expect("sample parses");
    let t = Instant::now();
    let d = diff(&a, &b);
    eprintln!("versionA → 示例_下一版: {} change rows in {:?}", d.changes.len(), t.elapsed());
    let s = &d.summary;
    eprintln!(
        "汇总: 前 {} 后 {} 配对 {} 未变 {} 新增 {} 删除 {} 内容 {} 组成 {} 重新打包 {}",
        s.before_assets,
        s.after_assets,
        s.paired,
        s.unchanged,
        s.added,
        s.removed,
        s.content,
        s.composition,
        s.repacked
    );
    assert!(d.comparable, "both are 内容标识 snapshots");
    // `.scratch/makedemo.py` injects 8 arriving and 12 vanishing assets. Recounting the
    // two files pair-wise by `gid` puts 73 assets with a different member set (43 of them
    // also a different count) and 400 whose stored bytes alone moved; the bands below
    // allow for a handful of pairs the matcher can only resolve by overlap.
    assert_eq!(s.added, 8, "{:?}", head(&d, ChangeKind::Added));
    assert_eq!(s.removed, 12, "{:?}", head(&d, ChangeKind::Removed));
    assert!(s.content >= 65 && s.content <= 85, "content = {}", s.content);
    assert!(s.composition >= 38 && s.composition <= 50, "composition = {}", s.composition);
    assert!(s.repacked >= 385 && s.repacked <= 405, "repacked = {}", s.repacked);
    assert_eq!(s.texture_only, 0, "样例未改贴图");
    assert_eq!(s.names_only, 0, "样例未改名称采集");
    assert!(s.unchanged > 9_000, "unchanged = {}", s.unchanged);
    assert_eq!(s.before_assets, s.paired + s.removed);
    assert_eq!(s.after_assets, s.paired + s.added);
    let rows = d.changes.iter().filter(|c| !matches!(c.headline, ChangeKind::Added | ChangeKind::Removed)).count();
    assert_eq!(s.unchanged + rows, s.paired, "每一对要么未变要么出现在变化表里");
}

fn head(d: &versiondiff::Diff, k: ChangeKind) -> Vec<String> {
    d.changes
        .iter()
        .filter(|c| c.changes.contains(&k))
        .map(|c| c.name.clone())
        .take(12)
        .collect()
}

/// A failing assertion must not dump a 3,405-member asset: name and verdict only.
fn brief(d: &versiondiff::Diff) -> String {
    let mut out = format!("{} change rows, first: ", d.changes.len());
    for c in d.changes.iter().take(6) {
        out.push_str(&format!("{}{:?} ", c.name, c.changes));
    }
    out
}

// ========================================================================= in-memory
// 语义用例：全部在内存里构造快照，不读数据库也不读文件，所以它们在任何机器上都会跑。
// 这里守的是这个模块存在的理由 —— 真实内容变化与指纹/口径变化必须是两回事。

use versiondiff::{AssetChange, MatchBasis, Member, SnapAsset, BASIS_RESOURCE};

fn file(role: &str, ident: &str, name: &str) -> Member {
    Member {
        role: role.to_string(),
        ident: ident.to_string(),
        name: name.to_string(),
        crc: String::new(),
        loc: String::new(),
    }
}

/// One group, built the way `Snapshot::from_db` builds it: members in, digests derived.
fn group(gid: i64, stem: &str, dir: &str, members: Vec<Member>) -> SnapAsset {
    let mut a = SnapAsset {
        gid,
        stem: stem.to_string(),
        kind: "npc".to_string(),
        dir: dir.to_string(),
        hub: format!("{dir}/{stem}.mdl"),
        ..Default::default()
    };
    a.members = members;
    a.refresh();
    a
}

fn library(assets: Vec<SnapAsset>) -> Snapshot {
    Snapshot {
        format: FORMAT,
        source: "内存样例".to_string(),
        basis: BASIS_RESOURCE.to_string(),
        assets,
    }
}

#[track_caller]
fn row<'a>(d: &'a versiondiff::Diff, name: &str) -> &'a AssetChange {
    match d.changes.iter().find(|c| c.name == name) {
        Some(c) => c,
        None => panic!("'{name}' 未出现在 {}", brief(d)),
    }
}

fn flags(c: &AssetChange) -> Vec<String> {
    c.changes.iter().map(|k| format!("{k:?}")).collect()
}

#[test]
fn a_library_never_changed_reports_nothing() {
    let s = library(vec![
        group(1, "npc_a", "data/source/npc/one", vec![
            file("model", "m1", "a.mdl"),
            file("texture", "t1", "a.tga"),
        ]),
        group(2, "npc_b", "data/source/npc/two", vec![file("model", "m2", "b.mdl")]),
    ]);
    let d = diff(&s, &s);
    assert!(d.is_empty(), "自反比较不得有任何一行：{}", brief(&d));
    assert_eq!(d.summary.unchanged, 2);
    assert_eq!(d.summary.paired, 2);
    assert_eq!(d.summary.added + d.summary.removed + d.summary.content, 0);
    assert!(d.comparable);
    assert_contract(&d.contract_document());
}

#[test]
fn an_arrival_is_listed_as_an_arrival() {
    let a = library(vec![group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")])]);
    let b = library(vec![
        group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]),
        group(2, "npc_new", "data/source/npc/two", vec![file("model", "m9", "n.mdl")]),
    ]);
    let d = diff(&a, &b);
    assert_eq!(d.summary.added, 1, "{}", brief(&d));
    assert_eq!(d.summary.removed, 0);
    assert_eq!(d.summary.content, 0, "新增不得同时计为配对资产的内容变化");
    let c = row(&d, "npc_new");
    assert_eq!(c.headline, ChangeKind::Added, "{:?}", flags(c));
    assert_eq!(c.matched_by, Some(MatchBasis::Added));
    assert_eq!(c.after_members, 1);
    let doc = d.contract_document();
    assert_contract(&doc);
    assert_eq!(doc["变化计数"]["新增"], 1);
    assert_eq!(doc["统计"]["新资产出现"], 1);
    let item = &doc["明细"][0];
    assert_eq!(item["变更类型"], "新增");
    assert_eq!(item["判定"], "新资产出现");
    assert_eq!(item["匹配方式"], "新增");
    // 新资产是新的内容：内容轴与指纹轴同时为真。
    assert_eq!(item["内容变化"], true);
    assert_eq!(item["指纹变化"], true);
    assert_eq!(item["变化层"], serde_json::json!(["fp_asset"]), "新资产带来的是整体新增");
}

#[test]
fn a_departure_is_listed_as_a_departure() {
    let a = library(vec![
        group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]),
        group(2, "npc_gone", "data/source/npc/two", vec![file("model", "m2", "b.mdl")]),
    ]);
    let b = library(vec![group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")])]);
    let d = diff(&a, &b);
    assert_eq!(d.summary.removed, 1, "{}", brief(&d));
    assert_eq!(d.summary.added, 0);
    let c = row(&d, "npc_gone");
    assert_eq!(c.headline, ChangeKind::Removed, "{:?}", flags(c));
    assert_eq!(c.matched_by, None, "消失的资产没有对侧可配");
    assert_eq!(c.after_members, 0);
    let doc = d.contract_document();
    assert_contract(&doc);
    assert_eq!(doc["统计"]["资产消失"], 1);
    assert_eq!(doc["明细"][0]["变更类型"], "删除");
    assert_eq!(doc["明细"][0]["判定"], "资产消失");
    assert_eq!(
        doc["明细"][0].get("匹配方式"),
        None,
        "契约的 匹配方式 值域里没有删除这一项，缺对侧时应当不写这个键"
    );
    assert_eq!(doc["明细"][0]["内容变化"], false, "消失不是内容变化，是资产消失");
}

#[test]
fn only_the_referenced_names_moving_is_a_vocabulary_change() {
    let mut x = group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]);
    let mut y = group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]);
    x.names = vec!["旧名字.tga".to_string()];
    y.names = vec!["新名字.tga".to_string()];
    x.refresh();
    y.refresh();
    let d = diff(&library(vec![x]), &library(vec![y]));
    let c = row(&d, "npc_a");
    assert!(c.changes.contains(&ChangeKind::NamesOnly), "{:?}", flags(c));
    assert!(!c.changes.contains(&ChangeKind::Content), "名称口径变化不得报成美术改了");
    assert!(c.notes.iter().any(|n| n.contains("采集口径")), "{:?}", c.notes);
    let doc = d.contract_document();
    assert_contract(&doc);
    let item = &doc["明细"][0];
    assert_eq!(item["变更类型"], "仅名称变化");
    assert_eq!(item["内容变化"], false);
    assert_eq!(item["指纹变化"], true, "名称层确实动了，只是那不是内容");
    assert_eq!(item["变化层"], serde_json::json!(["fp_names"]));
    assert_eq!(item["仅名称变化"], true);
}

#[test]
fn only_the_texture_moving_is_presentation_not_restructure() {
    let x = group(1, "npc_a", "data/source/npc/one", vec![
        file("model", "m1", "a.mdl"),
        file("material", "s1", "a.mtl"),
        file("texture", "t1", "a.tga"),
    ]);
    let y = group(1, "npc_a", "data/source/npc/one", vec![
        file("model", "m1", "a.mdl"),
        file("material", "s1", "a.mtl"),
        file("texture", "t2", "a.tga"),
    ]);
    let d = diff(&library(vec![x]), &library(vec![y]));
    let c = row(&d, "npc_a");
    assert_eq!(c.headline, ChangeKind::TextureOnly, "{:?}", flags(c));
    assert!(!c.changes.contains(&ChangeKind::Content), "贴图变化不得重复计为内容变化");
    assert_eq!(c.replaced_members.len(), 1);
    assert!(c.fingerprint_moves.iter().all(|(r, _, _)| r == "texture"), "{:?}", c.fingerprint_moves);
    let doc = d.contract_document();
    assert_contract(&doc);
    let item = &doc["明细"][0];
    // 贴图字节就是内容，所以内容轴为真；但结构没动，判定是微调而不是结构变化。
    assert_eq!(item["变更类型"], "变更");
    assert_eq!(item["判定"], "内容微调");
    assert_eq!(item["内容变化"], true);
    assert_eq!(item["变化层"], serde_json::json!(["fp_asset", "fp_texture"]));
    assert!(item["说明"].as_str().unwrap().contains("贴图"), "{:?}", item["说明"]);
}

#[test]
fn a_membership_move_without_a_content_move_is_attribution() {
    // 组成员清单变了，但没有任何内容标识变动：那个新成员根本没解出载荷。
    let x = group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]);
    let y = group(1, "npc_a", "data/source/npc/one", vec![
        file("model", "m1", "a.mdl"),
        file("mesh", "", "orphan.gmx"),
    ]);
    let d = diff(&library(vec![x]), &library(vec![y]));
    let c = row(&d, "npc_a");
    assert!(!c.changes.contains(&ChangeKind::Content), "无内容标识的成员进出不得报成内容变化：{:?}", flags(c));
    assert!(c.changes.contains(&ChangeKind::FingerprintOnly), "{:?}", flags(c));
    assert!(c.changes.contains(&ChangeKind::Composition), "组成数量确实变了，那要如实说：{:?}", flags(c));
    let doc = d.contract_document();
    assert_contract(&doc);
    let item = &doc["明细"][0];
    assert_eq!(item["内容变化"], false, "成员进出而无内容标识，不是内容变化");
    assert_eq!(item["指纹变化"], true, "归属/口径确实动了，那一条轴要为真");
    assert_eq!(item["变更类型"], "变更");
    assert!(
        matches!(item["判定"].as_str(), Some("身份证不同") | Some("结构变化")),
        "组成数量也变了，所以两词都算说清楚：{:?}",
        item["判定"]
    );
    assert!(item["说明"].as_str().unwrap().contains("不作内容变化"), "{:?}", item["说明"]);

    // 同一文件换了名字：内容标识一字未动。
    let p = group(1, "npc_b", "data/source/npc/one", vec![file("model", "m1", "old.mdl")]);
    let q = group(2, "npc_b", "data/source/npc/one", vec![file("model", "m1", "new.mdl")]);
    let d2 = diff(&library(vec![p]), &library(vec![q]));
    let c2 = row(&d2, "npc_b");
    assert!(!c2.changes.contains(&ChangeKind::Content), "{:?}", flags(c2));
    assert_eq!(d2.summary.content, 0, "重命名不得计入内容变化");
}

#[test]
fn a_relocated_asset_is_one_row_and_not_two_events() {
    let x = group(1, "npc_a", "data/source/npc/old_place", vec![file("model", "m1", "a.mdl")]);
    let y = group(9, "npc_a", "data/source/npc/new_place", vec![file("model", "m1", "a.mdl")]);
    let d = diff(&library(vec![x]), &library(vec![y]));
    assert_eq!(d.summary.added, 0, "搬了位置的资产不得算新增");
    assert_eq!(d.summary.removed, 0, "搬了位置的资产不得算删除");
    assert_eq!(d.changes.len(), 1, "{}", brief(&d));
    let c = row(&d, "npc_a");
    assert!(
        matches!(c.matched_by, Some(MatchBasis::Fingerprint) | Some(MatchBasis::MemberOverlap)),
        "搬家资产必须靠内容/成员配上，而不是靠路径或新增：{:?}",
        flags(c)
    );
    assert!(c.changes.contains(&ChangeKind::Renamed), "{:?}", flags(c));
    let doc = d.contract_document();
    assert_contract(&doc);
    let item = &doc["明细"][0];
    assert_eq!(item["变更类型"], "未变");
    assert_eq!(item["内容变化"], false);
    assert_eq!(item["变化层"].as_array().map(|v| v.len()), Some(0), "未变不得列出任何内容层");
    assert!(
        matches!(item["匹配方式"].as_str(), Some("身份证") | Some("成员重叠")),
        "{:?}",
        item["匹配方式"]
    );

    // 搬家且换了内容：仍然是一行，而且内容轴必须为真。
    let p = group(1, "npc_b", "data/source/npc/old_place", vec![
        file("model", "m1", "b.mdl"),
        file("texture", "t1", "b.tga"),
    ]);
    let q = group(8, "npc_b", "data/source/npc/new_place", vec![
        file("model", "m1", "b.mdl"),
        file("texture", "t2", "b.tga"),
    ]);
    let d2 = diff(&library(vec![p]), &library(vec![q]));
    assert_eq!(d2.summary.added + d2.summary.removed, 0, "{}", brief(&d2));
    assert_eq!(d2.changes.len(), 1);
    let item2 = &d2.contract_document()["明细"][0];
    assert_eq!(item2["变更类型"], "变更");
    assert_eq!(item2["内容变化"], true);
    assert_eq!(item2["匹配方式"], "成员重叠");
    assert_eq!(item2["变化层"], serde_json::json!(["fp_asset", "fp_texture"]));
}

#[test]
fn a_repack_stays_on_the_fingerprint_axis() {
    let mut x = group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]);
    let mut y = group(1, "npc_a", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]);
    for m in &mut x.members {
        m.crc = "aaaa1111".to_string();
        m.loc = "a.pak@100/3".to_string();
    }
    for m in &mut y.members {
        m.crc = "bbbb2222".to_string();
        m.loc = "a.pak@9000/3".to_string();
    }
    x.refresh();
    y.refresh();
    let d = diff(&library(vec![x]), &library(vec![y]));
    let c = row(&d, "npc_a");
    assert_eq!(c.headline, ChangeKind::Repacked, "{:?}", flags(c));
    let doc = d.contract_document();
    assert_contract(&doc);
    let item = &doc["明细"][0];
    assert_eq!(item["变更类型"], "未变");
    assert_eq!(item["判定"], "仅重新打包");
    assert_eq!(item["仅重新打包"], true);
    assert_eq!(item["内容变化"], false);
    assert_eq!(item["指纹变化"], true, "内容/指纹两轴正交，这里正是重打包那一格");
    assert_eq!(item["变化层"].as_array().map(|v| v.len()), Some(0));
}

#[test]
fn the_projection_counts_reconcile_with_the_summary() {
    let x1 = group(1, "keep", "data/source/npc/one", vec![file("model", "m1", "a.mdl")]);
    let x2 = group(2, "gone", "data/source/npc/two", vec![file("model", "m2", "b.mdl")]);
    let x3 = group(3, "edit", "data/source/npc/three", vec![
        file("model", "m3", "c.mdl"),
        file("animation", "k1", "c_idle.ani"),
    ]);
    let x4 = group(4, "names", "data/source/npc/four", vec![file("model", "m4", "d.mdl")]);
    let mut a = library(vec![x1, x2, x3, x4.clone()]);
    let y3 = group(3, "edit", "data/source/npc/three", vec![file("model", "m3", "c.mdl")]);
    let mut y4 = x4.clone();
    y4.names = vec!["d_hi.tga".to_string()];
    y4.refresh();
    let mut b = library(vec![
        a.assets[0].clone(),
        y3,
        y4,
        group(7, "fresh", "data/source/npc/five", vec![file("model", "m7", "e.mdl")]),
    ]);
    b.source = "内存样例乙".to_string();
    a.source = "内存样例甲".to_string();
    let d = diff(&a, &b);
    let doc = d.contract_document();
    assert_contract(&doc);
    let sum: usize = doc["统计"].as_object().unwrap().values().map(|v| v.as_u64().unwrap() as usize).sum();
    let buckets: usize =
        doc["变化计数"].as_object().unwrap().values().map(|v| v.as_u64().unwrap() as usize).sum();
    // 每个基线资产贡献一行（配对或未配对），每个新增资产再贡献一行。
    assert_eq!(sum, a.len() + d.summary.added, "统计与快照规模对不上");
    assert_eq!(buckets, sum, "两个计数表必须数同一批资产");
    assert_eq!(d.changes.len() + d.summary.unchanged, a.len() + d.summary.added);
    assert_eq!(doc["基线"], format!("内存样例甲〔{BASIS_RESOURCE}〕"));
    assert_eq!(doc["目标"], format!("内存样例乙〔{BASIS_RESOURCE}〕"));
    assert_eq!(doc["版本"], versiondiff::Diff::CONTRACT_VERSION);
}

#[test]
fn mismatched_bases_never_claim_content() {
    // 同一份组成、只有成员标识换了口径：内容不作判定，也不得凭空生出"美术改了"。
    let x = library(vec![group(1, "npc_a", "data/source/npc/one", vec![
        file("model", "m1", "a.mdl"),
        file("texture", "t1", "a.tga"),
    ])]);
    let mut y = library(vec![group(1, "npc_a", "data/source/npc/one", vec![
        file("model", "zzz", "a.mdl"),
        file("texture", "yyy", "a.tga"),
    ])]);
    y.basis = versiondiff::BASIS_PAYLOAD.to_string();
    let d = diff(&x, &y);
    assert!(!d.comparable);
    assert_eq!(d.summary.content, 0, "口径不可比时不得判定内容");
    assert_eq!(d.summary.added + d.summary.removed, 0, "同一份资产不能被拆成一删一增");
    let doc = d.contract_document();
    assert_contract(&doc);
    // 契约没有装"不可比"这句话的地方，所以它必须出现在两个合法位置之一。
    assert!(doc["基线"].as_str().unwrap().contains("口径不可比"), "{:?}", doc["基线"]);
    assert!(doc["目标"].as_str().unwrap().contains("口径不可比"), "{:?}", doc["目标"]);
    assert!(d.scope.contains("内容不作判定"), "{}", d.scope);

    // 组成能比：那一行必须存在，并且仍然不得报成内容变化。
    let mut z = library(vec![group(1, "npc_a", "data/source/npc/one", vec![
        file("model", "zzz", "a.mdl"),
    ])]);
    z.basis = versiondiff::BASIS_PAYLOAD.to_string();
    let d2 = diff(&x, &z);
    assert_eq!(d2.summary.content, 0);
    assert_eq!(d2.summary.composition, 1, "成员计数是口径无关的事实");
    let doc2 = d2.contract_document();
    assert_contract(&doc2);
    assert_eq!(doc2["明细"][0]["内容变化"], false);
    assert!(doc2["明细"][0]["说明"].as_str().unwrap().contains("判定范围"), "{:?}", doc2["明细"][0]["说明"]);
}

// =========================================================================== contract
//
// `contracts/VersionDiff.schema.json` 的关键约束手抄一遍（那个校验器不接外部输入）：
// 契约文档必须同时过这里的断言和 `node contracts/crosscheck.js`。

const LAYERS: [&str; 8] = [
    "fp_asset",
    "fp_model",
    "fp_skeleton",
    "fp_mesh",
    "fp_material",
    "fp_animation",
    "fp_texture",
    "fp_names",
];
const BUCKETS: [&str; 5] = ["新增", "删除", "变更", "仅名称变化", "未变"];
const VERDICTS: [&str; 7] =
    ["相同", "仅重新打包", "结构变化", "内容微调", "身份证不同", "资产消失", "新资产出现"];
const KIND_TOKENS: [&str; 7] =
    ["npc", "player", "map-prop", "effect", "ui", "shared-material", "other"];
const MATCH_WAYS: [&str; 4] = ["路径", "身份证", "成员重叠", "新增"];
const ITEM_KEYS: [&str; 13] = [
    "变更类型",
    "判定",
    "名称",
    "种类",
    "匹配方式",
    "内容变化",
    "指纹变化",
    "仅重新打包",
    "仅名称变化",
    "变化层",
    "基线指纹",
    "目标指纹",
    "说明",
];
const DOC_KEYS: [&str; 7] = ["版本", "基线", "目标", "生成时间", "统计", "变化计数", "明细"];

fn one_of(v: &serde_json::Value, set: &[&str], where_: &str) -> String {
    let s = v.as_str().unwrap_or_else(|| panic!("{where_} 必须是字符串：{v}"));
    assert!(set.contains(&s), "{where_} 越界：{s}");
    s.to_string()
}

/// Walk a contract document and assert every constraint the schema states.
#[track_caller]
fn assert_contract(doc: &serde_json::Value) {
    let obj = doc.as_object().expect("差异文档是对象");
    for k in obj.keys() {
        assert!(DOC_KEYS.contains(&k.as_str()), "多余键 {k}（additionalProperties:false）");
    }
    for k in ["版本", "基线", "目标", "统计", "变化计数", "明细"] {
        assert!(obj.contains_key(k), "缺必填 {k}");
    }
    assert!(doc["版本"].as_u64().unwrap() >= 1);
    assert!(doc["基线"].is_string() && doc["目标"].is_string());
    for (table, set) in [("统计", &VERDICTS as &[&str]), ("变化计数", &BUCKETS)] {
        for (k, v) in doc[table].as_object().unwrap() {
            assert!(set.contains(&k.as_str()), "{table} 键 {k} 越界");
            assert!(v.as_u64().is_some(), "{table}.{k} 必须是整数：{v}");
        }
    }
    let items = doc["明细"].as_array().expect("明细是数组");
    for (n, item) in items.iter().enumerate() {
        let at = format!("明细[{n}]");
        let io = item.as_object().expect("明细项是对象");
        for k in io.keys() {
            assert!(ITEM_KEYS.contains(&k.as_str()), "{at} 多余键 {k}");
        }
        for k in ["变更类型", "判定", "名称", "种类", "内容变化", "指纹变化", "变化层"] {
            assert!(io.contains_key(k), "{at} 缺必填 {k}");
        }
        let bucket = one_of(&item["变更类型"], &BUCKETS, &at);
        let verdict = one_of(&item["判定"], &VERDICTS, &at);
        one_of(&item["种类"], &KIND_TOKENS, &at);
        if let Some(m) = item.get("匹配方式") {
            one_of(m, &MATCH_WAYS, &at);
        }
        assert!(item["名称"].is_string(), "{at} 名称");
        for k in ["内容变化", "指纹变化"] {
            assert!(item[k].is_boolean(), "{at} {k} 必须是布尔");
        }
        let layers = item["变化层"].as_array().expect("变化层是数组");
        let mut seen: Vec<String> = Vec::new();
        for l in layers {
            let s = one_of(l, &LAYERS, &at);
            assert!(!seen.contains(&s), "{at} 变化层重复 {s}（uniqueItems）");
            seen.push(s);
        }
        let content = item["内容变化"].as_bool().unwrap();
        // allOf #1：内容变化=true 只可能是 变更 或 新增。
        assert!(!content || matches!(bucket.as_str(), "变更" | "新增"), "{at} 内容变化=true 却报成 {bucket}");
        // allOf #2：未变 不得有任何内容层。
        if bucket == "未变" {
            assert!(layers.is_empty(), "{at} 未变 却列出变化层 {layers:?}");
        }
        // allOf #3：仅名称变化 必须恰好是 fp_names。
        if bucket == "仅名称变化" {
            assert_eq!(layers.as_slice(), [serde_json::json!("fp_names")].as_slice(), "{at} {layers:?}");
            assert!(!content, "{at} 仅名称变化 不得谎称内容变化");
        }
        // allOf #4：判定=仅重新打包 必须内容未变并且带上那个布尔。
        if verdict == "仅重新打包" {
            assert!(!content, "{at} 仅重新打包 却报内容变化");
            assert_eq!(item["仅重新打包"], true, "{at} 缺 仅重新打包=true");
        }
        if item.get("仅名称变化").is_some() {
            assert_eq!(bucket, "仅名称变化", "{at} 仅名称变化 标记与桶不一致");
        }
    }
}

/// Where the contract document lands for `node contracts/crosscheck.js` to read.
fn contract_dump_path() -> std::path::PathBuf {
    std::env::temp_dir().join("tlbb_versiondiff_contract.json")
}

// ================================================================== real catalog scale

#[test]
fn the_real_library_self_diff_is_empty_stable_and_fast() {
    let Some(cat) = catalog() else { return };
    let Some(snap) = snapshot(&cat) else { return };
    if snap.len() < 100 {
        eprintln!("skip: catalog holds only {} groups", snap.len());
        return;
    }
    let t = Instant::now();
    let d = diff(&snap, &snap);
    let took = t.elapsed();
    let json = d.contract_json();
    eprintln!(
        "self-diff {} 资产 / {} 成员：{} 行，用时 {took:?}，契约文档 {} 字节",
        snap.len(),
        snap.total_members(),
        d.changes.len(),
        json.len()
    );
    assert!(d.is_empty(), "同一个库跟自己比不可能有变化：{}", brief(&d));
    assert_eq!(d.summary.unchanged, snap.len());
    assert!(took < std::time::Duration::from_secs(120), "自反比较用了 {took:?}");

    // 稳定性：同一对快照比两次，连投影出来的契约文档都要逐字相同。HashMap 顺序漏进输出
    // 就是这里会挂 —— 报告要能反复生成、反复对账。
    for _ in 0..3 {
        let again = diff(&snap, &snap);
        assert_eq!(again.contract_json(), json, "两次同样的比较给出了不同输出");
    }
    // A snapshot that survives being written down must still equal itself.
    let back = Snapshot::from_json(&snap.to_json()).expect("round trip parses");
    let d2 = diff(&snap, &back);
    assert!(d2.is_empty(), "写一遍再读回来就变了：{}", brief(&d2));

    // The empty document is a valid contract document.
    let doc = d2.contract_document();
    assert_contract(&doc);
    assert_eq!(doc["明细"].as_array().map(|v| v.len()), Some(0));
    assert_eq!(doc["变化计数"]["未变"], snap.len());
}

#[test]
fn the_real_pair_projects_a_valid_contract_document() {
    if !Path::new(PREVIOUS).exists() || !Path::new(SAMPLE).exists() {
        eprintln!("skip: needs {PREVIOUS} and {SAMPLE}");
        return;
    }
    let a = Snapshot::from_json_file(PREVIOUS).expect("versionA parses");
    let b = Snapshot::from_json_file(SAMPLE).expect("sample parses");
    let t = Instant::now();
    let d = diff(&a, &b);
    let doc = d.contract_document();
    let took = t.elapsed();
    assert_contract(&doc);
    let path = contract_dump_path();
    std::fs::write(&path, d.contract_json()).expect("契约文档写得出去");
    eprintln!(
        "versionA → 示例_下一版：{} 明细 / {} 未变 / 用时 {took:?} / 契约文档 {}",
        doc["明细"].as_array().map(|v| v.len()).unwrap(),
        doc["变化计数"]["未变"],
        path.display()
    );
    let bad: Vec<&serde_json::Value> = doc["明细"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|i| i["判定"] == "仅重新打包" && i["内容变化"] == true)
        .collect();
    assert!(bad.is_empty(), "{}/{} 行被判为重打包却报了内容变化", bad.len(), doc["明细"].as_array().unwrap().len());
    // 与 crosscheck.js 的参考口径同类：绝大多数资产未变，新增与删除都是小数目。
    assert!(d.summary.added > 0 && d.summary.added < 40, "added = {}", d.summary.added);
    assert!(d.summary.removed > 0 && d.summary.removed < 40, "removed = {}", d.summary.removed);
    assert!(d.summary.content > 0, "样例注入过内容变化，一个都没抓到就是没接通");
    assert!(d.summary.repacked > 300, "样例重打包了 400 个资产，抓到 {}", d.summary.repacked);
    let sum: usize = doc["统计"].as_object().unwrap().values().map(|v| v.as_u64().unwrap() as usize).sum();
    assert_eq!(sum, a.len() + d.summary.added);
}

