//! `.scene` 地图坐标契约测试 —— 把 `contracts/map_coordinate_contract.md`「已证实」表里
//! **可离线钉死**的条目变成常驻闸门，防止解析口径或理解悄悄漂移。
//!
//! # 这组测试钉什么、不钉什么
//!
//! **钉**（2026-10-05 全量审计，284,999 条实例 / 10,379 个可解文件 / 302 张图，
//! 数字见 `.scratch/coord_full_audit.txt` 与 `coord_stats3.txt`）：
//!
//! 1. **齐次末行恒 `(0,0,0,1)`**——精确等于，0 容差（全量 0 违反，且是判据 M 本身）。
//! 2. **旋转块正交**——三列两两 |cos| ≤ 1e-3（全量 0 违反）；可逆（|det| > 0，
//!    全量仅 2 条全零旋转块退化实例，样本里刻意不含）。
//! 3. **纯偏航占比 ≥ 0.90**（全量实测 90.48%；样本池实测 97.3%，留了余量）。
//! 4. **上轴偏离 ≤ 1° 的占比 ≥ 0.85**（+Y 的像与 Y 轴夹角；全量实测 90.84%，
//!    样本池 97.3%。俯仰/翻滚是真实数据行为，不钉死为 0）。
//! 5. **32 单位/格**——`floor(m[12]/32)==文件名第2段`、`floor(m[14]/32)==第3段`，
//!    样本池吻合率 ≥ 0.98（全量 99.99965%；样本刻意含已知的 1 条跨界实例）。
//! 6. **逐实例缩放非恒 1**——缩放取列范数，样本池里必须出现 ≠1 与三轴不一致的实例
//!    （全量：83.4% 三轴一致，16.6% 独立缩放，多为墙面/地砖类；恒 1 的说法已被全量推翻）。
//!
//! **不钉**（离线判不了，红线在契约文档「待客户端比对」）：
//! - R / Rᵀ（偏航符号/行向量 vs 列向量）——本文件所有断言对转置不敏感，刻意如此。
//! - 世界原点绝对位置——格号吻合只钉相对关系。
//!
//! # 样本
//!
//! `tests/scene_samples/`（.gitignore 刻意排除，客户端原始字节不入库——见仓库根
//! .gitignore 与 README「测试夹具」）。缺席时逐条跳过；有样本就必须跑出实质断言。
//!
//! 命名约定：
//! - `grid_<tag>.scene` —— 形态样本（tag 覆盖 324/596/601/592/605/749/753）。
//! - `<地图名>__<格号>.scene` —— 真名格子样本，`__` 后面是**客户端原样格号**
//!   （如 `1_-1_-6`），只有这类文件参与第 5 条格号断言。
//!
//! 阈值出处（改阈值必须先重跑全量审计拿新数）：
//! - `.scratch/coord_full_audit.py` → coord_full_audit.json/.txt（全量主表）
//! - `.scratch/coord_stats3.py`     → coord_stats3.json/.txt（上轴偏离/分位数）
//! - `.scratch/coord_tag_census.py` → coord_tag_census.json/.txt（tag 分布）

use std::path::PathBuf;

use tlbb_core::preview::scene::parse_scene;

/// 上轴偏离角（度）：列 1（+Y 轴的像）与 Y 轴的夹角。
/// 纯偏航下恒为 0；俯仰/翻滚把它推开——它是「Y-up + 俯仰程度」的联合读数。
fn up_axis_deviation_deg(m: &[f32; 16]) -> f32 {
    let sy = (m[4] * m[4] + m[5] * m[5] + m[6] * m[6]).sqrt();
    if sy <= 0.0 {
        return 90.0;
    }
    let c = (m[5].abs() / sy).clamp(-1.0, 1.0);
    c.acos().to_degrees()
}

fn col_norm(m: &[f32; 16], c: usize) -> f32 {
    (m[c] * m[c] + m[c + 1] * m[c + 1] + m[c + 2] * m[c + 2]).sqrt()
}

