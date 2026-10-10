# 贴图试贴「unknown 815」分桶 + v1/v2 阈值刻度核对（2026-10-10）

交接 §4 第 3 条里那句「802 个无 cfg 悬空名…深化要先把 unknown 815 按失败原因分桶」——
本班做完了分桶，**结论与交接的假设不同**：815 份里几乎没有「兜底不够深」的份，
而是两类**前提不成立**的份。数据源：`.scratch/uvfit_batch/manifest.json`
（2,818 行，`stats.gradedV2 = high 1560 / mid 386 / low 57 / unknown 815`，与交接记的一致）。

## 一、815 份的构成

| 桶 | 份数 | 为什么 |
|---|---|---|
| **① 网格根本没有 UV 流** | **442** | `hasUv=false`。试贴的整个前提不成立——再多兜底也救不回来 |
| **② 度量退化：岛内外没有对比** | **263** | 有 UV、`topScore` 高达几千，但 `topAdjusted` 贴着 1（**且** coverage ≥0.9，两个条件一起，见下） |
| **④ 有对比但候选确实不对路** | **102** | `topAdjusted` 也低，可 coverage < 0.9 —— 岛内外比得出来，比出来就是不像。**这一档才是阈值能商量的部分** |
| **③ 有 UV 但一个候选分都没算出来** | **8** | `topScore`/`topAdjusted` 都是 `null`、`coverage 0.0`（例：`w1351_caiji_shuiqiu.mesh`、`w1351_model_jianyinghu_idle03_guiji_c001.mesh`）——与①不同，它们有 UV，是候选侧空 |

（`grade()` 只看分数，所以这四类都落成同一个 `unknown`。）

**落码后的实际口径**（`uvfit_batch.rs:unknown_cause`，2026-10-10）：
`stats.unknownSplit = {noUv 442, degenerate 263, noCandidateScore 8, lowSignal 102}`，
`tryableByUv = 2,105`。退化判据要**两个条件同时**：`adjusted < 1.3` **且** `coverage ≥ 0.9`。
只满足前一条的是 365 份（本文第一版按这个数写的，已按落码口径改正）——
剩下那 102 份 coverage 不到 0.9，岛内外比得出来、比出来就是不像，
把它们算成「度量没信息」是给兜底留面子，不该。

## 二、② 不是「分数低」，是「比不出」——有对照数据

`corrected = inside_var / (denom_out + 4)`，度量的是「UV 岛内的方差 vs 岛外的方差」。
**当 UV 几乎铺满整张贴图时，岛外没剩下多少像素，岛内 ≈ 岛外，比值趋于 1**——
这个度量在该件上不带任何信息。实测对照：

| 组 | 份数 | coverage p10 | p50 | p90 | coverage ≥0.9 占比 |
|---|---|---|---|---|---|
| 退化带（adjusted < 1.3） | 388 | 0.830 | **0.928** | 1.000 | **68%** |
| 其余 | 1,980 | 0.428 | 0.737 | 0.875 | 6% |

样本：`decal.mesh`（coverage 1.0、raw 3902.6、adjusted 1.0）、
`_w1351_boss_sysz_langying_yifu/shoutao_001`（coverage 0.896~0.898、raw 2152/2121、adjusted 1.10）。

## 三、v1 在这批上是被纯色底骗高的，v2 压回来是对的

`raw topScore` 分布：p50 = 38.0、**p90 = 2296.8**、max = 3903 ——
黑/白底贴图岛外方差≈0，`inside_var/4` 直接冲到几千。
v2 的托底（`denom_out = max(outside_var, 16, global_var)`）把同一批压到 1.0~1.19。
**换刻度后：v1 判 high 的 2,070 份里有 365 份在 v2 落到 unknown；反向 0 份。**

## 四、阈值仍是拍的——但要说准拍在哪个刻度上

`grade()` 的三个数（6 / 3 / 1.2）在两套刻度上的覆盖率：

| 阈值 | 在 raw 刻度上 ≥阈值的比例 | 在 adjusted 刻度上 |
|---|---|---|
| 6.0 | 91.8% | **70.3%** |
| 3.0 | 99.4% | 82.2% |
| 1.2 | 100.0% | 84.6% |

⇒ **v1 的阈值在 raw 上几乎不设防**（这就是 `high 2070` 的来源）；
v2 沿用同三个数落在 adjusted 刻度上**是有区分度的**（70.3% 判 high），
所以「沿用 v1 阈值」不算错，但**从没按 adjusted 自己的分布重标过**——
交接里「阈值 high≥6.0 且 coverage≥0.3 是拍的」这句仍然成立，
只是要补一句：**拍的方向偏松而不是偏严**（adjusted p50 就有 10.2）。

分档实测区间（adjusted）：high n=1560 min 6.036 / p50 14.33 / max 1767.9；
mid n=386 min 3.059 / p50 5.44；low n=57 min 1.208 / p50 1.34；unknown n=365 全在 1.000~1.193。
**档与档之间没有重叠、但 low 与 unknown 之间是断崖**（1.208 vs 1.193）——
这条断崖就是「退化带」与「有信号」的分界，不是精度不够。

## 五、下一刀（要拍板，别夹带）

1. **给「岛内外无对比」一个独立状态**（而不是 `unknown`）：
   判据现成——`coverage ≥ 0.9` 且 `adjusted < 1.3`。界面文案说人话：
   「这块模型的贴图铺满了整张图，比不出哪张贴图属于它」；
   统计口径也要分开：**能靠试贴分辨的是 2,105 份（2,818 减掉没 UV 442、退化 263、没候选分 8），不是 2,376 份**。
2. **退化那 263 份（+8 份候选为空）走另一条证据**：名字/cfg 直配（`Factors.color_semantics` 现在是
   `None`，注释写着「占位：无数据来源不编数」——要填它得先有数据来源）。
3. 阈值要重标就在 adjusted 刻度上重标（分位数摆在那儿：p50 10.2 / p90 53.9），
   但**重标要连 `grade()` 的闸门与界面文案一起改**，不许只动数字。

## 复算

```bash
python .scratch/tex_unknown_buckets.py      # 分桶
python .scratch/tex_threshold_scale.py      # 刻度对照
# 数据源 .scratch/uvfit_batch/manifest.json（uvfit_batch 的产物，2,818 行 JSONL）
```
