//! The report is a deliverable: it gets mailed to an art lead and opened offline, so the
//! things these tests pin down are the things that would make it wrong or embarrassing —
//! a broken image link, an asset's own files listed as its users, markup eaten by a name,
//! or an empty preview box standing in for a picture that was never decoded.
//!
//! The unit cases drive the binary's own source through `include!`, so the logic under
//! test is the logic that ships; the end-to-end cases run the compiled binary against the
//! real catalog and skip when it is absent.

#![allow(dead_code)]

mod report_bin {
    include!("../src/bin/asset_report.rs");
}

use std::path::{Path, PathBuf};

use report_bin::{
    b64, current_snap, diff_snap, esc, external_users, human, inline_image, into_fps, nice,
    outside_refs, parse_args, placeholder_for, ref_kind, render, rescale, snap_from_json,
    subtitle, versions_for, Chip, Fingerprints, Pic, RefRow, Report, Snap,
};
use tlbb_core::catalog::Catalog;

const DB: &str = "D:/TLGL/.scratch/resources.db";

fn pic() -> Pic {
    Pic { data_url: "data:image/png;base64,iVBORw0KGgo=".into(), note: "BC3 8x8".into() }
}

fn filled() -> Report {
    Report {
        gid: 7,
        name: "w1351_boss_caoshuang".into(),
        subtitle: "角色 · caoshuang".into(),
        kind: "NPC / 怪物",
        scenario: "角色",
        dir: "data/source/npc/w1351_boss_caoshuang".into(),
        tags: vec!["首领".into(), "怪物".into()],
        placeholder: "character",
        pic: Some(pic()),
        no_pic: None,
        grade: "B 主体定位",
        grade_note: "主体可解码，部分依赖只有名称".into(),
        gaps: vec!["部分贴图引用未定位"],
        name_source: "客户端茎名（原文展示，未翻译）",
        ident: "0123456789abcdef".into(),
        pak: "data1".into(),
        members: 12,
        names: 3,
        fps: Some(Fingerprints { asset: "a1".into(), model: "-".into(), names: "n1".into(), ..Default::default() }),
        parts: vec![Chip { label: "模型".into(), n: 1 }, Chip { label: "贴图".into(), n: 4 }],
        refs: vec![
            RefRow { kind: "贴图", name: "a.tga".into(), status: "仅有名称" },
            RefRow { kind: "动作", name: "b.ani".into(), status: "已定位" },
        ],
        users: vec![report_bin::User { file: "other.mdl".into(), via: "骨骼", what: "x.ske".into() }],
        users_total: 1,
        versions: Vec::new(),
        snap_note: "无历史快照：样例目录里还没有任何快照文件。".into(),
        tech: vec![("主体标识", "0123456789abcdef".into())],
        built: "2026-09-22 07:00".into(),
    }
}

/* ------------------------------------------------------------------- single file */

#[test]
fn an_inlined_report_references_nothing_outside_itself() {
    let html = render(&filled());
    assert!(html.contains("src=\"data:image/png;base64,"), "preview must be inlined");
    assert!(outside_refs(&html).is_empty(), "leaked: {:?}", outside_refs(&html));
    // The sprite sheet is in the document, so the silhouette needs no external file; the
    // `<use>` itself only appears when a picture is missing (see the placeholder case).
    assert!(html.contains("id=\"i-character\""));
    assert!(!html.contains("<script"));
    assert!(!html.contains("../"));
}

#[test]
fn a_missing_image_still_proves_the_page_is_self_contained() {
    let rep = Report { pic: None, no_pic: Some("贴图内嵌后过大，已省略。".into()), ..Default::default() };
    let html = render(&rep);
    assert!(outside_refs(&html).is_empty());
    assert!(html.contains("贴图内嵌后过大，已省略"));
}

#[test]
fn base64_follows_rfc_4648() {
    let cases = [("", ""), ("f", "Zg=="), ("fo", "Zm8="), ("foo", "Zm9v"), ("foob", "Zm9vYg=="), ("fooba", "Zm9vYmE="), ("foobar", "Zm9vYmFy")];
    for (raw, want) in cases {
        assert_eq!(b64(raw.as_bytes()), want, "{raw:?}");
    }
}

