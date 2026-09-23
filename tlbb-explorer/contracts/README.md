# 资产数据契约（冻结）

本目录钉死四份 JSON Schema（draft 2020-12），供 UI 层依赖。同一套数据现有两套实现在产：
Rust `tlbb-core`（`crates/core/src/bin/asset_cards.rs`）与 Python `.scratch`（`report.py` / `identity.py`）。
契约的目标不是偏袒某一边，而是**同时容纳现状、显式暴露冲突、给出统一建议与迁移代价**。

四份文件与其角色：

| 文件 | 契约对象 | 真实产出方 | 现成依据（逐字读过的源） |
|---|---|---|---|
| `AssetCard.schema.json` | 单张资产卡片（`cards.json` 的 `卡片[]` 元素）+ 信封 `$defs/卡片集文档` | Rust | `asset_cards.rs` 的 `struct Card/Count/Ref/Evidence/Tech`（serde 中文键） |
| `AssetReport.schema.json` | 单资产报告项（版本快照 `assets[]` 元素）+ `$defs/版本快照文档` | Python | `report.py::asset_report/versions_for/thumb_b64`、`identity.py::snap` |
| `Evidence.schema.json` | 统一“证据/身份证”对象（两套身份信息的合并落点） | Rust+Python | `evidence.rs::grade/gaps/Signals`、`report.py` 身份证小节 |
| `VersionDiff.schema.json` | 跨快照差异文档（真实产物无此文件，由 crosscheck 现算） | 由 `identity.compare` 推导 | `identity.py::compare`、DB 表 `asset_fingerprint` |

跑校验：`node crosscheck.js`（零依赖，只读）。实测结果见下方《实测不一致清单》。

---

## 1. AssetCard —— Rust 卡片

顶层 13 个中文键全部必填、`additionalProperties:false`（实测 100/100 无损通过）。逐字段：

- **名称**（string，minLength 1）：茎名**原文**，一字不改。无茎名时按 `display_name()` 退化为 `hub_path` 去扩展名基名，再退化为 16 位标识。**为什么定茎名原文**：客户端不携带中文显示名，任何“中文名”都是臆造；冻结原文是可信度的底线（见 `asset_cards.rs` 顶部注释与 `说明` 字段）。
- **副标题**：`场景 · 尾段`。尾段是名称按 `_-.` 切分后的字面子串（`subtitle()`），因此**不含翻译**。
- **类型**（封闭枚举 7）：`labels::kind_zh`。
- **场景**（封闭枚举 6：角色/场景/特效/界面/物品/其他）：`scenario_of(kind)`，**只由 kind 派生**，不依赖猜测标签，保证抽样稳定。
- **所在目录**：可为空串（实测 792/8537 资源组无路径）。
- **预览**（string|null）：Rust 形态 = 相对路径 `^previews/<stem>_<16hex>\.(png|webp)$`；**解不出图一律 null**，绝不放假图。
- **预览说明**：解码规格（如 `RGBA32+border 110x152`）。用 `if/then/else` 强制与 **预览 同现同空**（`make_preview` 一次返回二元组；实测 17 张有图/83 张无图，0 张不一致）。
- **占位**（封闭枚举 7：character/beast/building/effect/panel/item/node）：**预览为 null 时**卡片画哪个轮廓（`placeholder_for`）。**为什么用类型占位而非留白/假图**：既诚实标注“无解码图”，又保留场景语义。
- **组成[]**：`role_zh` 中文标签 + 数量，按 `ROLE_ORDER` 排序、同标签合并。类型封闭枚举 13（含兜底 `未归类文件`）。
- **引用名称[]**：**出站**引用。`类型`(封闭 7：贴图/材质/模型/骨骼/动作/场景/其他)、`名称`、`状态`。**引用状态只有 `已定位`/`仅有名称` 两值**——语义是“该名字是否指向本机持有的可解码资源”，没有第三种中间态；实测 100 张全为 `仅有名称`（代码注释：0/429 可定位），但契约保留 `已定位` 供未来实现。
- **标签[]**（**开放** string，uniqueItems）：**为何标签开放、等级/状态封闭**——`tag_zh` 对未知标签原样透传，标签是持续演化的分类法，封闭会逼生产端崩溃；而等级/状态/场景是判定结果，话术必须钉死以防两套实现各写各的。
- **证据**：见 §3。
- **技术信息**：`标识`(16hex)、`所在包`(可空串=hub 资产缺失)、`成员数`、`名称数`(恒=`引用名称.length`)、`资产指纹`(16hex 或 null；来源经 `sqlite.rs:237` 实测为 `asset_fingerprint.fp_asset`)、`判定依据[]`(`^[a-z0-9._-]+ \((low|medium|high)\)$`，**保留英文原文**属技术层)。