fn det3(m: &[f32; 16]) -> f32 {
    m[0] * (m[5] * m[10] - m[6] * m[9]) - m[1] * (m[4] * m[10] - m[6] * m[8])
        + m[2] * (m[4] * m[9] - m[5] * m[8])
}

/// 两列夹角的 |cos|。全量 284,999 条无一超过 1e-3（正交性）。
fn abs_cos_between(m: &[f32; 16], c1: usize, c2: usize) -> f32 {
    let n1 = col_norm(m, c1);
    let n2 = col_norm(m, c2);
    if n1 == 0.0 || n2 == 0.0 {
        return 0.0;
    }
    (m[c1] * m[c2] + m[c1 + 1] * m[c2 + 1] + m[c1 + 2] * m[c2 + 2]).abs() / (n1 * n2)
}

fn scene_samples_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/scene_samples")
}

/// 把样本池整体载入。返回 (文件名, parse 结果) 列表——解析失败即 panic（样本是
/// 挑过的真文件，解不出来说明解析器坏了，不是样本坏了）。
fn load_samples() -> Vec<(String, tlbb_core::preview::scene::SceneGrid)> {
    let dir = scene_samples_dir();
    let mut out = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&dir) {
        let mut names: Vec<String> = entries
            .flatten()
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.ends_with(".scene"))
            .collect();
        names.sort();
        for name in names {
            let raw = std::fs::read(dir.join(&name)).expect("样本读取失败");
            let g = parse_scene(&raw)
                .unwrap_or_else(|e| panic!("样本 {name} 应能解析，实际 {e:?}（解析器坏了）"));
            out.push((name, g));
        }
    }
    out
}

/// 契约 1+2（逐实例硬断言）：齐次末行精确 (0,0,0,1)、平移恰在 m[12..15]、
/// 旋转块正交、列范数 sane（全量实测最大 5.648，取 10 上限）、可逆。
#[test]
fn 契约_齐次末行与正交性与可逆性_逐实例硬断言() {
    let samples = load_samples();
    assert!(
        !samples.is_empty(),
        "scene_samples/ 无样本（夹具不入库）：拷入样本后本测试才有意义"
    );

    let mut checked = 0usize;
    for (name, g) in &samples {
        assert_eq!(
            g.stride,
            g.tag as usize + 8,
            "{name}: stride 必须等于 tag+8"
        );
        assert!(!g.understated, "{name}: understated 全库 0 例，不得为 true");
        for (idx, inst) in g.instances.iter().enumerate() {
            let m = &inst.matrix;
            let at = |what: &str, cond: bool| {
                assert!(cond, "{name} 第 {idx} 条 {} 违反齐次末行契约", what);
            };
            at("m[3]", m[3] == 0.0);
            at("m[7]", m[7] == 0.0);
            at("m[11]", m[11] == 0.0);
            at("m[15]", m[15] == 1.0);
            assert_eq!(
                inst.position,
                [m[12], m[13], m[14]],
                "{name} 第 {idx} 条: position 必须就是 m[12..15]（列主序直读）"
            );
            for (c1, c2) in [(0usize, 4usize), (0, 8), (4, 8)] {
                let cos = abs_cos_between(m, c1, c2);
                assert!(
                    cos <= 1e-3,
                    "{name} 第 {idx} 条: 列 {c1} 与列 {c2} |cos|={cos}，正交性被破坏"
                );
            }
            for c in [0usize, 4, 8] {
                let n = col_norm(m, c);
                assert!(
                    n > 0.0 && n <= 10.0,
                    "{name} 第 {idx} 条: 列 {c} 范数 {n} 越界 (0,10]——全量最大 5.648"
                );
            }
            let d = det3(m);
            assert!(
                d.abs() > 1e-9,
                "{name} 第 {idx} 条: |det|={d} 近零（全量仅 2 条全零旋转块，样本不该含）"
            );
            checked += 1;
        }
    }
    assert!(checked > 0, "样本池一条实例都没跑到");
    eprintln!("契约1+2：逐实例硬断言通过，共 {checked} 条");
}

