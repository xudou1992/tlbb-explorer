# ResourcePath.cfg 仲裁报告 · 2026-09-26

> 结论先行：**「cfg 藏有路径映射」证实**。72,764 对「裸文件名 → 全路径」，其中 30,681 条
> 路径是 resources.db 从未索引过的；材质悬空的 8,690 个贴图名被 cfg 解释了 **7,888 个
> （90.8%）**。两份矛盾实测的分歧根源已找到：标准 JBCF 解析器字符串上限 8192，
> cfg 有 145,528 条字符串，超限 18 倍——用 `jbcf::parse` 的会话必然失败。
> 之前「按 8% 可修排期」的刹车解除，但修法不是"补库"，是"开新配对通道"。

## 1. 文件结构（逐字节验证）

标准 JBCF 容器，与 `crates/core/src/jbcf/parser.rs` 的语法完全一致：

```
[0]  'JBCF'  [4] 0  [8] v8  [12] bodyLen=10,853,856
[16] root chunk id=86 size=2,619,524（≈ 72,764 × 36B 记录区）
[2619552] 字符串表 id=85 size=8,234,312 flag=0 count=145,528
          = 2 × 72,764（每对映射 2 条字符串）
          描述符 (u32 len, u32 hash) 交错，字符区 @3,783,792，7,070,080 字节
          表尾 2,619,552+8+8,234,312 = 10,853,872 = 文件尾（slack 3B ≤ 7B 容差）
```

**为什么之前"复现不了"**：`parser.rs::MAX_COUNT = 8192`（按 .mtl/.mdl 的正常规模定的保守上限），
145,528 > 8192 → `Error::StrtabCount` 直接拒收。文件本身没有任何畸形。

## 2. 映射对（72,764 对，模式 100% 成立）

每对 = (裸文件名, 全路径)，如：

```
1351_boss_hadaba_shoutao_001.tga → data/source/npc/quest/w1351_boss_hadaba/texture/1351_boss_hadaba_shoutao_001.tga
100.wav                          → data/sound/run/100.wav
1_-1717_-2645.scene              → mobile_maps/w1351_fb_langhuanyudong_001/1_-1717_-2645.scene
```

路径扩展名分布 top：ani 37,568 · mtl 24,486 · **tga 23,702** · mesh 23,634 · pu 15,494 ·
mdl 5,132 · tani 3,972 · ske 3,704 · collision 1,866 · walkplane 311 …

（"72,760 条"的旧说法修正为 **72,764**，量级判断正确。）

## 3. 与 resources.db 对账（named=57,274）

| 口径 | 数量 |
|---|---|
| cfg 路径 ∩ db 有名路径 | 42,083 |
| **cfg 独有（db 没有）** | **30,681** |
| db 有名但 cfg 没有 | 15,191 |

cfg 独有路径扩展名 top：**tga 11,851** · ani 7,585 · mesh 3,856 · mtl 3,725 ·
collision 933 · wav 866 · ogg 574 · mdl 434 · walkplane 311 · ske 234

样例（全是特效贴图这类此前"无主"的东西）：
`data/effect/textures/fire/w1351_fire_c001.tga`、`data/effect/textures/distort/wyh_distort_lv_h001.tga` …

## 4. 决定性交叉：材质悬空贴图名 × cfg

refs 表（from_hash/from_path/name/kind/to_hash/ambig）中贴图类悬空名：
**8,690 个 distinct**（大小写归一后 8,688）。

| 通道 | 命中 |
|---|---|
| ∩ cfg 裸名侧 | 7,888 |
| ∩ cfg 路径 basename | 7,888 |
| **合计可解释** | **7,888 / 8,688 = 90.8%** |

仍未解释 800 个（9.2%）——后续结合内容特征处理。

## 5. 匿名贴图证据库存（配对原料盘点，24,261 张）

- **尺寸**：64×64 13,457 · 256×256 4,480 · 1024×1024 2,361 · 128×128 1,685 · 512×512 1,152；
  2 的幂尺寸占 24,090/24,261。
- **codec**：RGBA32 12,726 · BC3 9,752 · BC1 1,782 · WEBP 1——全是世界/特效级压缩贴图。
- **mips**：mip 链 1~11 级都有（14,733 张单 mip，其余带完整链）。
- **内容重复率极低**：distinct filecrc 24,239/24,261（仅 22 个重复块）——几乎每张都独一无二。
- **判别性发现**：有名贴图（2,259 张）是另一个世界——WEBP 2,164 张、60×60 类小图标、
  无 mip。**匿名=世界/特效贴图，有名=UI 图标，两个人群零重叠**，配对不会互相污染。
- 解码失败仅 1 张（24,260/24,261 已解出，缩略图在 TEMP 可按 hash join）。
- 顺带：type='geom' 12,676 个无名块只有 **6 种**固定 original 尺寸（105,853~109,960B）
  ——不是逐对象文件，更像 6 种模板；身份继续挂起。

## 6. UV 探针（view.exe 09-23 构建）

| 样本 | 顶点 | 结果 |
|---|---|---|
| w1351_model_plane_c01（静态） | 4 | UV正常 · 法线正常 |
| test_jianzhen（蒙皮 55,864 顶点） | 55,864 | **UV正常** · 法线正常 · 中间段未解不影响 |

→ 四梯队第③级（UV 吻合度验证）的数据前提**就绪**。

## 7. 这改写了什么

**改判前**：`.tga` 名字→实体命中 0.3%，"贴图归属是死局"。
**改判后**：材质引用的贴图名 **90.8% 能从 cfg 拿到全路径和语义目录**
（`data/effect/textures/fire/`、`data/source/npc/quest/<角色>/texture/`……）。
"按目录语义 + 尺寸/codec 特征筛候选 → UV 试贴 → 人工确认"的配对流水线全线有料。

**仍缺的一环（下一步的真工作）**：cfg 只给"名字→路径"，不给"名字→pak 里的字节"。
要把候选路径落到具体贴图 blob，还得靠内容特征（尺寸/codec/mips/像素统计）+ UV 试贴
在 24,260 张匿名贴图里锁定实体——这正是四梯队②③的活。

## 复现

```bash
python D:/TLGL/.scratch/cfg_final3.py     # 全解析+对账+交叉（本报告 §2-4 的全部数字）
python D:/TLGL/.scratch/tex_census_quick.py  # §5 匿名贴图证据
产物：cfg_paths.txt / cfg_keys.txt / mtl_dangling_names.txt（均在 .scratch）
```