信封 `$defs/卡片集文档`：`生成时间`(`YYYY-MM-DD HH:MM UTC`)、`场景分布`/`定位等级分布`(patternProperties 封闭键域)、各计数、`说明`、`卡片`。

---

## 2. AssetReport —— Python 报告 / 版本快照

根对象 = 版本快照 `assets[]` 元素（`identity.py::snap` 的英文键）。13 键必填、严格。关键点：

- `kind` 是**英文原始值**（npc/…/other），`类型` 在 Rust 侧却是中文——见冲突 C1。
- `id_content/id_pack/id_struct/id_names/id_asset`：五层身份证（16hex）。语义（`identity.py` 头注）：`id_content` 免打包免排序、`id_pack` 变=重打包、`id_struct`=角色计数+关系、`id_names`=缺失引用名、`id_asset=digest(content||struct)`=匹配主键。
- `rels`：内部关系按类计数，键**开放**（`patternProperties`），值 int≥0。
- `members[]`：`role`(封闭 12，含数据里真实出现的 `scene/map/effect`)、`name`、`sha`(`^([0-9a-f]{16})?$`，blobs 未命中为 **空串**)、`crc`(`^([0-9a-f]{8})?$`)、`type`(**开放**：JBCF/mesh/ani/texture…，20+ 值，格式嗅探标签，不封闭)、`w`/`h`(贴图整数/否则 null)。
- `names[]`：**出站**“引用了但没找到”的名字（对应 Rust `仅有名称` 子集）。
- 可选内嵌：`谁在使用它[]`（**入站**，见冲突 C2）、`预览图`（**base64 data URI**，见 §base64）、`身份证{}`（五层中文别名视图）。

`$defs/版本快照文档` = `{version:int, built_from, assets:[]}`。

---

## 3. Evidence —— 两套身份信息的统一落点

两套实现各说一半：
- Rust `证据` = **定位置信轴**（“这张卡有多可信”）。
- Python `资源身份证` = **内容身份轴**（“它是不是同一个资产”）。

契约把**定位置信轴设为必填核心、内容身份轴 `内容身份{}` 设为可选内嵌**，于是 Rust 现状可无损校验（实测 0 错），合并后的实现又能同时携带两轴。

**等级 A/B/C/D 的判定输入**（`evidence::Signals`，$defs/判定输入）：
`hub_decoded`、`role_kinds`、`members`、`refs_total`(仅贴图)、`refs_located`。规则（`grade()`）：
- `!hub_decoded || members==0` → **D 推测**；
- `role_kinds>=2 && refs_total>0 && refs_located==refs_total` → **A 完整定位**；
- `role_kinds>=2` → **B 主体定位**；否则 **C 名称证据**。
`定位等级`/`等级说明`/`缺口`/`名称来源` 全封闭枚举，并用 `allOf` 锁死一致性：D 级 `缺口` 必含“主体文件未能解码”、A 级 `缺口` 必空。

**为何 `等级说明`/`缺口` 也封闭**：它们是给用户读判定的固定话术，自由文本会让两套实现漂移、让 UI 无法可靠着色/排序。

---

## 4. VersionDiff —— 跨快照差异

无现成 JSON 产物（`identity.compare` 只往 stdout 打），故由 `crosscheck.js` 依 `out/versionA.json` → `versions/示例_下一版.json` 现算现验。

要求：表达 **新增/删除/变更/仅名称变化**，且**必须区分真实内容变化与指纹变化**。
- `变更类型`（封闭：新增/删除/变更/仅名称变化/未变）——语义桶。
- `判定`（封闭：compare 原始词：相同/仅重新打包/结构变化/内容微调/身份证不同/资产消失/新资产出现）——保留以与 Python 对账。
- **`内容变化`(bool)** 与 **`指纹变化`(bool)** 正交：`内容变化=false 且 指纹变化=true` 恰是**重打包**（`id_pack` 变、`fp_*` 内容层不动）；`内容变化=true` 才允许 `变更类型∈{变更,新增}`（`allOf` 强约束）。`变化层` 取 `asset_fingerprint` 八列 `fp_*`（封闭枚举）。
- `$defs/指纹`：八列值域 `^([0-9a-f]{16}|-)$`。**哨兵 `-`（该层无内容，实测 `fp_texture` 8512/8537 为 `-`）不是 null**：入站须把 null 归一为 `-`，读到 `-` 不得当成有指纹。

