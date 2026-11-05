//! pu_census — 全库 `.pu`（JBPU）特效文件的普查（v0.6 的盘子）。
//!
//! 回答「特效播放到底有多少可做」：多少份能解、每份几个发射器/更新器、
//! 参数记录按 cls 的分布、字符串条数。只统计，不推断语义。
//!
//! 用法：
//! ```text
//! pu_census --db D:/TLGL/.scratch/resources.db --root D:/TLGL --out D:/TLGL/.scratch/pu_census
//! ```

use std::collections::{BTreeMap, HashMap};
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::effect::{parse_pu, Effect};
use tlbb_core::preview::pu_field_name;

fn arg(name: &str) -> Option<String> {
    let a: Vec<String> = std::env::args().collect();
    a.iter().position(|x| x == name).and_then(|i| a.get(i + 1)).cloned()
}

fn main() {
    let db = arg("--db").unwrap_or_else(|| "D:/TLGL/.scratch/resources.db".into());
    let root = PathBuf::from(arg("--root").unwrap_or_else(|| "D:/TLGL".into()));
    let out = PathBuf::from(arg("--out").unwrap_or_else(|| "D:/TLGL/.scratch/pu_census".into()));
    std::fs::create_dir_all(&out).ok();

    let con = rusqlite::Connection::open_with_flags(
        &db,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY | rusqlite::OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("打开清单");

    let mut files: Vec<PathBuf> = std::fs::read_dir(&root)
        .expect("读取包目录")
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.extension().map(|x| x.eq_ignore_ascii_case("pak")).unwrap_or(false))
        .collect();
    files.sort();
    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut idx: HashMap<(String, u64), tlbb_core::jpak::Record> = HashMap::new();
    for path in files {
        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
        let pak = Pak::open(&path).expect("以只读方式打开 pak");
        for rec in pak.records() {
            idx.insert((stem.clone(), rec.hash), rec);
        }
        paks.insert(stem, pak);
    }

    let mut stmt = con
        .prepare("select coalesce(pak,''), hash, coalesce(path,''), coalesce(offset,-1) from resources where ext = '.pu' order by path")
        .expect("查询 .pu");
    let rows: Vec<(String, String, String, i64)> = stmt
        .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)))
        .unwrap()
        .flatten()
        .collect();

    let mut total = 0usize;
    let mut decoded = 0usize;
    let mut parsed = 0usize;
    let mut cls: BTreeMap<u16, usize> = BTreeMap::new();
    let mut emitters: BTreeMap<String, usize> = BTreeMap::new();
    let mut updaters: BTreeMap<String, usize> = BTreeMap::new();
    let mut renderers: BTreeMap<String, usize> = BTreeMap::new();
    let mut no_emitter = 0usize;
    let mut records_total = 0usize;
    let mut named_records = 0usize;
    let mut tsv = String::from("path|decoded|parsed|strings|records|emitters|updaters|renderers\n");

    for (pak, hex, path, offset) in &rows {
        total += 1;
        let Ok(hash) = u64::from_str_radix(hex, 16) else { continue };
        let Some(rec) = idx.get(&(pak.clone(), hash)) else { tsv.push_str(&format!("{path}|no-record\n")); continue };
        if rec.offset as i64 != *offset { tsv.push_str(&format!("{path}|moved\n")); continue }
        let Some(p) = paks.get(pak) else { tsv.push_str(&format!("{path}|no-pak\n")); continue };
        let Ok(d) = payload::decode(p, rec) else { tsv.push_str(&format!("{path}|decode-fail\n")); continue };
        decoded += 1;
        let Some(e): Option<Effect> = parse_pu(&d.bytes) else { tsv.push_str(&format!("{path}|parse-fail\n")); continue };
        parsed += 1;
        let mut row_cls: BTreeMap<u16, usize> = BTreeMap::new();
        for r in &e.param_records {
            *cls.entry(r.cls).or_insert(0) += 1;
            *row_cls.entry(r.cls).or_insert(0) += 1;
            records_total += 1;
            if pu_field_name(r.fld).is_some() {
                named_records += 1;
            }
        }
        let _ = row_cls;
        let n = &e.names;
        for x in &n.emitters { *emitters.entry(x.clone()).or_insert(0) += 1; }
        for x in &n.updaters { *updaters.entry(x.clone()).or_insert(0) += 1; }
        for x in &n.renderers { *renderers.entry(x.clone()).or_insert(0) += 1; }
        if n.emitters.is_empty() { no_emitter += 1; }
        tsv.push_str(&format!(
            "{}|{decoded}|{parsed}|{}|{}|{}|{}|{}\n",
            path, e.strings.len(), e.param_records.len(),
            n.emitters.join(","), n.updaters.join(","), n.renderers.join(",")
        ));
    }

    std::fs::write(out.join("pu_census.tsv"), tsv).ok();
    let mut md = String::new();
    md.push_str(&format!(
        "# .pu 特效普查\n\n- `.pu` 条目 **{total}** 条；解码成功 **{decoded}**；JBPU 解析成功 **{parsed}**。\n- 参数记录共 **{records_total}** 条，其中字段名能对上属性表的 **{named_records}** 条。\n- 没有发射器名字的 **{no_emitter}** 份。\n\n## 参数 cls 分布\n\n| cls | 条数 |\n|---|---|\n"
    ));
    for (k, v) in &cls { md.push_str(&format!("| {k} | {v} |\n")); }
    md.push_str("\n## 发射器（按出现份数）\n\n| 名字 | 份数 |\n|---|---|\n");
    let mut ev: Vec<_> = emitters.iter().collect();
    ev.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in ev.iter().take(15) { md.push_str(&format!("| {k} | {v} |\n")); }
    md.push_str("\n## 更新器（按出现份数）\n\n| 名字 | 份数 |\n|---|---|\n");
    let mut uv: Vec<_> = updaters.iter().collect();
    uv.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in uv.iter().take(15) { md.push_str(&format!("| {k} | {v} |\n")); }
    md.push_str("\n## 渲染器\n\n| 名字 | 份数 |\n|---|---|\n");
    let mut rv: Vec<_> = renderers.iter().collect();
    rv.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in rv.iter().take(15) { md.push_str(&format!("| {k} | {v} |\n")); }
    std::fs::write(out.join("SUMMARY.md"), md).ok();

    println!(
        ".pu {total} 条：解码 {decoded}，解析 {parsed}，参数记录 {records_total}（有名 {named_records}），无发射器 {no_emitter}"
    );
    println!("cls 分布：{:?}", cls);
    println!("发射器（前 8）：{:?}", ev.iter().take(8).collect::<Vec<_>>());
    println!("更新器（前 8）：{:?}", uv.iter().take(8).collect::<Vec<_>>());
    println!("落盘 {}", out.display());
}