/// 契约 3+4（分布下限）：纯偏航占比 ≥ 0.90、上轴偏离 ≤1° 占比 ≥ 0.85。
/// 全量实测：90.48% / 90.84%；样本池实测：97.3% / 97.3%。阈值取全量实测再留余量。
#[test]
fn 契约_纯偏航与上轴占比_不低于全量实测下限() {
    let samples = load_samples();
    assert!(!samples.is_empty(), "scene_samples/ 无样本，跳过依据不足");

    let mut n = 0usize;
    let mut pure_yaw = 0usize;
    let mut up_ok = 0usize;
    for (name, g) in &samples {
        for inst in &g.instances {
            let m = &inst.matrix;
            n += 1;
            if m[1] == 0.0 && m[4] == 0.0 && m[6] == 0.0 && m[9] == 0.0 {
                pure_yaw += 1;
            }
            if up_axis_deviation_deg(m) <= 1.0 {
                up_ok += 1;
            }
        }
        eprintln!(
            "  {name}: tag={} n={} has_tail={}",
            g.tag,
            g.instances.len(),
            g.has_tail
        );
    }
    assert!(n >= 50, "样本池只有 {n} 条，占比断言无意义（样本不全？）");
    let pure_ratio = pure_yaw as f64 / n as f64;
    let up_ratio = up_ok as f64 / n as f64;
    eprintln!(
        "契约3+4：纯偏航 {pure_yaw}/{n} = {:.2}%（≥90%）；上轴偏离≤1° {up_ok}/{n} = {:.2}%（≥85%）",
        pure_ratio * 100.0,
        up_ratio * 100.0
    );
    assert!(
        pure_ratio >= 0.90,
        "纯偏航占比 {pure_ratio:.4} 低于全量实测下限 0.90——解析口径或样本变了，先重跑全量审计"
    );
    assert!(
        up_ratio >= 0.85,
        "上轴偏离≤1° 占比 {up_ratio:.4} 低于全量实测下限 0.85——同上"
    );
}

/// 契约 5（32 单位/格）：`<地图名>__<格号>.scene` 样本按文件名格号逐条对照
/// `floor(m[12]/32)` / `floor(m[14]/32)`，池内吻合率 ≥ 0.98。
/// 全量实测 284,998/284,999 = 99.99965%；样本池刻意含已知的 1 条跨界实例
/// （w1351_fb_songliao_001 格 `1_-1_-6` 的石灯塔，z 落在邻格 -7）。
#[test]
fn 契约_32格号与文件名吻合() {
    let samples = load_samples();
    let grid_samples: Vec<_> = samples
        .iter()
        .filter(|(name, _)| name.contains("__"))
        .collect();
    assert!(
        !grid_samples.is_empty(),
        "无 <地图名>__<格号>.scene 样本，格号契约没跑到"
    );

    let mut ok = 0usize;
    let mut total = 0usize;
    let mut misses: Vec<String> = Vec::new();
    for (name, g) in &grid_samples {
        let grid_part = name.split("__").nth(1).expect("含 __ 才进到这里");
        let grid_part = grid_part.trim_end_matches(".scene");
        let segs: Vec<i64> = grid_part
            .split('_')
            .map(|s| s.parse::<i64>().expect("格号段必须是整数"))
            .collect();
        assert_eq!(segs.len(), 3, "{name}: 格号应为 3 段");
        for (idx, inst) in g.instances.iter().enumerate() {
            total += 1;
            let gx = (inst.position[0] / 32.0).floor() as i64;
            let gz = (inst.position[2] / 32.0).floor() as i64;
            if gx == segs[1] && gz == segs[2] {
                ok += 1;
            } else {
                misses.push(format!(
                    "{name} 第 {idx} 条: floor(x/32)={gx} floor(z/32)={gz} vs 格号 ({}, {})",
                    segs[1], segs[2]
                ));
            }
        }
    }
    assert!(total >= 50, "格号样本只有 {total} 条，占比断言无意义");
    let ratio = ok as f64 / total as f64;
    eprintln!(
        "契约5：格号吻合 {ok}/{total} = {:.4}%（阈值 ≥98%；全量 99.99965%）",
        ratio * 100.0
    );
    for m in &misses {
        eprintln!("  已知跨界实例: {m}");
    }
    assert!(
        ratio >= 0.98,
        "格号吻合率 {ratio:.4} 低于 0.98——格子尺寸或坐标语义变了，先重跑全量审计"
    );
}

