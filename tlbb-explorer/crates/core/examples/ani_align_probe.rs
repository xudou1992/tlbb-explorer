//! 对齐口径裁决：把 `.mesh` 的存储绑定矩阵当裁判，看 `.ani` 的第 i 条轨道/静态记录
//! 到底归骨架的第几根骨（δ=0 同名同序 / δ=1 整体后挪一根=改前读法），
//! 以及静态记录里绑定四元数在 +12 还是 +28。逐模型打印命中数，末尾给合计。
//!
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --release --example ani_align_probe -- ../../.scratch/dyn/probe_pairs.json
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{
    parse_hierarchy,
    rest::{align_best_delta, align_outliers, align_probe, align_residual_quat, min3_bind_offset_probe},
};

fn main() {
    let pairs_file = std::env::args()
        .nth(1)
        .unwrap_or_else(|| ".scratch/dyn/probe_pairs.json".to_string());
    let json = std::fs::read_to_string(&pairs_file).expect("配对文件读不到");
    // [[mesh_hash_hex, mesh_pak, ani_hash_hex, ani_pak], ...]（网格和动作可以不在同一个容器）
    let mut pairs: Vec<(u64, String, u64, String)> = Vec::new();
    for row in json
        .trim()
        .trim_start_matches('[')
        .trim_end_matches(']')
        .split("],")
    {
        let parts: Vec<&str> = row
            .trim()
            .trim_start_matches('[')
            .trim_end_matches('[')
            .trim_end_matches(']')
            .split(',')
            .map(|s| s.trim().trim_matches('"'))
            .collect();
        if parts.len() < 4 {
            continue;
        }
        if let (Ok(m), Ok(a)) = (
            u64::from_str_radix(parts[1], 16),
            u64::from_str_radix(parts[3], 16),
        ) {
            pairs.push((m, parts[0].to_string(), a, parts[2].to_string()));
        }
    }
    println!("配对 {} 组", pairs.len());

    let root = PathBuf::from("D:/TLGL");
    let mut paks: HashMap<String, Pak> = HashMap::new();
    // 合计：(δ,sub) -> (干净骨, 旋转命中, 平移命中, 参与模型数)
    let mut total: HashMap<(usize, usize), (usize, usize, usize, usize)> = HashMap::new();
    // 逐骨对账的交叉表：骨名形态 -> [无旋转值, 精确, ≈90~110°, ≥175°, 其它角度]
    let mut tab: HashMap<&'static str, [usize; 5]> = HashMap::new();
    let mut shift: HashMap<&'static str, usize> = HashMap::new();
    let mut buck: HashMap<usize, usize> = HashMap::new();
    let mut world_match: HashMap<&'static str, [usize; 3]> = HashMap::new();
    // (形态, 是否真的对上了) -> 根数；用来验「晚一格」是不是每根骨都成立
    let mut delta: HashMap<(&'static str, bool), usize> = HashMap::new();
    let mut dmap: HashMap<(&'static str, isize), usize> = HashMap::new();
    let mut resid: HashMap<(&'static str, i32, char, i8), usize> = HashMap::new();
    let mut pairs_ok = 0usize;

    for (mh, mpk, ah, apk) in &pairs {
        for name in [mpk, apk] {
            if !paks.contains_key(name) {
                if let Ok(p) = Pak::open(root.join(format!("{name}.pak"))) {
                    paks.insert(name.clone(), p);
                }
            }
        }
        let Some(mp) = paks.get(mpk) else { continue };
        let Some(ap) = paks.get(apk) else { continue };
        // 路径哈希会跨容器撞名，所以两条都必须在各自容器里查得到
        let Some(rec) = mp.records().find(|r| r.hash == *mh && r.stored > 0) else {
            continue;
        };
        let mesh = payload::decode(mp, &rec).map(|d| d.bytes).ok();
        let Some(rec2) = ap.records().find(|r| r.hash == *ah && r.stored > 0) else {
            continue;
        };
        let ani = payload::decode(ap, &rec2).map(|d| d.bytes).ok();
        let (Some(mesh), Some(ani)) = (mesh, ani) else { continue };
        let Some(h) = parse_hierarchy(&mesh) else { continue };
        for (name, ang, ax, sgn) in align_residual_quat(&ani, &h) {
            let sh = shape(&name);
            if ang >= 0.5 {
                let bucket = (ang / 15.0).floor() as i32 * 15;
                *resid.entry((sh, bucket, ax, sgn)).or_insert(0) += 1;
            }
        }
        for (name, di, rot, dist) in align_best_delta(&ani, &h, 3) {
            let good = rot < 0.5 && dist < 1e-3;
            let sh = shape(&name);
            if good {
                *dmap.entry((sh, di)).or_insert(0) += 1;
            }
            *delta.entry((sh, good)).or_insert(0) += 1;
        }
        let ol = align_outliers(&ani, &h);
        for (name, d, r, dw, rw) in &ol {
            let bucket = if !r.is_finite() { 0 } else if *r < 0.5 { 1 } else if (85.0..=115.0).contains(r) { 2 } else if *r >= 175.0 { 3 } else { 4 };
            let row = shape(name);
            let e = tab.entry(row).or_insert([0usize; 5]);
            e[bucket] += 1;
            if *d > 0.05 {
                *shift.entry(row).or_insert(0) += 1;
            }
            *buck.entry(bucket).or_insert(0) += 1;
            // 对不上局部的那批，改比对「世界」口径：对上了就说明它压根没沿父链复合
            let w = world_match.entry(row).or_insert([0usize; 3]);
            if *r >= 0.5 {
                w[0] += 1;
                if *rw < 0.5 && *dw < 1e-3 {
                    w[1] += 1;
                }
            }
            if *r < 0.5 {
                w[2] += 1;
            }
        }
        let p3 = min3_bind_offset_probe(&ani, &h);
        if !p3.is_empty() {
            println!("  静态记录里等于绑定局部平移的子偏移：{}", p3.iter().map(|(s,c,hh)| format!("+{s}={hh}/{c}")).collect::<Vec<_>>().join("  "));
        }
        pairs_ok += 1;
        let got = align_probe(&ani, &h);
        if got.is_empty() {
            continue;
        }
        let tag = ani.get(0x8c..0x90).map(|s| String::from_utf8_lossy(s).into_owned()).unwrap_or_default();
        print!("  {apk}/{mpk} {tag} 骨架 {} 根：", h.bones.len());
        for (d, sub, clean, rot, tr) in &got {
            print!("δ{d}+{sub}={rot}/{tr}/{clean}  ");
            let e = total.entry((*d, *sub)).or_default();
            e.0 += clean;
            e.1 += rot;
            e.2 += tr;
            e.3 += 1;
        }
        println!();
    }

    let mut rk: Vec<(&'static str, i32, char, i8)> = resid.keys().cloned().collect();
    rk.sort();
    println!("残差旋转（对不上的那些，15° 一档 · 主轴 · 符号）→ 根数：");
    for k in rk {
        if resid[&k] >= 3 {
            println!("  {:12} {:4}° 轴 {}{}  {:4} 根", k.0, k.1, if k.3 > 0 { '+' } else { '-' }, k.2, resid[&k]);
        }
    }
    // 每根骨自由找最对的轨道偏移：按形态统计「对上」的骨都落在哪个偏移上
    println!("自由找最优轨道偏移（窗口 ±3）—— 形态：偏移→根数（只统计对上的）");
    let mut shapes: Vec<&'static str> = delta.keys().map(|k| k.0).collect();
    shapes.sort();
    shapes.dedup();
    for sh in shapes {
        let mut line = format!("  {:12}", sh);
        for d in -3isize..=3isize {
            let c = *dmap.get(&(sh, d)).unwrap_or(&0);
            if c > 0 {
                line += &format!("  δ{:+}={}", d, c);
            }
        }
        let bad = *delta.get(&(sh, false)).unwrap_or(&0);
        println!("{}   （对不上 {} 根）", line, bad);
    }
    if !tab.is_empty() {
        let mut names: Vec<&&'static str> = tab.keys().collect();
        names.sort();
        println!(
            "逐骨对账交叉表（{} 份资产、{} 根骨）：形态 → 精确 / ≈90~110° / ≥175° / 其它 / 其中位移也差>0.05",
            pairs_ok,
            tab.values().map(|v| v.iter().sum::<usize>()).sum::<usize>()
        );
        for k in names {
            let v = tab[k];
            println!(
                "  {:12} 精确 {:6}  90~110° {:5}  ≥175° {:5}  其它 {:6}  位移差 {:6}  对不上局部里改对上世界的 {:4}",
                k,
                v[1],
                v[2],
                v[3],
                v[4],
                shift.get(k).copied().unwrap_or(0),
                world_match.get(k).copied().unwrap_or([0; 3])[1]
            );
        }
    }
    let mut ks: Vec<(usize, usize)> = total.keys().cloned().collect();
    ks.sort();
    println!("合计（旋转命中/平移命中 占干净骨数，参与模型数）：");
    for k in ks {
        let t = total[&k];
        println!(
            "  δ{} 静态四元数+{:2} → 旋转 {:6}/{}  平移 {:6}/{}  模型 {} 个",
            k.0,
            k.1,
            t.1,
            t.0,
            t.2,
            t.0,
            t.3
        );
    }
}

/// 骨名形态分组：看整角度对不上是不是集中在某一类骨（`pelvis`/脊柱/四肢/`boneNN`/镜像对）。
fn shape(name: &str) -> &'static str {
    let n = name.to_ascii_lowercase();
    if n.contains("footsteps") {
        return "footsteps";
    }
    if n.contains("pelvis") {
        return "pelvis";
    }
    if n.contains("spine") {
        return "spine";
    }
    if n.contains("neck") || n.contains("head") {
        return "neck/head";
    }
    if n.contains("clavicle") {
        return "clavicle";
    }
    if n.contains("upperarm") {
        return "upperarm";
    }
    if n.contains("forearm") {
        return "forearm";
    }
    if n.contains("hand") {
        return "hand";
    }
    if n.contains("thigh") || n.contains("calf") || n.contains("foot") {
        return "leg";
    }
    if n.contains("mirror") {
        return "镜像对";
    }
    if n.starts_with("bone") {
        return "boneNN";
    }
    "其它"
}