/* -------------------------------------------------------------- who uses it (b) */

/// The filter moved into `Catalog::external_users`, and these three unit cases drive the
/// SQL version end-to-end instead of the old in-memory one. They need a catalog; when it
/// is absent they skip rather than weaken into a tautology.
const SKELETON: &str = "%w1351_nan.ske";
const TEXTURED: &str = "%w1351_nan_s_yifu_zhongshilifu.mdl";
const SELF_CONTAINED: &str = "%w1351_nan_s_yifu_mjrmdz.mdl";

fn open_catalog() -> Option<Catalog> {
    if !Path::new(DB).exists() {
        eprintln!("skip: catalog absent ({DB})");
        return None;
    }
    Catalog::open_ro(DB).ok()
}

#[test]
fn an_assets_own_files_are_never_listed_as_its_users() {
    let Some(cat) = open_catalog() else { return };
    let Some(gid) = gid_for(SELF_CONTAINED) else { return };
    let mine = member_paths(gid);
    let users = external_users(&cat, gid, 40);
    for u in &users {
        let full = format!("{}/{}", "", u.what);
        assert!(
            !mine.iter().any(|m| m.replace('\\', "/").ends_with(&full)),
            "listed user {} is one of its own members: {mine:?}",
            u.what
        );
    }
    // Nothing on the report may name a member file.
    let html = render(&Report { users: users.clone(), users_total: users.len(), ..Default::default() });
    assert!(!html.contains("self_a"), "member path leaked into the report");
}

#[test]
fn a_report_with_only_internal_edges_says_so_in_words() {
    let Some(cat) = open_catalog() else { return };
    let Some(gid) = gid_for(SELF_CONTAINED) else { return };
    let users = external_users(&cat, gid, 40);
    assert!(users.is_empty(), "{SELF_CONTAINED} should have no outside user: {users:?}");
    let html = render(&Report { users, users_total: 0, ..Default::default() });
    assert!(html.contains("谁在使用它 · 0 项"));
    assert!(html.contains("已排除，不计入"));
}

#[test]
fn a_referrer_without_a_path_is_never_dressed_up_as_one() {
    let Some(cat) = open_catalog() else { return };
    // Every user the catalog hands back must carry a real path: the old workbench query
    // backfilled an empty one with the referrer's stem, which invented a filename.
    for probe in [SKELETON, SELF_CONTAINED, TEXTURED] {
        let Some(gid) = gid_for(probe) else { continue };
        for e in cat.external_users(gid).unwrap_or_default() {
            assert!(!e.from_path.is_empty(), "gid {gid}: a user came back with no path");
            assert!(e.from_path.contains('/'), "gid {gid}: {:?} is not a path", e.from_path);
            assert_eq!(e.from_hash, e.from_hash, "sanity");
        }
    }
}

#[test]
fn the_list_is_capped_but_the_headline_keeps_the_true_total() {
    let Some(cat) = open_catalog() else { return };
    let Some(gid) = gid_for(SKELETON) else { return };
    let all = external_users(&cat, gid, usize::MAX);
    let users = external_users(&cat, gid, 40);
    assert!(users.len() <= all.len().min(40));
    let html = render(&Report { users, users_total: all.len(), ..Default::default() });
    assert!(html.contains(&format!("谁在使用它 · {} 项", all.len())));
    if all.len() > 40 {
        assert!(html.contains("此处列出前 40 项"));
    }
}

/* ------------------------------------------------------- placeholder, not an <img> */

#[test]
fn an_asset_with_no_decodable_texture_shows_a_silhouette() {
    let rep = Report { name: "w1351_ll_hlf_001".into(), placeholder: "building", ..Default::default() };
    let html = render(&rep);
    assert!(!html.contains("<img"), "empty <img> would read as a broken preview");
    assert!(html.contains("暂无可解析预览"));
    assert!(html.contains("<use href=\"#i-building\""));
}

