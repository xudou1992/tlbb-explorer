# Signals 统一 · 结论（2026-09-22）

## 一句话

评分算法从 4 处各自实现收口为 1 处（`catalog::evidence::EvidenceFacts`），
全库 13,080 组在基线与工作台给出**逐字节相同**的等级分布：**A20 / B2581 / C10479 / D0**。

## 修之前：为什么两处评分会分家

| 分歧点 | 工作台 | 基线（旧） | 后果 |
|---|---|---|---|
| `hub_decoded` | 主体文件真的解码成功 | `!cands.is_empty()`（同目录有没有贴图） | 基线把 12,137 个"目录里没贴图"的组判成 D（实报 12,134），工作台 0 |
| 贴图引用总数 | 只数 `贴图` 标签的条目 | `agroup_names` 行数 | 两套行集，同一资产 tot 不一样 |
| 已定位数 | 同上 | `refs_from_group` 行数 | 与 tot 来源不同——分子分母都不是一个集合 |

最 irony 的一条：`refs.kind` 里存的是**扩展名**（`.tga`/`.mtl`），从来不是中文"贴图"，
工作台拿显示标签当过滤条件，等于**永远过滤不出任何东西**——但恰好因为两边都错，
错错相抵，工作台的 tot/loc 反而"看起来能用"。

## 修法：三个动作

1. **`evidence.rs` 新增 `EvidenceFacts`**（原始事实）+ `Decode` 三态枚举
   （`Decoded` / `Failed` / `Unmeasured`）。
   关键设计：**目录级工具无权断言"主体没解码"**。基线不打开容器，就声明
   `Unmeasured`，D 规则不触发，只按组成 + 引用评分——它看到的就这么多，就评这么多。
2. **`sqlite.rs` 新增 `Catalog::texture_refs(gid) -> (total, located)`**：
   按名去重、`max()` 聚合（任一行可定位即算定位）、贴图扩展名集合唯一。
   这是两条工具共用的唯一计数查询。
3. **四处调用点全部改走 `EvidenceFacts`**：`data.rs`（工作台）、
   `catalog_baseline.rs`、`asset_cards.rs`、`asset_report.rs`
   （后两处的贴图计数也于 2026-09-23 审计后改走 `texture_refs`）。

## 修之后：三方对账

| 口径 | 结果 |
|---|---|
| 基线 `catalog_baseline --json` | A20 / B2581 / C10479，`grade_coverage.decode_unmeasured=13080` |
| 工作台 `tlbb-shell --probe` | A20 / B2581 / C10479 / D0 |
| Python 直连 SQLite 复算 | A20 / B2581 / C10479 / D0（逐位一致） |

合计 20 + 2581 + 10479 = 13080 ✓

**A 档 20 组全在 `ui/icon/wardrobe`**：material + texture 两角色、单一贴图引用且全部定位
（如 `w1351_nan_s_moyuqianyou_001`）。是真 A，不是巧合——它们是全库唯一
"组成完整且引用全落地"的资产族。

**旧 A2（gid 1994/2118）降为 B 的原因**：这两组各有 2 条贴图引用
（`*.tga` 已定位 + `*_pbr.tga` 悬空），旧基线按名字表计数只看到 1 条，
新口径如实暴露 `_pbr` 悬空 → 不再满足"全部定位"。**这是纠错，不是回归。**

## 双计数路对账（防下一次漂移）

- `texture_refs`（按名去重）vs 逐行 `refs` 重算：**全库 13,080 组两条路同答案**；
- 同名多行共 1,388 对，**可定位性 0 条混合**（要么全定位要么全悬空），
  所以 `refs_from_group` 的 `GROUP BY` 任取一行也不会说谎——但这是**数据性质**，
  不是查询性质，已用测试钉住。

## 冻结

`crates/core/tests/grade_census.rs` 两条测试：

1. `frozen_grade_distribution_holds` —— 钉死 `13080 = A20 + B2581 + C10479`，
   D=0，`decode_unmeasured=13080`。库重建或评分规则修订时这里红，
   红了就重跑基线、人工确认后更新常量。
2. `texture_refs_and_ref_rows_agree_on_every_group` —— 两条计数路逐组相等，
   谁再给任何一处写私有 SQL 计贴图引用，这里红。

**冻结面审计**（2026-09-23 agent 扫描）：`asset_cards.rs` / `asset_report.rs` 各有一处
自建贴图计数残留（refs 列表 × hub 定位源），已改走 `Catalog::texture_refs`。
至此四处调用点（data.rs / baseline / cards / report）全部同一条查询。

## 验证记录

- `cargo test -p tlbb-core`：**144 passed, 0 failed**（含新增 evidence 归约测试 9 条、
  grade_census 冻结测试 2 条，全绿两轮）。
- 工作台重编译通过（`Finished dev`，1 条既有命名警告）。
- 探针脚本：`.scratch/verify_A20.py`（复算）、`aset_cmp.py`（双路 A 集对比）、
  `mixed_probe.py`（混合行探测）、`cross_check.py`（单资产对账）。
- 基线产物：`.scratch/baseline_now.json`。
- 排障备注：期间一次 exit 101（E0382）是并发会话写 `preview/summary.rs` 的中间态
  被编译逮住，磁盘文件自洽，与本轮改动无关。

## 用户报价纠偏

用户引用的基线旧数（A2 B23 C921 D12134）是**更早一轮**的产物；本轮修前实测为
A2 / B2599 / C10479 / D0 附近（B/C 之差来自名字表 vs refs 行集），修后三方收敛为
A20 / B2581 / C10479。差别本身不重要——重要的是现在**只剩一个数字来源**。

## 下一步

数据层冻结完成。按既定顺序进入 **P3-B 内容考古墙**
（24,261 无名贴图 → 缩略图 → 聚族 → 人工标注）。
