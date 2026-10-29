# 覆盖表贴图异常项体检

- 表：`D:\TLGL\.scratch\model_texture_override.json`
- 条数：**1**

## `cfg:data/source/player/w1351_nan/texture/toufa/w1351_nan_s_toufa_xianfeng_001.tga`
- 槽名：`w1351_nan_s_toufa_xianfeng_001.tga`
- 哈希：`ab5d2b3da9535d43`
- note：uvfit v1 人工确认
- 时间：2026-10-25 14:08:38
- 绑定网格：`w1351_model_xx_nan_jt_x02.mesh`
- 槽名所属资产组：[1569]
- 引用来源：[('data/source/npc/model/w1351_model_xx_nan_jt_x02/w1351_model_xx_nan_jt_x02.mtl', None)]
- 哈希实体：type=texture 512×512 BC3 mips=10 pak=data path=(匿名)
- 资产组 1569 的网格：['w1351_model_xx_nan_jt_x02.mesh']
  - w1351_model_xx_nan_jt_x02.mesh：候选 10 张，目标 hash 名次 = 4

## 结论
- 「槽名/键/哈希能解」与「能不能自动套回模型」是两件事：
  旧 `mesh_override_png` 只找与网格同名的槽；头发/衣服槽不同名时，确认会写进表但**永远套不上**。
- 2026-10-26 起覆盖表条目带 `mesh` 绑定，确认时由界面写入；加载时按绑定找回。
- 多条绑定同一网格时拒绝猜（mask 与基础色各一条时套错比灰模更坏）。

## 本次整理（2026-10-26）

- 体检：1 条，槽位 / 键 / hash 都能对上；hash 是 `w1351_model_xx_nan_jt_x02.mesh` 候选榜**第 4 名**（共 10 张），512×512 BC3、10 级 mip。
- **异常**：这条例目没有 `mesh` 绑定；旧 `mesh_override_png` **只找与网格同名的槽**，而槽名是
  `w1351_nan_s_toufa_xianfeng_001.tga`，和网格 `w1351_model_xx_nan_jt_x02.mesh` 不同名
  ⇒ 确认写进了表，但模型从来不会自动套上。
- **已修**：给条目录入 `mesh`；确认接口与界面也一并写；加载时先试同名槽，再按 `mesh` 绑定找回。
  实测 `mesh_override_png('w1351_model_xx_nan_jt_x02.mesh')` 回 `slot=w1351_nan_s_toufa_xianfeng_001.tga`、
  `hash=ab5d2b3da9535d43`、PNG 350,006 字节；真窗口打开组 1569 标题显示「已套用人工确认的贴图」。
- 表已统一：hash 小写、LF；原表备份在 `.scratch/model_texture_override.pre_audit_20261026.json`。
- 其余：无重复键、无非法 hash、无绑定到不存在网格的条目。
- 备注：这个槽名是玩家头发，却挂在 `w1351_model_xx_nan_jt_x02`（NPC/怪物资产组）；该组 `.mtl` 确实引用它，不是错标。
- 多条绑定同一网格时现在会拒绝猜（mask 与基础色各一条时，套错比灰模更坏）。

## 追加（2026-10-26）：槽位清单不再只列悬空引用

- 玩家衣服基础色 `w1351_nan_s_yifu_xianfeng_001.tga` 在库里**对上了 UI 小图标**，旧槽位清单只收
  `to_hash is null` 的悬空引用 ⇒ **基础槽根本不出现**，只能标 mask。
- 现在已对上实体的贴图名也列入槽位，并注明「可能是 UI 小图标」；衣服页下拉自动对准与网格同名的
  **基础槽**（真窗口验过 `w1351_nan_s_yifu_xianfeng_001`），确认后走同名槽加载路径。
- 这属于槽位清单的显示/绑定缺口，不改任何贴图归属结论。

## 追加（2026-10-26 晚）：自动对图上线，旧哈希被证实是 UV 检查格图

- 客户端 `convert/dxt/` 桥接回 **9,491 张**匿名贴图后，本槽自动对上的真文件是
  `9871e8ac8c525aa7`（512×512 BC3，`convert/dxt/data/source/player/w1351_nan/texture/toufa/...tga`）。
- 旧哈希 `ab5d2b3da9535d43` 解出的 PNG 是 **UV 检查格图**，不是头发——它当时是候选榜第 4 名，
  但候选榜只是「特征排序」，没有归属含义。第 4 名不是「差不多对」，是另一张图。
- 已从界面「确认这张」改正；表备份 `.scratch/model_texture_override.pre_autoconfirm_20261026.json`。
  重开组 1569 自动套真头发，槽位显示 🟢 + 🔵 一致，不再有 ⚠。
