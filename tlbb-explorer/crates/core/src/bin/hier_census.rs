//! 骨架表（父骨链）解不出的**分桶普查**。
//!
//! `parse_hierarchy` 只回 `Option`——361 份解不出的文件全报同一个 `None`，
//! 没法定位该修哪一族。这里改用带原因的 `hierarchy_try`（判据一字未改），
//! 按原因分桶，再给每族带上可测特征与样本路径。
//!
//! 用法：
//! ```text
//! hier_census --tree=D:\TLGL\.scratch\out\tree [--out=D:\TLGL\.scratch\hier_census.json]
//! ```

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use tlbb_core::preview::{
    bone_count, hierarchy_forest, hierarchy_stuck, hierarchy_try, parse_ani, parse_mesh,
    tail_entries,
};

fn arg(argv: &[String], name: &str) -> Option<String> {
    let want = format!("--{name}=");
    argv.iter()
        .skip(1)
        .find_map(|a| a.strip_prefix(&want))
        .map(|s| s.trim_matches('"').to_string())
}

fn walk(dir: &Path, out: &mut Vec<PathBuf>) {
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                walk(&p, out);
            } else if p.extension().map(|x| x.eq_ignore_ascii_case("mesh")).unwrap_or(false) {
                out.push(p);
            }
        }
    }
}

/// 一族失败的可测特征：够不够把「同一族」再切开。
#[derive(Default, serde::Serialize)]
struct Bucket {
    n: usize,
    declared_sum: u64,
    size_sum: u64,
    with_origin: usize,
    with_root_flag: usize,
    mesh_parse_fail: usize,
    samples: Vec<String>,
    /// 逐行明细（路径 + 声明骨 + 大小），给再切一族用。
    rows: Vec<String>,
}

fn has_origin_record(raw: &[u8]) -> bool {
    let mut i = 0usize;
    while i + 96 <= raw.len() {
        let name = &raw[i..i + 32];
        let end = name.iter().position(|&c| c == 0).unwrap_or(32);
        if end >= 3 && name[..end].eq_ignore_ascii_case(b"origin") {
            return true;
        }
        i += 4;
    }
    false
}

fn has_root_flag(raw: &[u8]) -> bool {
    raw.windows(4).any(|w| w == [0xFF, 0xFF, 0xFF, 0xFF])
}

/// `--stuck`：对「尾部走不通」那族报卡点。判据不参与，纯诊断。
/// 看点两个：卡之前吃下几条条目（`eaten` vs `declared`），以及**卡点处头 4 字节**
/// 是什么——同一族文件会撞在同一个签名上，那就是没认出的块型的入口。
fn stuck_probe(files: &[PathBuf]) {
    use std::collections::BTreeMap;
    let mut sig: BTreeMap<String, usize> = BTreeMap::new();
    let mut rows = Vec::new();
    let mut n = 0usize;
    for f in files {
        let Ok(raw) = std::fs::read(f) else { continue };
        if bone_count(&raw).unwrap_or(0) == 0 {
            continue;
        }
        if hierarchy_try(&raw).is_ok() {
            continue;
        }
        let Some(s) = hierarchy_stuck(&raw) else { continue };
        if s.stopped >= raw.len() {
            continue; // 走到 EOF 了，是条数不对那一族，不是卡住
        }
        n += 1;
        let w = u32::from_le_bytes([raw[s.stopped], raw[s.stopped + 1], raw[s.stopped + 2], raw[s.stopped + 3]]);
        let ascii: String = raw[s.stopped..(s.stopped + 16).min(raw.len())]
            .iter()
            .map(|&c| if (0x20..0x7f).contains(&c) { (c as char).to_string() } else { ".".to_string() })
            .collect();
        *sig.entry(format!("{w:#010x} {ascii}")).or_default() += 1;
        rows.push(format!(
            "{}\t起点 {:#x}\t卡在 {:#x}\t吃了 {}/{} 条\t头 4 字节 {:#010x}\t{ascii}",
            f.to_string_lossy().replace('\\', "/"),
            s.start,
            s.stopped,
            s.eaten,
            s.declared,
            w
        ));
    }
    let mut out = vec![format!("卡住的份数 {n}")];
    out.push("卡点签名 top15：".to_string());
    let mut top: Vec<(&String, &usize)> = sig.iter().collect();
    top.sort_by(|a, b| b.1.cmp(a.1));
    for (k, v) in top.iter().take(15) {
        out.push(format!("  {v:>4} × {k}"));
    }
    out.push(String::new());
    out.extend(rows);
    let txt = r"D:\TLGL\.scratch\hier_stuck.txt";
    let _ = std::fs::write(txt, out.join("\n"));
    println!("WROTE {txt} · 卡住 {n} 份");
}

