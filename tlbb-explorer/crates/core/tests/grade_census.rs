//! 13,080 基线的等级分布冻结。
//!
//! 「Signals 统一」之后，工作台与基线共用同一套 `EvidenceFacts` → `grade()` 归约，
//! 全库只该有一个答案。本文件把那个答案钉住：谁改了评分规则、动了 `texture_refs`
//! 的口径、或换了一套会改变等级的库，这里就红。
//!
//! **这不是脆，这是冻结的本意。** 数字要变只有两条正路：
//!
//! 1. 重新扫描 / 重建 `resources.db` 后，跑 `catalog_baseline --json`，把新分布
//!    人工确认后写回下面的常量；
//! 2. 评分规则本身修订（例如 D 轴的判定改变），此时应当先改 `evidence.rs` 的
//!    文档，再让本测试红掉，最后带着新基线一起改这里的常量。
//!
//! 真实库不在时全部跳过 —— 和 `refs_audit` 一样，这是对**数据**立的规矩。
//! 只读打开；评分轴声明 `Decode::Unmeasured`，与基线完全同口径。

use std::path::Path;

use tlbb_core::catalog::{Catalog, Decode, EvidenceFacts, Grade};

const DB: &str = "D:/TLGL/.scratch/resources.db";

/// 2026-09-22 冻结值。来源：`catalog_baseline`（A20/B2581/C10479）与工作台
/// `--probe`（A20/B2581/C10479/D0）同库双跑一致；Python 直连 SQLite 复算亦一致。
const FROZEN_GROUPS: usize = 13_080;
const FROZEN: [(Grade, usize); 3] =
    [(Grade::A, 20), (Grade::B, 2_581), (Grade::C, 10_479)];

fn cat() -> Option<Catalog> {
    if !Path::new(DB).exists() {
        eprintln!("skip: {DB} 不存在");
        return None;
    }
    match Catalog::open_ro(DB) {
        Ok(c) => Some(c),
        Err(e) => {
            eprintln!("skip: 无法只读打开 {DB}: {e}");
            None
        }
    }
}

/// 全库逐组评分，走与基线 / 工作台完全相同的归约路径。
fn census(c: &Catalog) -> Vec<(Grade, usize)> {
    use std::collections::BTreeMap;
    let groups = c.groups(50_000).expect("读取资源组");
    let mut m: BTreeMap<String, usize> = BTreeMap::new();
    for g in &groups {
        let members = c.members(g.id).unwrap_or_default();
        let (tex_total, tex_located) = c.texture_refs(g.id).unwrap_or((0, 0));
        let facts = EvidenceFacts {
            hub_decoded: Decode::Unmeasured,
            roles: members.iter().map(|x| x.role.clone()).collect(),
            members: members.len(),
            refs_total: tex_total,
            refs_located: tex_located,
        };
        *m.entry(facts.grade().label().chars().next().unwrap().to_string())
            .or_default() += 1;
    }
    // 按冻结常量的顺序输出（A/B/C），缺的档记 0。
    FROZEN
        .iter()
        .map(|(g, _)| {
            let key = g.label().chars().next().unwrap().to_string();
            (*g, m.remove(&key).unwrap_or(0))
        })
        .collect()
}

#[test]
fn frozen_grade_distribution_holds() {
    let Some(c) = cat() else { return };
    let totals = c.totals().unwrap_or_default();
    assert_eq!(
        totals.groups, FROZEN_GROUPS,
        "资源组总数变了 —— 基线已过期，重跑 catalog_baseline 并更新 FROZEN 常量"
    );

    let got = census(&c);
    for ((grade, want), (_, have)) in FROZEN.iter().zip(got.iter()) {
        assert_eq!(
            have, want,
            "等级 {grade:?} 分布漂移：期望 {want}，实测 {have}。\
             若是库重建所致，重跑 catalog_baseline 后更新 FROZEN；\
             若是评分规则改动，先改 evidence.rs 文档再随新基线一起更新。"
        );
    }

    // 结构不变量：每组合计恰好等于组数（评了且只评了一次），D 在纯目录视角下
    // 必须为 0（目录工具无权断言"主体没解码"）。
    let sum: usize = got.iter().map(|(_, n)| n).sum();
    assert_eq!(sum, FROZEN_GROUPS, "等级合计 {sum} ≠ 组数 {FROZEN_GROUPS}");
    assert_eq!(got.iter().filter(|(g, _)| *g == Grade::D).count(), 0);
}

#[test]
fn texture_refs_and_ref_rows_agree_on_every_group() {
    // 防下一次漂移的那道闩：`texture_refs`（按名去重）与逐行 `refs_from_group`
    // （按 hash 走、按名归并）必须对**每一组**给出相同的 refs_total / refs_located。
    // 基线与工作台曾经各用一条路，才有了 A2 与 A0 的分家；这里保证两条路永远同答案。
    let Some(c) = cat() else { return };
    let groups = c.groups(50_000).expect("读取资源组");
    let mut checked = 0usize;
    for g in &groups {
        let by_name = c.texture_refs(g.id).unwrap_or((0, 0));

        let mut names: std::collections::BTreeMap<String, bool> = Default::default();
        for r in c.refs_from_group(g.id).unwrap_or_default() {
            if tlbb_core::catalog::labels::is_texture_name(&r.name) {
                let landed = names.entry(r.name.clone()).or_default();
                *landed |= r.to.is_some();
            }
        }
        let by_rows = (names.len(), names.values().filter(|v| **v).count());

        assert_eq!(
            by_name, by_rows,
            "gid {} ({}) 两条计数路给出不同答案",
            g.id, g.stem
        );
        checked += 1;
    }
    assert_eq!(checked, FROZEN_GROUPS);
}