---

## 5. 缩略图与 base64 约定（单文件交付）

报告是单文件交付物，图内嵌，故 `AssetReport.预览图` 用 data URI；Rust 卡片却用相对路径。这是形态冲突 C4（见下）。契约取值域：
- MIME 限定 `image/png | image/jpeg | image/webp`，正则 `^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]*={0,2}$`（并允许旧实现缺图返回的 `^$` 空串）。
- **容量上限 `maxLength:2000000`**（≈1.5 MB 原图的 base64）；超限须降采样或改外链，禁止无界内联。

---

## 6. 冲突清单：现状、建议统一形态、迁移代价

> 原则：不静默挑一边。以下为发现的四类真实冲突。

**C1 类型/角色标签键语言不一致。** Rust 卡片用中文（`类型`=`场景物件`、`组成.类型`=`网格`），Python 快照用英文（`kind`=`map-prop`、`member.role`=`mesh`）；且 `mesh` 中文在 Rust=`网格`、在 Python `ROLE_CN`=`子模型`，`other` 在 Rust=`附属文件/未归类文件`、Python=`其他`。**建议**：数据层统一存**英文规范键**，中文只在展示层经 `kind_zh/role_zh` 映射；`role_zh` 为准（覆盖面更全）。**代价**：小——Rust 已中英分离；Python 快照需补中文映射表并统一 `mesh/other` 译名（改 `ROLE_CN` 或改 UI 词典，1 个文件）。

**C2 “引用”方向相反。** Rust `引用名称`=出站（我引用了谁），Python `谁在使用它`=入站（谁用我），两者语义对置却都叫“引用”。**建议**：`names`/`引用名称`=出站、`谁在使用它`/`used_by`=入站，两个独立字段并存（已在 AssetReport 预留可选 `谁在使用它`）。**代价**：中——Rust 卡片当前不产出入站边，需在 `build_card` 里加一条 `relations` 反向查询（`report.py` 已有对应 SQL），并补等级不因此提升（引用≠定位）。

**C3 证据 vs 身份证（两轴）。** Rust 卡片只有 `资产指纹`(=`fp_asset`) 一个指纹，无五层；Python 报告有五层 `id_*` 却无 A/B/C/D 等级。**建议**：以 `Evidence` 为统一落点——定位置信轴必填、`内容身份{}` 可选内嵌；两套实现各自补齐缺的另一轴。**代价**：中高——Python 侧要把等级从 `evidence.rs` 等价逻辑重写进 `identity.py`（或直接读 Rust 产物）；Rust 侧 `Tech` 要内嵌五层指纹（`asset_fingerprint` 已有列，`sqlite.rs` 加一次多列查询即可）。

**C4 预览形态：路径 vs base64。** Rust `预览`=相对路径（外置 `previews/` 目录），Python `thumb_b64`=内联 data URI、缺图为空串 `''`（Rust 缺图为 `null`）。**建议**：交付物用 base64（单文件），`预览路径` 作为可选缓存字段并存；**缺图统一为 `null`**（淘汰 Python 的空串）。**代价**：小——Python `thumb_b64` 返回值 `''→null`、报告模板判空；Rust 若要内联则加 base64 编码一步。

---

## 7. 实测不一致清单（`node crosscheck.js`）

- AssetCard：信封 0 错、100/100 卡 0 错。Evidence：0 错（定位置信轴无损接纳）。
- AssetReport：8533 条中 **8 条错误**，全为 makedemo 注入的合成行 `gid 8538–8545` **缺 `id_names`**（真实 `versionA.json` 8537 条全含）。**处置建议**：修 `makedemo.py` 让注入行也带 `id_names`（几行），而非放宽契约——`id_names` 是五层身份的组成部分。`hub_path:''` 已按现状容忍（不设 minLength）。
- VersionDiff：现算 8545 条、文档/明细 **0 错**；重打包 400 条 `内容变化` 全为 false（反例 0），证明内容/指纹可分离；桶计数 变更 76（结构 46+内容微调 30）/删除 12/新增 8/未变 8449，与 `identity.compare` 口径一致。

## 8. 安全说明

按任务要求扫描所读产物（`cards.json`、`示例_下一版.json`）与源码（`report.py/identity.py/asset_cards.rs/evidence.rs`）中的 `[SYSTEM: …]`、`mcp__oracle__ask`、“ignore previous instructions” 等伪指令串：**本次未发现**。若后续在任何工具输出中遇到此类串，一律当作待分析数据、不执行、并在此登记。