/// `--forest`：「不是单根」那族到底长什么样——列每份的根名与每棵子树的大小。
/// 只诊断，不参与判定。
fn forest_probe(files: &[PathBuf]) {
    let mut out = Vec::new();
    let mut n = 0usize;
    // 真验证：放开森林之后，这些文件里有多少**真的**被 `hierarchy_forest` 解出来了
    // （不是靠本函数自己的启发式数根）。
    let mut gained = 0usize;
    let mut still = 0usize;
    let mut hist: std::collections::BTreeMap<usize, usize> = std::collections::BTreeMap::new();
    for f in files {
        let Ok(raw) = std::fs::read(f) else { continue };
        if bone_count(&raw).unwrap_or(0) == 0 {
            continue;
        }
        if let Ok(_) = hierarchy_try(&raw) {
            continue;
        }
        if hierarchy_forest(&raw).is_ok() {
            gained += 1;
        } else {
            still += 1;
        }
        let Some(entries) = tail_entries(&raw) else { continue };
        let mut listed: std::collections::HashSet<String> = std::collections::HashSet::new();
        for (_, kids) in &entries {
            for k in kids {
                listed.insert(k.to_ascii_lowercase());
            }
        }
        let roots: Vec<String> = entries
            .iter()
            .filter(|(n, _)| !listed.contains(&n.to_ascii_lowercase()))
            .map(|(n, _)| n.clone())
            .collect();
        if roots.len() < 2 {
            continue; // 不是这一族
        }
        n += 1;
        *hist.entry(roots.len()).or_default() += 1;
        out.push(format!(
            "{}  根 {} 个: {}",
            f.to_string_lossy().replace('\\', "/"),
            roots.len(),
            roots.join(", ")
        ));
    }
    out.insert(0, format!(
        "多根份数 {n} · 根数分布 {hist:?} · 森林口径实际多解出 {gained} 份（其余 {still} 份仍解不出）"
    ));
    let txt = r"D:\TLGL\.scratch\hier_forest.txt";
    let _ = std::fs::write(txt, out.join("\n"));
    println!("WROTE {txt} · 多根 {n} 份 · 森林口径多解出 {gained} 份（仍解不出 {still}）");
}