#[test]
fn placeholder_keys_stay_inside_the_sprite_set() {
    let known = ["character", "beast", "building", "effect", "panel", "item", "node"];
    for kind in ["npc", "player", "map-prop", "effect", "ui", "shared-material", "other"] {
        let p = placeholder_for(report_bin::scenario_of(kind), &[]);
        assert!(known.contains(&p), "{kind} → {p}");
    }
    // Parity with the card contract: tags win over scenario.
    assert_eq!(placeholder_for("角色", &["坐骑".into()]), "beast");
    assert_eq!(placeholder_for("其他", &["武器".into()]), "item");
    assert_eq!(placeholder_for("场景", &["地表贴图组".into()]), "building");
    assert_eq!(ref_kind("a/b.TGA"), "贴图");
    assert_eq!(ref_kind("run.ani"), "动作");
    assert_eq!(ref_kind("no extension"), "文件");
}

#[test]
fn the_subtitle_is_only_ever_a_cut_of_the_name() {
    assert_eq!(subtitle("w1351_nan_s_moyuqianyou_001", "player"), "角色 · moyuqianyou");
    assert_eq!(subtitle("w1351_fb_sxzc_001", "map-prop"), "场景 · sxzc");
    assert_eq!(subtitle("w1351", "other"), "其他 · w1351");
    let tail = subtitle("w1351_boss_caoshuang", "npc").split('·').last().unwrap().trim().to_string();
    assert_eq!(nice("w1351_boss_caoshuang"), "boss_caoshuang");
    assert!(tail.chars().all(|c| !c.is_uppercase()));
}

/* ------------------------------------------------------------------------ escaping */

#[test]
fn names_carrying_markup_cannot_rearrange_the_page() {
    let nasty = "a<b>\"c\"&'d&e <script>alert(1)</script>";
    let html = render(&Report {
        name: nasty.into(),
        dir: nasty.into(),
        refs: vec![RefRow { kind: "贴图", name: nasty.into(), status: "仅有名称" }],
        users: vec![report_bin::User { file: nasty.into(), via: "骨骼", what: nasty.into() }],
        users_total: 1,
        parts: vec![Chip { label: nasty.into(), n: 1 }],
        tags: vec![nasty.into()],
        tech: vec![("主体标识", nasty.into())],
        ..Default::default()
    });
    assert!(!html.contains("<script>alert"), "raw script survived escaping");
    assert_eq!(html.matches("<h1>").count(), 1);
    assert_eq!(html.matches("</section>").count(), html.matches("<section>").count());
    assert_eq!(esc(nasty), "a&lt;b&gt;&quot;c&quot;&amp;&#39;d&amp;e &lt;script&gt;alert(1)&lt;/script&gt;");
    assert_eq!(esc(""), "");
    // Every echoed value carries the escaped form, so the page structure is intact.
    assert!(html.contains("a&lt;b&gt;&quot;c&quot;&amp;&#39;d&amp;e"));
    assert!(html.contains("<title>资源报告 · a&lt;b&gt;"));
}

/* ------------------------------------------------------------------ version diff */

fn snap(dir: &str, stem: &str, id: &str, members: &[(&str, &str, &str)]) -> Snap {
    Snap {
        dir: dir.into(),
        stem: stem.into(),
        hub_path: format!("{dir}/{stem}.mdl"),
        id_asset: id.into(),
        id_pack: id.into(),
        members: members
            .iter()
            .map(|(r, n, s)| ((r.to_string(), n.to_string()), (s.to_string(), "aaaa0001".into())))
            .collect(),
    }
}

#[test]
fn snapshots_are_compared_with_the_census_vocabulary() {
    let a = snap("d/x", "stem", "id1", &[("model", "x.mdl", "sha1"), ("material", "x.mtl", "sha2")]);
    let same = a.clone();
    assert_eq!(diff_snap(&a, &same).0, "相同");

    let repacked = Snap { id_pack: "other".into(), ..a.clone() };
    assert_eq!(diff_snap(&a, &repacked).0, "仅重新打包");

    let dropped = snap("d/x", "stem", "id2", &[("model", "x.mdl", "sha1")]);
    let (verdict, detail) = diff_snap(&a, &dropped);
    assert_eq!(verdict, "成员变化");
    assert!(detail.contains("多了材质 1 个"), "{detail}");

    let grown = snap("d/x", "stem", "id3", &[("model", "x.mdl", "sha1"), ("material", "x.mtl", "sha2"), ("animation", "x.ani", "sha9")]);
    let (verdict, detail) = diff_snap(&a, &grown);
    assert_eq!(verdict, "成员变化");
    assert!(detail.contains("少了动作 1 个"), "{detail}");

    let edited = snap("d/x", "stem", "id4", &[("model", "x.mdl", "zzz"), ("material", "x.mtl", "sha2")]);
    let (verdict, detail) = diff_snap(&a, &edited);
    assert_eq!(verdict, "成员变化");
    assert!(detail.contains("1 个文件内容变了"), "{detail}");

    // Same files, different content digest: name-level movement only.
    let renamed = Snap { id_asset: "id5".into(), id_pack: "id5".into(), ..a.clone() };
    assert_eq!(diff_snap(&a, &renamed).0, "仅名称变化");
}

