//! 那 22,749 条「取不出网格」的摆位记录，文件到底在不在容器里？
//!
//! 之前用 Python 扫索引得过 0/120，但**同一套扫描在对照样本上只查到 4/60**——
//! 说明是扫描姿势错了，那个 0 不算证据。这里改用仓库自己的 `Pak::records()`
//! （`gap.rs` 数出 119,340 条索引记录用的就是它）重做一遍，并且**先跑对照组**：
//! 对照组查不到，就什么都不许下结论。
//!
//!   cargo run --release --example mesh_presence_check

use std::collections::HashSet;
use std::fs;
use std::path::PathBuf;

use tlbb_core::jpak::crypto::path_hash;
use tlbb_core::jpak::Pak;

fn read_lines(p: &str) -> Vec<String> {
    fs::read_to_string(p)
        .unwrap_or_default()
        .lines()
        .map(|l| l.trim().to_string())
        .filter(|l| !l.is_empty())
        .collect()
}

fn main() {
    let root = PathBuf::from("D:/TLGL");
    let control = read_lines("D:/TLGL/.scratch/control_mesh_paths.txt");
    let missing = read_lines("D:/TLGL/.scratch/missing_mesh_paths.txt");
    if control.is_empty() || missing.is_empty() {
        println!("两组路径有一组是空的，先跑导出脚本");
        return;
    }
    let mut want_ctl: HashSet<u64> = HashSet::new();
    let mut want_miss: HashSet<u64> = HashSet::new();
    for p in &control {
        want_ctl.insert(path_hash(p));
    }
    for p in &missing {
        want_miss.insert(path_hash(p));
    }
    let mut names: Vec<String> = vec!["data".into()];
    for i in 1..8 {
        let stem = format!("data{i}");
        if root.join(format!("{stem}.pak")).is_file() {
            names.push(stem);
        }
    }
    if root.join("data_1.pak").is_file() {
        names.push("data_1".into());
    }
    let mut found_ctl: HashSet<u64> = HashSet::new();
    let mut found_miss: HashSet<u64> = HashSet::new();
    let mut records = 0usize;
    let mut bad = Vec::new();
    for stem in &names {
        let path = root.join(format!("{stem}.pak"));
        match Pak::open(&path) {
            Ok(pak) => {
                for rec in pak.records() {
                    records += 1;
                    if want_ctl.contains(&rec.hash) {
                        found_ctl.insert(rec.hash);
                    }
                    if want_miss.contains(&rec.hash) {
                        found_miss.insert(rec.hash);
                    }
                }
            }
            Err(e) => bad.push(format!("{stem}.pak：{e}")),
        }
    }
    let mut out = String::new();
    out.push_str(&format!(
        "容器 {} 个（读失败 {}）· 索引记录 {} 条\n对照组（清单里已存在的网格路径）：{} / {} 在容器索引里查到\n待解组（缺失名在 ResourcePath.cfg 里的路径）：{} / {} 在容器索引里查到\n",
        names.len(),
        bad.len(),
        records,
        found_ctl.len(),
        want_ctl.len(),
        found_miss.len(),
        want_miss.len(),
    ));
    if bad.len() > 0 {
        out.push_str(&format!("读失败：{}\n", bad.join("；")));
    }
    // 对照组查不到就什么都别说：这条管道连已知存在的东西都报不出来。
    if found_ctl.len() * 10 < want_ctl.len() * 8 {
        out.push_str("⚠ 对照组命中率低于 80%，这条管道不可信，上面的数字不许当结论用。\n");
    } else {
        out.push_str("对照组可信（≥80%），待解组那个数可以用。\n");
    }
    fs::write("D:/TLGL/.scratch/mesh_presence_check.txt", &out).ok();
    print!("{out}");
}