/// 契约 6（缩放非恒 1，且允许三轴独立）：大理样本 `w1351_ll_dl_002__1_1_-5.scene`
/// 里 75 条中 22 条三轴不一致（全量 16.6%，多为墙面/地砖类）——这钉住两件事：
/// ① 缩放逐实例存在（不是恒 1）；② 「逐实例统一缩放」的旧说法不成立，三轴独立
/// 是真实数据行为，渲染管线不得假设 sx==sy==sz。
#[test]
fn 契约_缩放逐实例存在且允许三轴独立() {
    let samples = load_samples();
    let fence = samples
        .iter()
        .find(|(name, _)| name == "w1351_ll_dl_002__1_1_-5.scene");
    let Some((name, g)) = fence else {
        eprintln!("大理样本缺席，契约 6 退化为池内存在性检查");
        let mut any_non_unit = false;
        for (_, g) in &samples {
            for inst in &g.instances {
                if (inst.matrix[5] - 1.0).abs() > 1e-3 {
                    any_non_unit = true;
                }
            }
        }
        assert!(any_non_unit, "样本池里全部 m[5]==1，与「逐实例缩放」矛盾");
        return;
    };

    let mut non_unit = 0usize;
    let mut non_uniform = 0usize;
    for inst in &g.instances {
        let sx = col_norm(&inst.matrix, 0);
        let sy = col_norm(&inst.matrix, 4);
        let sz = col_norm(&inst.matrix, 8);
        if (sy - 1.0).abs() > 1e-3 {
            non_unit += 1;
        }
        let mx = sx.max(sy).max(sz);
        let mn = sx.min(sy).min(sz);
        if mx > 0.0 && mx - mn > 1e-3 * mx {
            non_uniform += 1;
        }
    }
    eprintln!(
        "契约6：{name} 共 {} 条，m[5]≠1 有 {non_unit} 条，三轴不一致 {non_uniform} 条",
        g.instances.len()
    );
    assert!(
        non_unit > 0,
        "{name}: 全部实例 m[5]==1，与「逐实例缩放、不是恒 1」矛盾"
    );
    assert!(
        non_uniform > 0,
        "{name}: 全部实例三轴一致——若这是真的，说明样本被换过，须重跑全量审计再改阈值"
    );
}

/// tag 白名单钉死：样本池覆盖 7 个实例表 tag（957 是水参数容器，不是物件清单，
/// 见 scene.rs 模块文档，不放样本）。tag 集合变了必须先过全量普查
/// （`.scratch/coord_tag_census.py`，2026-10-05 全量复扫：已知集合外只有
/// 295 个版权头文件 tag=1751607666，没有新实例表 tag）。
#[test]
fn 契约_tag白名单与样本覆盖() {
    let samples = load_samples();
    assert!(!samples.is_empty(), "scene_samples/ 无样本");
    let mut seen = std::collections::BTreeSet::new();
    for (name, g) in &samples {
        assert!(
            tlbb_core::preview::scene::known_version(g.tag),
            "{name}: tag {} 不在白名单", g.tag
        );
        assert_ne!(g.tag, 957, "{name}: 957 是水参数容器，不该作为样本出现");
        seen.insert(g.tag);
    }
    for t in [324u32, 596, 601, 592, 605, 749, 753] {
        assert!(seen.contains(&t), "样本池缺 tag={t} 的形态样本：{seen:?}");
    }
}