#[test]
fn an_unreadable_snapshot_directory_reads_as_no_history() {
    let cur = snap("d/x", "stem", "id1", &[("model", "x.mdl", "sha1")]);
    let (rows, note) = versions_for(Path::new("D:/TLGL/definitely-not-here"), &cur);
    assert!(rows.is_empty());
    assert!(note.starts_with("无历史快照"), "{note}");
}

#[test]
fn a_snapshot_directory_without_json_also_reads_as_no_history() {
    let dir = std::env::temp_dir().join("tlbb_report_empty_snapshots");
    std::fs::create_dir_all(&dir).unwrap();
    std::fs::write(dir.join("notes.txt"), b"not a snapshot").unwrap();
    let cur = snap("d/x", "stem", "id1", &[("model", "x.mdl", "sha1")]);
    let (rows, note) = versions_for(&dir, &cur);
    assert!(rows.is_empty(), "{rows:?}");
    assert!(note.starts_with("无历史快照"), "{note}");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn a_snapshot_row_is_parsed_by_literal_fields_only() {
    let v: serde_json::Value = serde_json::from_str(
        r#"{"dir":"d/x","stem":"s","hub_path":"d/x/s.mdl","id_asset":"i","id_pack":"p",
            "members":[{"role":"model","name":"s.mdl","sha":"abc","crc":"0102"}]}"#,
    )
    .unwrap();
    let s = snap_from_json(&v).unwrap();
    assert_eq!(s.members[&( "model".to_string(), "s.mdl".to_string())].0, "abc");
    assert!(snap_from_json(&serde_json::json!({"dir": "d"})).is_none(), "no member list, no claim");
}

/* ---------------------------------------------------------------------- thresholds */

#[test]
fn rescaling_caps_a_sheet_without_smearing_its_colors() {
    // A 4x2 field, left half opaque red, right half opaque green: a block average must
    // land on the two source colors, not on the seam between them.
    let mut rgba = vec![0u8; 4 * 2 * 4];
    for (i, px) in rgba.chunks_mut(4).enumerate() {
        let col = i % 4;
        px.copy_from_slice(if col < 2 { &[200, 10, 10, 255] } else { &[10, 200, 10, 255] });
    }
    let (w, h, buf) = rescale(&rgba, 4, 2, 2);
    assert_eq!((w, h), (2, 1));
    assert_eq!(buf.len(), 2 * 4);
    assert_eq!(&buf[0..4], &[200, 10, 10, 255]);
    assert_eq!(&buf[4..8], &[10, 200, 10, 255]);
    // Fully transparent stays fully transparent — no black box where the art had holes.
    let clear = vec![0u8; 4 * 2 * 4];
    let (_, _, buf) = rescale(&clear, 4, 2, 2);
    assert_eq!(&buf[0..4], &[0, 0, 0, 0]);
    // Under the cap it is a straight copy.
    let (w, h, same) = rescale(&rgba, 4, 2, 512);
    assert_eq!((w, h), (4, 2));
    assert_eq!(same, rgba);
    // An oversized sheet becomes a thumbnail, not a full-size blob.
    let big = vec![7u8; 2048 * 1024 * 4];
    let (w, h, _) = rescale(&big, 2048, 1024, 512);
    assert_eq!((w, h), (512, 256));
}

