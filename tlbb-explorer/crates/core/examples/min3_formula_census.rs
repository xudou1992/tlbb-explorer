//! 全库验一条闭式：MIN3 的标志区起点 = `0xD2 + 78×骨数`（骨数取 0xBA，标志条数取 0xBE）。
//!
//! 起因：现在用「名表 30B + 静态区 44B + 扫 ≤640 字节的定长块」找标志区，
//! 块长随骨数线性增长（57 骨→200、182 骨→700、189 骨→728），超过 640 就找不到 ⇒ 误判「结构不成立」。
//! 闭式在 5 份样本上（含 2 骨 / 25 骨 / 57 骨 / 182 骨 / 189 骨）都精确命中。
//! 这份普查要的是**全库分母**：2,522 份 MIN3 里有多少份按闭式正好收在文件尾，剩下的差多少。
//!
//! 只读：db、pak 全部只读打开，不落资源字节。
//! 用法（在 crates/core 下）：
//! ```text
//! cargo run --offline --example min3_formula_census
//! ```

use std::collections::HashMap;
use std::path::PathBuf;

use rusqlite::{Connection, OpenFlags};
use tlbb_core::jpak::Pak;
use tlbb_core::payload;
use tlbb_core::preview::{ani_min3_landing, parse_ani, parse_ani_header};