/// `--corroborate`：拿**另一个文件**当旁证。
///
/// 判据放宽（矩阵三轴允许不等长、行列两向都判）之后，光看「闸门没破」不够——
/// 同一个 `.mesh` 里能互相印证的结构有限，于是用同目录的 `.ani`：
/// 它的每条轨道都带骨名，那是**独立解出来的另一份容器记录**。
/// 若 `.ani` 出现的骨名不在这份网格的父骨链里，说明链少了骨（走段吃错东西的征状）。
fn corroborate(files: &[PathBuf]) {
    let mut checked = 0usize;
    let mut with_ani = 0usize;
    let mut clean = 0usize;
    let mut group_ok = 0usize;
    let mut bad: Vec<(String, usize, String)> = Vec::new();
    for f in files {
        let Ok(raw) = std::fs::read(f) else { continue };
        if bone_count(&raw).unwrap_or(0) == 0 {
            continue;
        }
        let Ok(h) = hierarchy_try(&raw) else { continue };
        let tree: std::collections::HashSet<String> =
            h.bones.iter().map(|b| b.name.to_ascii_lowercase()).collect();
        checked += 1;
        // .ani 不在网格自己目录下，而在同级 `ani/` 子目录（解出来的目录树实测形状：
        // `.../w1351_boss_sangtugong/ani/*.ani` 与 `.../model/<x>/*.mesh`）。
        let mut dirs: Vec<PathBuf> = Vec::new();
        if let Some(d) = f.parent() {
            dirs.push(d.to_path_buf());
            dirs.push(d.join("ani"));
            if let Some(g) = d.parent() {
                dirs.push(g.join("ani"));
            }
        }
        let mut anis: Vec<PathBuf> = Vec::new();
        for d in dirs {
            if let Ok(rd) = std::fs::read_dir(&d) {
                anis.extend(rd.flatten().map(|e| e.path()));
            }
        }
        anis.sort();
        let mut miss: Vec<String> = Vec::new();
        let mut hit_ani = false;
        // `.ani` 自己声明的骨数与实际轨道数：用来分清「链少解了骨」与
        // 「动作本来就驱动一副比网格更大的骨架（动画专用骨）」——两者症状一样，结论完全不同。
        let mut ani_bones = 0usize;
        let mut ani_tracks = 0usize;
        for ap in anis {
            if ap.extension().and_then(|x| x.to_str()) != Some("ani") {
                continue;
            }
            let Ok(ab) = std::fs::read(&ap) else { continue };
            let Some(a) = parse_ani(&ab) else { continue };
            hit_ani = true;
            ani_bones = a.bones;
            ani_tracks = a.tracks.len();
            for t in &a.tracks {
                if !tree.contains(&t.bone.to_ascii_lowercase()) && t.bone.len() > 2 {
                    miss.push(t.bone.clone());
                }
            }
            break;
        }
        if !hit_ani {
            continue;
        }
        with_ani += 1;
        miss.sort();
        miss.dedup();
        if miss.is_empty() {
            clean += 1;
            continue;
        }
        // 一条 `.ani` 驱动的是**整组网格拼起来的骨架**（2026-10-10 实测：`zhaotianshi`
        // 部件链 118 根 + 动作另 59 根 = 177，与「主网格 ∪ 四份部件」的 177 根逐数对上）。
        // 所以报缺之后必须再拿同目录全部网格的并集判一次——只对一份部件网格就报「缺骨」，
        // 是对照对象拿错了，不是父骨链解错。
        let mut union = tree.clone();
        if let Some(d) = f.parent() {
            if let Ok(rd) = std::fs::read_dir(d) {
                for e in rd.flatten() {
                    let q = e.path();
                    if q.extension().and_then(|x| x.to_str()) != Some("mesh") || q == *f {
                        continue;
                    }
                    let Ok(rb) = std::fs::read(&q) else { continue };
                    if let Ok(h2) = hierarchy_try(&rb) {
                        union.extend(h2.bones.iter().map(|b| b.name.to_ascii_lowercase()));
                    }
                }
            }
        }
        if miss.iter().all(|m| union.contains(&m.to_ascii_lowercase())) {
            group_ok += 1;
        } else {
            let left: Vec<String> = miss
                .iter()
                .filter(|m| !union.contains(&m.to_ascii_lowercase()))
                .cloned()
                .collect();
            let sample = left.iter().take(3).cloned().collect::<Vec<_>>().join(", ");
            bad.push((
                f.display().to_string(),
                left.len(),
                format!(
                    "ani 声明 {ani_bones} 骨 / 轨道 {ani_tracks} 条，这份链 {} 根，并集仍缺：{sample}",
                    tree.len()
                ),
            ));
        }
    }
    bad.sort_by_key(|b| std::cmp::Reverse(b.1));
    println!(
        "父骨链解出且同目录有可读 .ani 的份数 {with_ani}（树解出总数 {checked}）：
           .ani 骨名全在这一份的链里 = {clean} · 单份有缺 {bad_n} 份，
           其中拿**同目录全部网格的并集**再判就对上的 = {group_ok} 份 · 并集仍对不上 = {} 份",
        bad.len(), bad_n = with_ani - clean
    );
    for (p, n, note) in bad.iter().take(12) {
        println!("   缺 {n:>3} 根  {}  {}", p.replace(std::path::MAIN_SEPARATOR, "/"), note);
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().collect();
    let tree = arg(&argv, "tree").unwrap_or_else(|| r"D:\TLGL\.scratch\out\tree".to_string());
    let out = arg(&argv, "out").unwrap_or_else(|| r"D:\TLGL\.scratch\hier_census.json".to_string());
    let mut files = Vec::new();
    walk(Path::new(&tree), &mut files);
    files.sort();

    if argv.iter().any(|a| a == "--stuck") {
        stuck_probe(&files);
        return;
    }
    if argv.iter().any(|a| a == "--corroborate") {
        corroborate(&files);
        return;
    }
    if argv.iter().any(|a| a == "--forest") {
        forest_probe(&files);
        return;
    }

    let mut buckets: BTreeMap<String, Bucket> = BTreeMap::new();
    let (mut ok, mut no_bones, mut unreadable, mut total) = (0usize, 0usize, 0usize, 0usize);

    for f in &files {
        total += 1;
        let raw = match std::fs::read(f) {
            Ok(r) => r,
            Err(_) => {
                unreadable += 1;
                continue;
            }
        };
        let rel = f.to_string_lossy().replace('\\', "/");
        let declared = match bone_count(&raw) {
            Some(n) if n > 0 => n,
            _ => {
                no_bones += 1;
                continue;
            }
        };
        let key = match hierarchy_try(&raw) {
            Ok(_) => {
                ok += 1;
                continue;
            }
            Err(e) => e.to_string(),
        };
        let b = buckets.entry(key).or_default();
        b.n += 1;
        b.declared_sum += declared as u64;
        b.size_sum += raw.len() as u64;
        if has_origin_record(&raw) {
            b.with_origin += 1;
        }
        if has_root_flag(&raw) {
            b.with_root_flag += 1;
        }
        if parse_mesh(&raw).is_err() {
            b.mesh_parse_fail += 1;
        }
        if b.samples.len() < 6 {
            b.samples.push(format!("{rel} (声明 {declared})"));
        }
        b.rows.push(format!("{rel}	{declared}	{}", raw.len()));
    }

    let mut lines = Vec::new();
    // 逐行明细：分桶只给量级，要再切一族（比如「声明 1 根的静态件」）得看逐行。
    let csv = buckets
        .iter()
        .flat_map(|(reason, b)| {
            b.rows.iter().map(move |r| format!("{reason}\t{r}"))
        })
        .collect::<Vec<_>>()
        .join("\n");
    let _ = std::fs::write(out.replace(".json", ".tsv"), format!("原因\t路径\t声明骨\t大小\n{csv}\n"));
    lines.push(format!(
        "树 {tree}\n.mesh 总数 {total} · 读不出 {unreadable} · 无骨架声明(0x110=0/读不出) {no_bones} · 解出 {ok}"
    ));
    lines.push(format!("解不出合计 {}", total - unreadable - no_bones - ok));
    let mut by_n: Vec<(&String, &Bucket)> = buckets.iter().collect();
    by_n.sort_by(|a, b| b.1.n.cmp(&a.1.n));
    for (reason, b) in &by_n {
        lines.push(format!(
            "\n【{reason}】 {} 份 · 平均声明骨 {:.1} · 平均大小 {} B · 有 origin 记录 {} · 有 -1 标志 {} · 网格本身解不出 {}",
            b.n,
            b.declared_sum as f64 / b.n.max(1) as f64,
            b.size_sum as f64 / b.n.max(1) as f64,
            b.with_origin,
            b.with_root_flag,
            b.mesh_parse_fail
        ));
        for s in &b.samples {
            lines.push(format!("   {s}"));
        }
    }
    let report = lines.join("\n");
    let _ = std::fs::write(&out, serde_json::to_string_pretty(&buckets).unwrap_or_default());
    let txt = out.replace(".json", ".txt");
    let _ = std::fs::write(&txt, &report);
    // 控制台是 cp936，中文会成乱码：屏幕上只报路径与两个数
    println!("WROTE {txt}\n合计 {total} · 解出 {ok} · 解不出 {}", total - unreadable - no_bones - ok);
}