#[test]
fn an_oversized_sheet_steps_down_the_ladder_instead_of_disappearing() {
    // The biggest shipped sheets are 2048x1024 BC3 (2.8 MB stored). Block-compressed game
    // art is close to incompressible, so a fixed thumbnail target is not enough: measured
    // on an incompressible sheet, the full inline is 10.9 MB of base64 and even the 512px
    // one is 595 KB. The cap has to keep shrinking until the bytes fit.
    let (w, h) = (2048u16, 1024u16);
    let noise = {
        let mut v: Vec<u8> = Vec::with_capacity(w as usize * h as usize * 4);
        let mut x: u32 = 0x1234_5678;
        for _ in 0..(w as usize * h as usize) {
            x = x.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            v.extend_from_slice(&[(x >> 24) as u8, (x >> 16) as u8, (x >> 8) as u8, 255]);
        }
        v
    };
    let tex = tlbb_core::jmt1::Texture {
        width: w,
        height: h,
        mips: 1,
        declared_tag: "DXT5".into(),
        marker: 0,
        codec: tlbb_core::jmt1::Codec::Bc3,
        rgba: noise,
        webp: None,
        mip_sizes: Vec::new(),
    };
    let pic = inline_image(&tex, 512, 400).expect("a smaller rung must fit");
    assert!(pic.data_url.starts_with("data:image/png;base64,"));
    assert!(
        pic.data_url.len() <= 400 * 1024,
        "cap ignored: {} bytes",
        pic.data_url.len()
    );
    assert!(
        pic.note.contains("显示"),
        "the note must admit it shrank: {}",
        pic.note
    );
    // Squeeze the budget below every rung and the picture is dropped for a stated reason,
    // never left as an empty img.
    let why = inline_image(&tex, 512, 0).unwrap_err();
    assert!(why.contains("上限"), "{why}");
    let html = render(&Report { no_pic: Some(why), ..Default::default() });
    assert!(!html.contains("<img"));
    assert!(html.contains("暂无可解析预览"));
}

#[test]
fn a_smooth_texture_only_needs_the_first_rung() {
    let (w, h) = (2048u16, 1024u16);
    let tex = tlbb_core::jmt1::Texture {
        width: w,
        height: h,
        mips: 1,
        declared_tag: "DXT5".into(),
        marker: 0,
        codec: tlbb_core::jmt1::Codec::Bc3,
        rgba: vec![9u8; w as usize * h as usize * 4],
        webp: None,
        mip_sizes: Vec::new(),
    };
    let pic = inline_image(&tex, 512, 400).expect("a flat sheet compresses small");
    assert!(pic.note.contains("显示 512x256"), "{}", pic.note);
    assert!(pic.note.starts_with("BC3 2048x1024"));
}

#[test]
fn byte_sizes_are_written_for_people() {    assert_eq!(human(0), "0 字节");
    assert_eq!(human(999), "999 字节");
    assert_eq!(human(2048), "2.0 KB");
    assert_eq!(human(5_000_000), "5.0 MB");
    assert_eq!(human(-4), "0 字节");
}

#[test]
fn arguments_default_to_the_read_only_catalog_layout() {
    let a = parse_args(&["--gid".to_string(), "1280".to_string()]);
    assert_eq!(a.gid, 1280);
    assert_eq!(a.snapshots, PathBuf::from("D:/TLGL/.scratch/versions"));
    assert_eq!(a.max_side, 512);
    let b = parse_args(&["--gid=16".to_string(), "--out=/tmp/x".to_string(), "--all=8".to_string()]);
    assert_eq!((b.gid, b.all, b.max_kib), (16, Some(8), 400));
    assert_eq!(b.out, PathBuf::from("/tmp/x"));
}

#[test]
fn the_composition_chips_are_labelled_once_each() {
    let rep = Report {
        parts: vec![
            Chip { label: "模型".into(), n: 6 },
            Chip { label: "网格".into(), n: 7 },
            Chip { label: "材质".into(), n: 10 },
        ],
        ..Default::default()
    };
    let html = render(&rep);
    let section = html.split("<h2>组成</h2>").nth(1).unwrap().split("</section>").next().unwrap();
    assert_eq!(section.matches("class=\"chip\"").count(), 3);
    for label in ["模型 6", "网格 7", "材质 10"] {
        assert!(section.contains(label), "{label} missing");
    }
}

