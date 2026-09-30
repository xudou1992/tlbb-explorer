//! JBCF container tests: synthetic round trip plus one real shipped material.

use std::path::Path;

use tlbb_core::jbcf::{parse, role, round8, Role, STRTABLE_ID, ROOT_ID};

/// Build a grammar-accurate JBCF: 16-byte header, root chunk 86, then the string table
/// at the position the engine predicts.
fn build(root_body: &[u8], strings: &[&str]) -> Vec<u8> {
    let chars: Vec<u8> = strings.iter().flat_map(|s| s.as_bytes().to_vec()).collect();
    let count = strings.len() as u32;
    let table_size = 8 + 8 * count + chars.len() as u32;

    let mut v = Vec::new();
    v.extend_from_slice(b"JBCF");
    v.extend_from_slice(&0u32.to_le_bytes()); // +4
    v.extend_from_slice(&8u32.to_le_bytes()); // +8
    v.extend_from_slice(&0u32.to_le_bytes()); // +12 body length, filled below
    v.extend_from_slice(&ROOT_ID.to_le_bytes());
    v.extend_from_slice(&(root_body.len() as u32).to_le_bytes());
    v.extend_from_slice(root_body);
    // The engine predicts the table at round8(root.size) + 24; place it exactly there.
    let table_at = round8(root_body.len() as u32) + 24;
    while v.len() < table_at as usize {
        v.push(0);
    }
    v.extend_from_slice(&STRTABLE_ID.to_le_bytes());
    v.extend_from_slice(&table_size.to_le_bytes());
    v.extend_from_slice(&0u32.to_le_bytes()); // flag
    v.extend_from_slice(&count.to_le_bytes());
    for s in strings {
        v.extend_from_slice(&(s.len() as u32).to_le_bytes());
        v.extend_from_slice(&((0x1234_0000u32 | s.len() as u32) as u32).to_le_bytes());
    }
    v.extend_from_slice(&chars);
    let body = (v.len() - 16) as u32;
    v[12..16].copy_from_slice(&body.to_le_bytes());
    v
}

#[test]
fn round_trip_recovers_every_string_and_role() {
    let raw = build(b"root", &["body.tga", "template_default.mtl", "DynModelShader"]);
    let f = parse(&raw).expect("parse");
    assert_eq!(f.strings.len(), 3);
    assert_eq!(f.names(Role::Texture), vec!["body.tga"]);
    assert_eq!(f.names(Role::Material), vec!["template_default.mtl"]);
    assert_eq!(f.names(Role::Shader), vec!["DynModelShader"]);
    assert_eq!(f.strings[0].hash, 0x1234_0008);
    assert_eq!(f.strtab_at, predicted(&raw));
}

/// Where the engine says the table should be — the parser must agree without scanning.
fn predicted(raw: &[u8]) -> usize {
    let root_size = u32::from_le_bytes(raw[20..24].try_into().unwrap());
    round8(root_size) as usize + 24
}

#[test]
fn role_classifies_by_extension() {
    assert_eq!(role("a/b/body.TGA"), Role::Texture);
    assert_eq!(role("template_default.mtl"), Role::Material);
    assert_eq!(role("MainBody.ske"), Role::Skeleton);
    assert_eq!(role("idle01.ani"), Role::Animation);
    assert_eq!(role("NewSfxShader"), Role::Shader);
    assert_eq!(role("plain text"), Role::Other);
}

#[test]
fn rejects_foreign_and_inconsistent_payloads() {
    assert!(parse(b"JXYZ\0\0\0\0\0\0\0\0\0\0\0\0").is_err());

    let mut raw = build(b"x", &["a.tga"]);
    let n = raw.len();
    raw.truncate(n - 1); // character area is one byte short of what the table declares
    assert!(parse(&raw).is_err());

    let mut raw = build(b"x", &["a.tga"]);
    raw[16..20].copy_from_slice(&99u32.to_le_bytes()); // root chunk is not 86
    assert!(parse(&raw).is_err());

    let mut raw = build(b"x", &["a.tga"]);
    raw[12..16].copy_from_slice(&0u32.to_le_bytes()); // body length lies
    assert!(parse(&raw).is_err());
}

/// End to end over shipped data: a real `.mtl` must yield its texture and parent names,
/// and the catalog must resolve the parent to a hash while the texture stays dangling
/// (world textures are indexed by a path table this install does not contain).
#[test]
fn shipped_material_exposes_its_graph() {
    let root = Path::new("D:/TLGL");
    let db = Path::new("D:/TLGL/.scratch/resources.db");
    if !root.join("data.pak").exists() || !db.exists() {
        eprintln!("skip: game data not present");
        return;
    }
    let cat = tlbb_core::catalog::Catalog::open_ro(db).expect("open catalog");
    let path = "data/source/npc/quest/w1351_boss_sunmeimei/w1351_boss_sunmeimei_lian_001.mtl";
    let hash = cat
        .hash_by_path(path)
        .expect("query")
        .unwrap_or_else(|| panic!("{path} missing from catalog"));
    let asset = cat.asset(hash).expect("asset").expect("asset row");
    let pak = tlbb_core::Pak::open(root.join(format!("{}.pak", asset.pak))).expect("pak");
    let rec = pak
        .records()
        .find(|r| r.hash == hash)
        .expect("record");
    let decoded = tlbb_core::payload::decode(&pak, &rec).expect("decode");
    let f = parse(&decoded.bytes).expect("jbcf");

    assert_eq!(role(path), Role::Material);
    assert!(!f.names(Role::Texture).is_empty(), "no textures named");
    // 真数据闸门：这份材质里有中文贴图名（GBK），解错就会在界面上摆一排
    // 替换符。名字带 U+FFFD 就是解码链路坏了，不是「客户端给了乱码」。
    let garbled: Vec<&String> = f
        .strings
        .iter()
        .map(|s| &s.text)
        .filter(|t| t.contains('\u{FFFD}'))
        .collect();
    assert!(
        garbled.is_empty(),
        "字符串表里出现替换符，GBK 没解对：{garbled:?}"
    );
    let has_cjk = f.strings.iter().any(|s| {
        s.text
            .chars()
            .any(|c| ('\u{4E00}'..='\u{9FFF}').contains(&c))
    });
    assert!(has_cjk, "这份 .mtl 里该有中文贴图名，一个都没解出来");
    assert!(
        f.names(Role::Material).iter().any(|m| m.ends_with(".mtl")),
        "no parent material"
    );
    // `refs` keeps only the path-like strings, so it is a subset of the table.
    let refs = cat.refs_from(hash).expect("refs");
    assert!(!refs.is_empty() && refs.len() <= f.strings.len(), "catalog refs drifted");
    for r in &refs {
        assert!(
            f.strings.iter().any(|s| s.text == r.name),
            "ref {} is not in the string table",
            r.name
        );
    }
    let resolved = refs.iter().filter(|r| r.to.is_some()).count();
    assert!(
        resolved >= 1 && resolved < refs.len(),
        "expected the parent .mtl to resolve while its texture stays dangling, got {resolved}/{}",
        refs.len()
    );
}
