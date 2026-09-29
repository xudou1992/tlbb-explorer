# TLBB Explorer

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Rust](https://img.shields.io/badge/Rust-stable-orange?logo=rust)
![Tauri](https://img.shields.io/badge/Tauri-2-24C8DB?logo=tauri)

天龙八部（TLBB）客户端资源浏览器 —— 让人能看懂客户端里有什么。

> **本仓库只带源码与结论，不带客户端二进制，也不带任何游戏素材。** 客户端 `data*.pak`（6GB）与 Rust
> 构建目录合计 40GB+，全部排除在版本控制之外。换机后按「首次运行」重建即可。

---

## 免责声明

- 本项目是**非官方、未授权**的第三方互操作性研究工具，与游戏开发商、发行商及任何运营方
  **均无关联、均未获其认可**。
- 仓库**不包含**游戏客户端、`data*.pak`、模型 / 贴图 / 音频等任何游戏素材，也**不提供**
  获取途径。使用者需自行准备合法取得的客户端，并自行承担相应责任。
- 唯一随仓库分发的客户端派生数据是 `crates/core/assets/cipher_table.bin`（16 KB，4096 个
  `u32` 常量）：它是解析容器所必需的解密表，属于**功能性互操作性常量**，不含任何美术作品。
- 格式知识来自对本地客户端的合法研究，仅用于**理解与互操作性**目的。**请勿**用本项目
  分发游戏素材，也请勿用于商业运营服务端。
- 游戏名称、资源名与商标归其各自权利人所有。

---

## 这是什么

一个只读的客户端资源浏览器/解包预览器。**不做资产知识图谱**，只回答
「客户端里有什么、长什么样」。

**第一屏是「浏览」（2026-09-27 用户定版）**：左边点一个 `data*.pak` → 中间列出
它里面的文件夹结构（原始路径树）→ 点文件预览（贴图直接出大图）→ 一键导出
（单文件 / 文件夹 / 整包，目标目录强制在客户端根之外）。没有名字的文件按
16 位编号摆在「(未命名)」桶里，照样能预览能导出——编号是身份不是路径，不编造。

其余入口都是第二位：

- **资产检索**（第二标签）：按「资产组」搜索与详读，面向研究
- **分析模式**（开发者选项）：refs / dangling / evidence

### 路线图（2026-09-27 更新）

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.3.0 | 贴图 Resolver v1（cfg翻译表+UV试贴+覆盖表） | ✅ 已封板 |
| v0.3.1 | 地图 UI 重构 + 中文别名 + 白话状态 | ✅ 已封板 |
| v0.3.2 | 地图坐标证据闭环（R/Rᵀ、原点、32格） | 排队 |
| **v0.4.0** | **工作台 UI 全面改版（亮色青绿 · 三栏 · 六标签页 · 环形图/关系网/贴图候选）** | ✅ 已封板 |
| v0.4.0.1 | 缺陷修复轮：导出 junction 闸门 + 前端五处接线（常驻行为用例钉住） | ✅ 已封板 |
| v0.4.1 | 贴图批量 Resolver 进工作台（引擎移进 core · 后台跑 · 进度事件 · 界面可发起） | ✅ 已封板 |
| v0.4.2 | UV 评分升级（颜色/alpha 维度进界面：因子/综合分排序 + 取图按编号） | ✅ 已封板 |
| **v0.5.0** | **动画解析/播放（先走跑攻待四动作）** | ← **当前**（关键帧已解出；播放卡在蒙皮权重，见下） |
| v0.6.0 | 特效解析/播放（单独立项） | 排队 |
| v0.7.0 | 地形解析/真实地图 | 排队 |
| v0.8.0 | 1.2 万未知数据块分类/解析 | 排队 |
| v1.0 | 完整资源理解浏览器 | 终点 |

**关于「动画 / 着色器还没搞定」的口径**（动画部分 2026-09-29 更新）：
- **骨骼动画**：`.ani` **关键帧已解出**（v0.5.0 的解析层）——每骨每帧
  四元数 + 位移 + 缩放，四个真样本 21/26/31/41 帧逐字节对齐、全部四元数单位长，
  口径钉在 `crates/core/src/preview/anim.rs`，并由一条全库抽样闸门守着：随机抽
  60 份 `.ani`（骨骼数 1~181）→ 230,268 个旋转字段全部单位四元数。**播放还做不了**：父骨链、绑定位
  与蒙皮权重都不在 `.mesh`/`.ske` 里（见下），没有权重就没法把动作贴到模型上。
  这一条是「解析完成、播放待续」，不再是「格式没看懂」。骨架静态区里的绑定旋转
  也读得出（184/184 单位四元数）；父骨链与绑定位移既不在 `.ani` 也不在 `.ske`
  （`.ske` 是动作登记表，数值区几乎全零、没有骨架矩阵）——下一条线索在客户端
  引擎侧的 bip01 模板。浏览视图点一个 `.ani` 现在会报「骨骼 46 条 · 关键帧 21 帧
  · 会动的骨 N 根」，并把为什么还不能播写在同一屏里。
- **着色器**：`.mtl` 里的着色器槽名（如 `DynModelShader`）已能读出并如实标「缺」，
  但着色器本体（编译后的 GPU 程序）**不打算还原**——它要靠引擎运行，不是资源问题。

---

## 项目纪律（改代码前必读）

这五条是硬规矩，违反它们比写出 bug 更严重：

1. **没解出像素不显图。** 绝不拿同目录的图顶替。
2. **名称一律客户端原文。** 不翻译、不编显示名。**例外（2026-09-26 裁定）**：地图可加
   中文白话别名，但别名必须有**人工标注或证据**（见 `.scratch/map_aliases.json`），
   原始 ID 永远一起显示（`大理城` + `w1351_ll_dl_002`），没有证据就显示「未命名地图」，
   不许按拼音猜。
3. **命名推断 ≠ 引用。** same-stem / model-part 只进 `relations`，不进 `refs`。
4. **数据层英文键，中文只在展示层映射。**
5. **悬空引用显示「缺」，不编造。** `resources.db` 一律只读。

### 已经推翻、不要再回头的结论

- ❌ 2.4 万无名贴图**不是**解析漏了 —— 名字唯一来源 JRPC 已穷尽；**原始文件名不可保证恢复**
- ❌ 「共享」概念不存在
- ❌ 100% 自动恢复原始文件名不成立 —— 但**所属关系（贴图→材质→模型）可以重建**，见下面三层账第 3 层
- ❌ `.tga` 断链是**客户端设计使然**（path 从未入命名表），工具无错

### 三层账（2026-09-26 用户裁定：所有进度汇报按此口径，禁止把三层混为一谈）

1. **解包（把字节从 pak 拿出来）——✅ 100% 完成，不再投入。**
   105,327 = 57,274 有名（57,195 个已落盘 `.scratch/out/tree`，逐类对账分毫不差；差 79 个
   是 WebView2 散件，本来就在客户端目录）+ 48,053 无名（字节全在 pak 里随时可取，
   其中 24,260 张贴图已导出缩略图）。
2. **解析（看懂内容）——进行中的战场。** 已懂：图片 / 网格 / 材质 / 模型 / 地图物件。
   没懂：动画关键帧、特效（.pu/.tani）、地形 .map、1.2 万无名 geom 块、小杂料。
   说「XX 还没解出来」之前先问自己说的是哪一层——文件没拿到和格式没看懂是两回事。
3. **关联（它属于谁）——当前主攻。** 原始名字丢了 ≠ 所属关系丢了。配对四梯队：
   ① 材质引用重解析（必先做）→ ② 内容特征匹配（尺寸/codec/alpha/hash）→
   ③ UV 吻合度验证 → ④ 人工目检最终裁决。每条配对关系带证据等级；
   目标不是 100% 恢复，是「每一条都说明证据是什么」。
   **`ResourcePath.cfg` 悬案已仲裁（2026-09-26，见 `.scratch/cfg_arbitration_20260926.md`）**：
   证实藏有 72,764 对「裸名→全路径」，材质悬空贴图名被解释 **90.8%**（7,888/8,688）；
   之前解析失败是因为字符串数 145,528 超了 `jbcf::parse` 的 8192 上限，文件本身无畸形。

---

## 目录结构

```
.
├── tlbb-explorer/                    # 主项目
│   ├── crates/core/                  # 解析 + catalog（Rust）
│   │   └── src/
│   │       ├── preview/              # 语义层：字节 → 人能看懂的摘要
│   │       │   ├── geometry.rs       # .mesh 几何解析
│   │       │   ├── summary.rs        # 类型化摘要（FileKind 路由）
│   │       │   └── scene.rs          # .scene 地图格子解析（M3-0）
│   │       ├── catalog/              # resources.db 只读访问
│   │       ├── jbcf/ jpak/ jmt1/     # 容器与解码
│   │       └── bin/                  # view.rs（CLI 预览器）等
│   ├── app/                          # Tauri 2 工作台
│   │   ├── src-tauri/src/            # IPC（inspector.rs / mdl_view.rs / mesh_view.rs）
│   │   ├── web/                      # 原生 JS 前端（零依赖）
│   │   │   ├── lib/                  # 状态机（detailState.js / mapState.js）
│   │   │   └── mesh-viewer.js        # 原生 WebGL 灰模渲染
│   │   └── tests/                    # node --test
│   ├── contracts/                    # 跨语言契约
│   └── tests/                        # Rust 集成测试
├── .scratch/                         # 探索产物与结论（**换机必须带走**）
│   ├── *.md                          # 阶段结论报告
│   ├── agent_*.txt                   # 探索过程记录（含地图/scene 逆向）
│   └── M3-0_地图灰模_分派规格.md      # 当前阶段的分派规格
└── LICENSE                           # MIT
```

---

## 首次运行（换机后）

### 1. 自备客户端

仓库不含客户端。需要一份 TLBB 客户端安装，其中至少有：

```
<客户端根>/
├── data.pak data1.pak ... data4.pak data_1.pak    # 资源容器（6GB）
└── ...（其余运行文件）
```

### 2. 重建资源清单

`resources.db`（145MB）不入库，需要重新索引客户端。建库脚本随仓库分发在
`.scratch/dbbuild.py`（Python + 标准库 sqlite3，无第三方依赖）。一趟跑全三阶段：

```bash
# 第 1 步：扫 6 个 pak 的索引 → resources / records（顺带落 .scratch/index_off.tsv）
python .scratch/dbbuild.py
# 第 2 步：把 payload 解出来（refs / relations 要从文件内容里读，见下方说明）
python .scratch/pakunpack2.py --outdir <客户端根>/.scratch/out
# 第 3 步：读 JBCF 字符串表建引用边、聚资产图
python .scratch/dbbuild.py --no-build --rels --assets --extras
```

客户端不在 `D:\TLGL`、或库想建到别处，用命令行或环境变量覆盖（与 Rust 侧同一套约定）：

```bash
python .scratch/dbbuild.py --root E:/Games/TLBB --db E:/Games/TLBB/.scratch/resources.db
# 等价：TLBB_ROOT=... TLBB_DB=... python .scratch/dbbuild.py
```

> **`--rels` 那一步的产出取决于第 2 步解没解全。** 引用边（`refs`）不是从文件名猜的，
> 是打开材质/骨架/模型这些 JBCF 文件的字符串表读出来的，所以它只认
> `.scratch/out/all/<容器>/<编号>…` 里真存在的字节。本机实测：只跑第 1、3 步
> （`out/all` 不全）得到 `refs` 93,395 / 资产组 12,779；把 payload 解全之后才是
> 基线那套 98,504 / 13,080。**别拿一个没解全的库去对基线然后说脚本错了。**

> 名字表来自 `.scratch/names_jrpc.tsv`（JRPC 恢复出来的 hash→虚拟路径，随仓库分发）。
> 没有它照样建库，只是绝大多数条目会落到「未命名」那一边——那是客户端打包时
> 剥掉文件名的结果，不是解析漏了。

建完后**务必跑基线核对**（等级分布是冻结值）：

```bash
cargo run --release --bin catalog_baseline
# 期望：A20 / B2581 / C10479 / D0
# 组 13080 / 成员 48122 / 资源 105327
```

对不上就说明索引方式和当初不同，**先查清楚再继续**，不要改冻结值。

> **2026-09-29 实测：照上面重建，数字会比冻结基线多 1,799 条（107,126 vs 105,327），
> 这不是重建错了，是随仓库那份库少算了。** 差全部来自 `data_1.pak`（更新器写的补丁包）
> 的第 12、13 两代索引数组：老库只跟到第 11 代，而新库是老库的严格超集（老库独有的
> hash 有 0 个）。根因是建库脚本的索引遍历靠「上一条 payload 的末尾」猜下一个数组位置，
> 补丁包的数组不连着排就断了链——已改成与 Rust `jpak` 同一口径顺着数组头里的 `next`
> 指针走（`.scratch/pakunpack2.py`），改完 Python 侧与 Rust 侧一字不差：
> `data.pak` 16 数组 / 15,651 槽，`data_1.pak` 14 数组 / 13,684 槽。
> **基线常量还没重钉**（那要连随仓库那份库一起换，属于口径变更），在此之前
> 重建后跑 `catalog_baseline` 必然对不上，原因就在这段话里。

### 3. 构建

```bash
# Rust core
cd tlbb-explorer
CARGO_TARGET_DIR=.scratch/rc3 cargo build --release --jobs 1

# 前端（dist 在编译期嵌入，改了 web/ 必须重建 exe 才生效）
node app/web/build.mjs
cd app/src-tauri && cargo build --release
```

### 4. 验证

```bash
# CLI 探针：全链路只读自检，末尾带 M1/M2 验收段和计时
./tlbb-shell --probe 曹霜

# 地图金标准：重跑 6 张真图，与 contracts/map_golden.json 逐字段比（动过 scene/几何解析必跑）
node tools/map_golden.mjs
```

> `node --test tests/`（旧写法）在 Node 25 下报 `MODULE_NOT_FOUND`，要显式列文件名：
> `cd tlbb-explorer/app && node --test tests/wording.test.js tests/detailState.test.js tests/meshViewerInstances.test.js tests/meshLayout.test.js tests/seq.test.js`
>
> `tests/behavior.test.js` 用 `node:vm` 的 ESM 沙箱跑真前端（只替掉 IPC 和 WebGL），
> VM Modules 仍是实验特性，必须带开关：
> `node --experimental-vm-modules --test tests/behavior.test.js`

### 5. 测试夹具（不入库，按需自取）

`crates/core/tests/` 下有几条用例吃**客户端原始字节**当夹具（2 个 `.mesh` + 3 个
`.scene`）。它们**不入库**——避免随仓库分发游戏素材——缺样本时用例自己跳过并在
stderr 说明，**不算失败**。想让它们真跑，从你自己的客户端导出：

```bash
# scene 夹具：产物先落 %TEMP%\tlbb_scene_samples
cargo run --release --bin dump_scene_sample
# 再把 grid_749 / grid_753_full / grid_753_with_tail 三个 .scene
# 拷到 tlbb-explorer/crates/core/tests/scene_samples/

# mesh 夹具：从 pak 直接落原始字节（走工作台「浏览」视图导出也行）
cd tlbb-explorer/crates/core
cargo run --offline --example dump_raw     # 写回 tests/ 那两个 .mesh
```

> `dump_raw` 只写 `payload::decode` 出来的字节。曾经本机这两个夹具是
> **UTF-8 有损转码后的副本**（真 18,408B → 存成 29,445B），用例读到的是
> 「子网格数字段 131072」那种假头——夹具必须是字节，不能是文本。

### 6. 环境变量（可选）

```
TLBB_ROOT=<客户端根>        # 默认 D:/TLGL
TLBB_DB=<resources.db 路径> # 默认 <root>/.scratch/resources.db
```

> 部分 `bin/` 下的开发期工具把 `D:/TLGL` 写成了默认值（历史原因），用 `--root` /
> `--db` / `--out` 覆盖即可，不影响正常使用。

---

## 当前进度：v0.5.0 动画（解析已成，播放待续）

已解：`.ani` 的关键帧（每骨每帧 旋转/位移/缩放）与骨架静态区的绑定旋转，
口径与证据在 `crates/core/src/preview/anim.rs`。浏览视图点一条 `.ani` 会报
「骨骼 N 条 · 关键帧 M 帧 · 会动的骨 K 根」，并写明为什么还不能播。

未解（播放的前两道槛）：父骨链、蒙皮权重。已排除的去处：`.ske` 是动作登记表
（数值区几乎全零、没有骨架矩阵）、客户端 exe 里没有 `bip01` 字符串、
`.mesh` 的「未解中间」区不是「4 索引 + 4 权重且和为 1」的连续数组。
没有骨链与权重，动作贴不到模型上——这是缺证据，不是缺工时。

### 地图侧已锁的口径（v0.2/v0.3 的成果，别再回头验）

`.scene` 格式**已解**（全量 11,933 文件独立复算）：

```text
偏移 0x00  u32  n_records    记录数（★会被低估，尾部还有附加段）
偏移 0x04  u32  tag          753 / 749 / 605 / 592 / 596 / 601 / 324 / 957
偏移 0x08  u32  zero

base   = 12        恒定，与 tag 无关
stride = tag + 8   753→761、749→757、605→613、592→600
记录   := [64B 列主序仿射矩阵] [名字区，长度 = stride-64，名字起点恒为 64]
平移在 m[12], m[13], m[14]；floor(m[12]/32)、floor(m[14]/32) 对上格子文件名
```

链已闭合：`.scene`（物件清单）→ 网格名 → mesh 解析器 → WebGL 灰模。
地图灰模浏览器与地图浏览器重构（v0.2 / v0.3.1）都在用这套口径，回归由
`node tools/map_golden.mjs` 的 6 张真图金标准盯着。

---

## 数据基线（2026-09-22，可用 `catalog_baseline` 重算）

| 指标 | 数值 |
|---|---|
| 资源组 / 成员 / 资源 | 13080 / 48122 / 105327 |
| 引用总数 / 已解析 | 98,504 / 61,408（62%） |
| 悬空名 | 14,377 |
| 等级分布 | **A20 / B2581 / C10479 / D0** |
| .mtl 解析率 | 98% |
| .tga 解析率 | **0%**（30,585→25，客户端设计使然） |
| .ani / .mesh / .ske | 72% / 92% / 89% |

等级分布是**冻结值**，由 `tests/grade_census.rs` 钉死。库重建或改评分后必须重跑基线
并更新常量。

---

## 已知的环境陷阱（Windows 沙箱）

1. **Bash 工具不可用** —— `dirname` 都找不到。一律用 PowerShell。
2. **PowerShell 吞 stdout**，`*>` 产出 UTF-16LE。抓输出要写 UTF-8 文件再读。
3. **判断命令成功只看 `$LASTEXITCODE`** —— `NativeCommandError` 是假警报。
4. **构建必须** `CARGO_TARGET_DIR=D:\TLGL\.scratch\rc3` + `--jobs 1`。
5. **同文件多处编辑禁止放同一条消息**（读旧写回会互相覆盖）。
6. `crates/core` 无 `anyhow` / `image` 依赖（离线环境），新代码只用 `std`。

---

## 许可证

[MIT](LICENSE) —— 可自由使用、修改、分发、商用，保留版权声明即可。

## 贡献

欢迎 issue 与 PR。提交前请先读上面那五条项目纪律，尤其：

- **没解出像素不显图** —— 绝不拿同目录的图顶替
- **悬空引用显示「缺」，不编造** —— 宁缺勿假

新增解析器请自带用例，并保证**夹具缺席时降级跳过**而不是 panic（夹具不入库，
见「测试夹具」）。数据层返回英文键，中文只在展示层映射。