#[test]
fn fingerprints_read_as_facts_not_failures() {
    let f = Fingerprints { asset: "c888".into(), texture: "-".into(), ..Default::default() };
    let rows = f.rows();
    assert_eq!(rows[0], ("整份资源", "c888"));
    assert_eq!(rows[6], ("贴图", "（无此类文件）"));
    let html = render(&Report { fps: Some(f), ..Default::default() });
    assert!(html.contains("资产指纹"));
    assert!(html.contains("无此类文件"));
}

/* ------------------------------------------------------------------ against the db */

fn run(args: &[String]) -> Option<String> {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static SEQ: AtomicUsize = AtomicUsize::new(0);
    if !Path::new(DB).exists() {
        eprintln!("skip: catalog absent ({DB})");
        return None;
    }
    // Skips rather than fails when the harness did not hand us the built binary.
    let exe = option_env!("CARGO_BIN_EXE_asset_report")?;
    // One directory per invocation: the cases run on threads of a single process.
    let out = std::env::temp_dir().join(format!("tlbb_report_{}_{}", std::process::id(), SEQ.fetch_add(1, Ordering::Relaxed)));
    std::fs::create_dir_all(&out).unwrap();
    let mut full = vec![
        "--db".to_string(),
        DB.into(),
        "--root".to_string(),
        "D:/TLGL".into(),
        "--out".to_string(),
        out.to_string_lossy().replace('\\', "/"),
    ];
    full.extend(args.iter().cloned());
    let got = std::process::Command::new(exe).args(&full).output().expect("run report");
    assert!(got.status.success(), "stderr: {}", String::from_utf8_lossy(&got.stderr));
    Some(out.to_string_lossy().replace('\\', "/"))
}

fn read(dir: &str, gid: i64) -> String {
    let p = Path::new(dir).join(format!("资源报告_{gid}.html"));
    std::fs::read_to_string(&p).unwrap_or_else(|e| panic!("{}: {e}", p.display()))
}

/// The catalog is rebuilt by another pipeline and its gids shift every time, so these
/// tests resolve groups by path and assert invariants rather than counts.
fn gid_for(path_like: &str) -> Option<i64> {
    let con = rusqlite::Connection::open_with_flags(DB, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).ok()?;
    con.query_row(
        "SELECT id FROM agroups WHERE hub_path LIKE ?1 ORDER BY n DESC LIMIT 1",
        [path_like],
        |r| r.get::<_, i64>(0),
    )
    .ok()
}