fn main() {
    let root = std::env::var("TLBB_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| PathBuf::from("D:/TLGL"));
    let db = std::env::var("TLBB_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join(".scratch/resources.db"));
    let con = Connection::open_with_flags(
        &db,
        OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
    )
    .expect("资源清单打不开");

    let mut rows: Vec<(u64, String)> = Vec::new();
    {
        let mut st = con
            .prepare("SELECT hash, coalesce(pak,'') FROM resources WHERE name LIKE '%.ani' AND coalesce(pak,'') <> ''")
            .unwrap();
        let it = st
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .unwrap();
        for row in it.flatten() {
            if let Ok(h) = u64::from_str_radix(&row.0, 16) {
                rows.push((h, row.1));
            }
        }
    }

    let mut paks: HashMap<String, Pak> = HashMap::new();
    let mut min3 = 0usize;
    let mut now_ok = 0usize; // 现口径 parse_ani 认下的
    // 名表基址 / 绑定旋转子偏移的普查
    let mut name_files = 0usize; // 每条名都可读（0xD2 起 30B）
    let mut name_bones = (0usize, 0usize); // (可读名条数, 总条数)
    let mut ee_bones = (0usize, 0usize); // 对照：现代码基址 0xEE 的可读名条数
    let mut quat_all_files = 0usize; // 整份每骨单位长（静态区 +28）
    let mut quat_bones = (0usize, 0usize); // (单位长条数, 总条数)
    let mut quat_at0_bones = (0usize, 0usize); // 对照：现在代码读的 +0
    // 闭式落点分桶
    let mut hit_bones2 = 0usize; // 正好收尾（标志条数=0xBE）
    // 索引表（骨 → 通道块号）统计：这次修复的影响面
    let mut idx_files = 0usize; // 表能按「0..块数-1 + 哨兵」解释的份数
    let mut idx_sentinel_files = 0usize; // 有哨兵（骨数 > 块数）的份数
    let mut idx_sentinels = 0usize; // 哨兵总条数
    let mut idx_bones_shift = 0usize; // 非恒等（按骨序顺序取块会错位）的份数
    let mut idx_bad = 0usize; // 表读不出合法映射的份数
    let mut hit_bones = 0usize; //  正好收尾（标志条数=0xBA）
    let mut hit_both = 0usize;
    let mut no_walk = 0usize; // 走一遍就崩（越界/计数不合法）
    let mut miss_hist: HashMap<i64, usize> = HashMap::new(); // 差多少字节
    let mut examples: Vec<String> = Vec::new();
    let mut bone_hist: HashMap<usize, usize> = HashMap::new(); // 失败样本的骨数分布

    for (hash, pak_name) in &rows {
        if !paks.contains_key(pak_name) {
            if let Ok(p) = Pak::open(root.join(format!("{pak_name}.pak"))) {
                paks.insert(pak_name.clone(), p);
            }
        }
        let Some(p) = paks.get(pak_name) else { continue };
        let Some(rec) = p.records().find(|r| r.hash == *hash && r.stored > 0) else {
            continue;
        };
        let Ok(raw) = payload::decode(p, &rec) else { continue };
        let bytes = raw.bytes;
        if bytes.get(0x8c..0x90) != Some(&b"MIN3"[..]) {
            continue;
        }
        min3 += 1;
        if parse_ani(&bytes).is_some() {
            now_ok += 1;
        }
        let Some(h) = parse_ani_header(&bytes) else {
            miss_hist.entry(-9999).and_modify(|c| *c += 1).or_insert(1);
            continue;
        };
        let flags_at = 0xd2usize.saturating_add(78usize.saturating_mul(h.bones));
        // 名表基址（现代码写 0xEE）与静态区绑定旋转的子偏移（现代码写 +0）一并普查。
        let f32s = |o: usize, n: usize| -> Option<Vec<f32>> {
            let s = bytes.get(o..o + 4 * n)?;
            Some((0..n).map(|k| f32::from_le_bytes([s[4 * k], s[4 * k + 1], s[4 * k + 2], s[4 * k + 3]])).collect())
        };
        let unit = |o: usize| -> bool {
            f32s(o, 4).map(|q| ((q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]).sqrt() - 1.0).abs() < 0.02)
                .unwrap_or(false)
        };
        let static_at = 0xd2usize + 30 * h.bones;
        let mut nm_ok = 0usize;
        let mut nm_ee = 0usize;
        let mut q28 = 0usize;
        let mut q0 = 0usize;
        for i in 0..h.bones {
            if let Some(slot) = bytes.get(0xd2 + i * 30..0xd2 + i * 30 + 30) {
                let end = slot.iter().position(|&c| c == 0).unwrap_or(30);
                if end > 0 && slot[..end].iter().all(|c| (0x20..0x7f).contains(c)) {
                    nm_ok += 1;
                }
            }
            // 对照：现代码的名表基址 0xEE（比 0xD2 晚 28 字节，落在名槽尾部）
            if let Some(slot) = bytes.get(0xee + i * 30..0xee + i * 30 + 30) {
                let end = slot.iter().position(|&c| c == 0).unwrap_or(30);
                if end > 0 && slot[..end].iter().all(|c| (0x20..0x7f).contains(c)) {
                    nm_ee += 1;
                }
            }
            let o = static_at + i * 44;
            if unit(o + 28) {
                q28 += 1;
            }
            if unit(o) {
                q0 += 1;
            }
        }
        name_bones.0 += nm_ok;
        name_bones.1 += h.bones;
        ee_bones.0 += nm_ee;
        ee_bones.1 += h.bones;
        if nm_ok == h.bones && h.bones > 0 {
            name_files += 1;
        }
        quat_bones.0 += q28;
        quat_bones.1 += h.bones;
        quat_at0_bones.0 += q0;
        quat_at0_bones.1 += h.bones;
        if q28 == h.bones && h.bones > 0 {
            quat_all_files += 1;
        }
        {
            let bones = h.bones as usize;
            let flag_n = (h.bones2 as usize).min(bones);
            let at = 0xd2 + bones * (30 + 44);
            let vals: Vec<u32> = (0..bones)
                .filter_map(|j| {
                    let b = bytes.get(at + j * 4..at + j * 4 + 4)?;
                    Some(u32::from_le_bytes(b.try_into().ok()?))
                })
                .collect();
            if vals.len() == bones {
                let sent = vals.iter().filter(|v| **v > 0xFFFF_0000).count();
                let real: Vec<u32> = vals.iter().cloned().filter(|v| *v <= 0xFFFF_0000).collect();
                let ok = real.len() == flag_n && real.iter().enumerate().all(|(k, v)| *v == k as u32);
                if ok {
                    idx_files += 1;
                    if sent > 0 {
                        idx_sentinel_files += 1;
                        idx_sentinels += sent;
                    }
                    // 第一个哨兵之前的骨是恒等，之后整体后移 ⇒ 顺序取块就错位
                    if vals.iter().enumerate().any(|(j, v)| *v != j as u32) {
                        idx_bones_shift += 1;
                    }
                } else {
                    idx_bad += 1;
                }
            } else {
                idx_bad += 1;
            }
        }
        let l2 = ani_min3_landing(&bytes, flags_at, h.bones2, h.frames);
        let l1 = if h.bones == h.bones2 { None } else { ani_min3_landing(&bytes, flags_at, h.bones, h.frames) };
        match l2 {
            Some(0) => {
                if l1 == Some(0) {
                    hit_both += 1;
                } else {
                    hit_bones2 += 1;
                }
            }
            Some(d) => {
                if l1 == Some(0) {
                    hit_bones += 1;
                    continue;
                }
                if d.abs() > 4096 {
                    // 越界/离谱的差值多半是走崩了，单独记
                    miss_hist.entry(9999).and_modify(|c| *c += 1).or_insert(1);
                } else {
                    miss_hist.entry(d).and_modify(|c| *c += 1).or_insert(1);
                }
                *bone_hist.entry(h.bones).or_insert(0) += 1;
                if examples.len() < 12 {
                    examples.push(format!(
                        "{hash:016x} 骨={} 标志={} 帧={} 大小={} 闭式 flags@{} 差={}",
                        h.bones, h.bones2, h.frames, bytes.len(), flags_at, d
                    ));
                }
            }
            None => {
                if l1 == Some(0) {
                    hit_bones += 1;
                    continue;
                }
                no_walk += 1;
                *bone_hist.entry(h.bones).or_insert(0) += 1;
                if examples.len() < 12 {
                    examples.push(format!(
                        "{hash:016x} 骨={} 标志={} 帧={} 大小={} 闭式 flags@{} 走崩",
                        h.bones, h.bones2, h.frames, bytes.len(), flags_at
                    ));
                }
            }
        }
    }

    println!(
        "索引表：可解释 {idx_files}/{min3} · 有哨兵 {idx_sentinel_files} 份（共 {idx_sentinels} 条）
            · 顺序取块会错位的 {idx_bones_shift} 份 · 读不出合法映射的 {idx_bad} 份"
    );
    println!(
        "MIN3 全库 {min3} 份 · 现口径解出 {now_ok} · 闭式正好收尾：标志条数=0xBE {hit_bones2} · 0xBE/0xBA 都行 {hit_both} · 只有 0xBA {hit_bones}"
    );
    println!(
        "            对不上的：走崩 {no_walk} · 落点有差 {}",
        min3 - hit_bones2 - hit_both - hit_bones - no_walk
    );
    let mut hs: Vec<(i64, usize)> = miss_hist.into_iter().collect();
    hs.sort_by_key(|(d, _)| d.abs());
    println!(
        "        差值分布（字节，前 12 桶）：{}",
        hs.iter()
            .take(12)
            .map(|(d, c)| format!("{d}×{c}"))
            .collect::<Vec<_>>()
            .join("  ")
    );
    let mut bh: Vec<(usize, usize)> = bone_hist.into_iter().collect();
    bh.sort_by_key(|(b, _)| *b);
    println!(
        "        对不上样本的骨数分布：{}",
        bh.iter()
            .take(20)
            .map(|(b, c)| format!("{b}骨×{c}"))
            .collect::<Vec<_>>()
            .join("  ")
    );
    for e in examples {
        println!("        eg {e}");
    }
    println!(
        "名表基址 0xD2：整份每条名都可读的份数 {name_files}/{min3} · 逐条 {}/{}；\
         对照现代码的 0xEE：逐条 {}/{}",
        name_bones.0, name_bones.1, ee_bones.0, ee_bones.1
    );
    println!(
        "静态区 44B/骨：绑定旋转在 +28 时单位长 {}/{} 条（整份全对的份数 {quat_all_files}/{min3}）；\
         对照现代码读的 +0：{}/{} 条",
        quat_bones.0, quat_bones.1, quat_at0_bones.0, quat_at0_bones.1
    );
}