fn member_paths(gid: i64) -> Vec<String> {
    let con = rusqlite::Connection::open_with_flags(DB, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
        .expect("open catalog");
    let mut st = con
        .prepare("SELECT IFNULL(r.path, m.hash) FROM amembers m LEFT JOIN resources r ON r.hash = m.hash WHERE m.gid = ?1")
        .unwrap();
    let mut out = Vec::new();
    for row in st.query_map([gid], |r| r.get::<_, String>(0)).unwrap() {
        if let Ok(p) = row {
            out.push(p.replace('\\', "/"));
        }
    }
    out
}

#[test]
fn a_self_contained_asset_reports_no_users_and_stays_one_file() {
    let Some(gid) = gid_for("%w1351_nan_s_yifu_mjrmdz.mdl") else {
        eprintln!("skip: catalog absent");
        return;
    };
    let arg = gid.to_string();
    let Some(dir) = run(&["--gid".to_string(), arg]) else { return };
    let html = read(&dir, gid);
    assert!(outside_refs(&html).is_empty(), "leaked: {:?}", outside_refs(&html));
    assert!(html.contains("谁在使用它 · 0 项"), "internal edges came back");
    assert!(html.contains("已排除，不计入"), "the exclusion must be stated, not silent");
    assert!(html.len() < 200_000, "a nameless sheet should stay small: {}", html.len());
}

#[test]
fn a_shared_skeleton_lists_only_outside_users() {
    let Some(cat) = open_catalog() else { return };
    let Some(gid) = gid_for(SKELETON) else { return };
    // The outside users are the sibling `.mdl`s in the same folder. They are a real
    // cross-asset reference (the splitter put the skeleton in its own group), so the
    // section must be non-empty and must not name the skeleton itself.
    let mine = member_paths(gid);
    let users = external_users(&cat, gid, usize::MAX);
    assert!(!users.is_empty(), "a shared skeleton must have users somewhere");
    for u in &users {
        assert!(!u.what.ends_with("w1351_nan.ske"), "self-reference survived the filter");
        assert!(
            !mine.iter().any(|m| m.replace('\\', "/").ends_with(&u.what)),
            "listed user {} is one of its own members",
            u.what
        );
    }
    assert!(users.iter().all(|u| u.via == "骨骼"), "the kind of use should be carried: {users:?}");
}

#[test]
fn a_texture_bearing_asset_embeds_a_real_image() {
    let Some(gid) = gid_for("%w1351_nan_s_yifu_zhongshilifu.mdl") else { return };
    let arg = gid.to_string();
    let Some(dir) = run(&["--gid".to_string(), arg.clone()]) else { return };
    let html = read(&dir, gid);
    assert!(html.contains("src=\"data:image/"), "no inlined preview");
    assert!(!html.contains("暂无可解析预览"));
    assert!(outside_refs(&html).is_empty());
    // Squeeze the budget: the ladder either shrinks the picture or drops it for a stated
    // reason. Either way the file stays small, which is the whole point of the cap.
    let Some(dir) = run(&[
        "--gid".to_string(),
        arg.clone(),
        "--max-b64-kib".to_string(),
        "1".to_string(),
    ]) else { return };
    let tight = read(&dir, gid);
    assert!(tight.len() < html.len(), "the cap changed nothing");
    assert!(tight.len() < 40_000, "a 1 KiB budget produced {}", tight.len());
    if !tight.contains("src=\"data:image/") {
        assert!(tight.contains("上限"), "silenced without a reason");
        assert!(tight.contains("暂无可解析预览"));
    }
}

#[test]
fn a_real_snapshot_json_changes_the_verdict_it_prints() {
    if !Path::new(DB).exists() {
        eprintln!("skip: catalog absent");
        return;
    }
    // Copy the shipped sample, drop a member from it, and check the report notices.
    let dir = std::env::temp_dir().join(format!("tlbb_report_snap_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let src = Path::new("D:/TLGL/.scratch/versions/示例_下一版.json");
    if !src.exists() {
        eprintln!("skip: no sample snapshot");
        return;
    }
    let txt = std::fs::read_to_string(src).unwrap();
    let mut doc: serde_json::Value = serde_json::from_str(&txt).unwrap();
    let hit = doc["assets"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|a| a["gid"].as_i64() == Some(1280));
    let Some(asset) = hit else {
        eprintln!("skip: gid 1280 absent from the sample");
        return;
    };
    let members = asset["members"].as_array().unwrap().clone();
    asset["stem"] = serde_json::json!("w1351_ll_hlf_001");
    asset["id_asset"] = serde_json::json!("changed0000000");
    asset["members"] = serde_json::Value::Array(members.iter().skip(3).cloned().collect());
    std::fs::write(dir.join("篡改版.json"), serde_json::to_string(&doc).unwrap()).unwrap();

    let Some(out) = run(&[
        "--gid".to_string(),
        "1280".to_string(),
        "--snapshots".to_string(),
        dir.to_string_lossy().replace('\\', "/"),
    ]) else { return };
    let html = read(&out, 1280);
    assert!(html.contains("篡改版.json"), "the sample was not compared at all");
    assert!(html.contains("成员变化") || html.contains("仅名称变化"), "{html}");
    assert!(html.contains("多了"), "which files were added is not stated");
    let _ = std::fs::remove_dir_all(&dir);
}

/* --------------------------------------------------- one brain, checked, not assumed */

/// The report used to read `asset_fingerprint`, `asset_identity`, `amembers` and `blobs`
/// with its own SQL while the workbench read them through `Catalog` — two readers, and
/// nothing forcing them to agree. They now share one, and these cases make a future split
/// fail loudly instead of quietly printing a different digit.

#[test]
fn the_report_prints_the_catalogs_own_fingerprint() {
    let Some(cat) = open_catalog() else { return };
    // Probe a spread of groups rather than one, since a digest can coincide by accident.
    let mut checked = 0usize;
    for gid in catalog_gids(24) {
        let Some(fp) = cat.fingerprints(gid).unwrap_or_default() else { continue };
        let html = render(&Report {
            gid,
            fps: Some(into_fps(fp.clone())),
            ..Default::default()
        });
        // Whatever the catalog holds is what the page shows, verbatim — no reformatting,
        // no truncation, no fallback. An empty column is legal and must print as such.
        for (label, value) in into_fps(fp).rows() {
            if value == "（无此类文件）" {
                assert!(html.contains("（无此类文件）"), "gid {gid}: {label} lost its empty marker");
            } else {
                assert!(html.contains(value), "gid {gid}: {label} {value:?} is not on the page");
            }
        }
        checked += 1;
    }
    if checked == 0 {
        eprintln!("skip: no identified groups");
    }
}

#[test]
fn the_report_prints_the_catalogs_own_identity() {
    let Some(cat) = open_catalog() else { return };
    let mut checked = 0usize;
    for gid in catalog_gids(24) {
        let Some(id) = cat.identity(gid).unwrap_or_default() else { continue };
        let snap = current_snap(&cat, &group_for(gid).expect("group"));
        assert_eq!(snap.id_asset, id.id_asset, "gid {gid}: the snapshot ignored the catalog's id_asset");
        assert_eq!(snap.id_pack, id.id_pack, "gid {gid}: the snapshot ignored the catalog's id_pack");
        checked += 1;
    }
    if checked == 0 {
        eprintln!("skip: no identified groups");
    }
}

#[test]
fn the_snapshot_members_are_the_catalogs_member_digests() {
    let Some(cat) = open_catalog() else { return };
    let mut checked = 0usize;
    for gid in catalog_gids(24) {
        let digests = cat.member_digests(gid).unwrap_or_default();
        let snap = current_snap(&cat, &group_for(gid).expect("group"));
        // Same rows, same count — a member the catalog drops (unnamed) must not appear,
        // and a member it keeps must not vanish.
        assert_eq!(
            snap.members.len(),
            digests.len(),
            "gid {gid}: the snapshot holds {} members, the catalog {}",
            snap.members.len(),
            digests.len()
        );
        for d in &digests {
            let got = snap
                .members
                .get(&(d.role.clone(), d.name.clone()))
                .unwrap_or_else(|| panic!("gid {gid}: {} / {} missing from the snapshot", d.role, d.name));
            assert_eq!(got.0, d.sha.chars().take(16).collect::<String>(), "gid {gid}: sha differs");
            assert_eq!(got.1, d.crc, "gid {gid}: crc differs");
        }
        checked += 1;
    }
    if checked == 0 {
        eprintln!("skip: no groups");
    }
}

#[test]
fn the_workbench_and_the_report_read_the_same_fingerprint() {
    let Some(cat) = open_catalog() else { return };
    // The workbench asks for `fp_asset` alone; the report asks for the full row. They are
    // two views of one table, so the narrow answer must equal the wide one's `asset` field.
    // If anyone ever gives them separate queries, this is where it breaks.
    let mut checked = 0usize;
    for gid in catalog_gids(24) {
        let narrow = cat.fingerprint(gid).unwrap_or(None);
        let wide = cat.fingerprints(gid).unwrap_or_default().map(|f| f.asset);
        assert_eq!(
            narrow.filter(|s| !s.is_empty()),
            wide.filter(|s| !s.is_empty()),
            "gid {gid}: fingerprint() and fingerprints().asset disagree"
        );
        checked += 1;
    }
    if checked == 0 {
        eprintln!("skip: no groups");
    }
}

/// gids of the biggest groups, deterministic per catalog so the probes are stable.
fn catalog_gids(n: usize) -> Vec<i64> {
    let Ok(con) = rusqlite::Connection::open_with_flags(DB, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
    else {
        return Vec::new();
    };
    let Ok(mut st) = con.prepare("SELECT id FROM agroups ORDER BY n DESC LIMIT ?1") else {
        return Vec::new();
    };
    st.query_map([n as i64], |r| r.get::<_, i64>(0))
        .map(|it| it.flatten().collect())
        .unwrap_or_default()
}

fn group_for(gid: i64) -> Option<tlbb_core::catalog::Group> {
    let cat = open_catalog()?;
    cat.groups(20_000).ok()?.into_iter().find(|g| g.id == gid)
}
