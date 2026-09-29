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
| **v0.4.0** | **工作台 UI 全面改版（亮色青绿 · 三栏 · 六标签页 · 环形图/关系网/贴图候选）** | ← **当前** |
| v0.4.1 | 贴图批量 Resolver（后台预热全部模型） | 排队 |
| v0.4.2 | UV 评分升级（颜色/alpha 维度） | 排队 |
| v0.5.0 | 动画解析/播放（先走跑攻待四动作） | 排队 |
| v0.6.0 | 特效解析/播放（单独立项） | 排队 |
| v0.7.0 | 地形解析/真实地图 | 排队 |
| v0.8.0 | 1.2 万未知数据块分类/解析 | 排队 |
| v1.0 | 完整资源理解浏览器 | 终点 |

**关于「动画 / 着色器还没搞定」的口径**：这两项按三层账都属于第 2 层（解析），
状态是「格式还没看懂」，不是「文件没拿到」——字节全在 pak 里，随时可取。
- **骨骼动画**：`.ani` 容器已解（信封 + 41 个 bip01_* 骨架名），但**关键帧数据未解**，
  排在 v0.5.0。当前工作台的「组成成员」里能看到 .ani 名单，点不出播放。
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

`resources.db`（145MB）不入库，需要用 `catalog` 的建库工具重新索引客户端：

```bash
# 详见 tlbb-explorer/crates/core/src/bin/ 下的 catalog 相关 bin
cargo run --release --bin <catalog 建库 bin> -- --root <客户端根> --out .scratch/resources.db
```

建完后**务必跑基线核对**（等级分布是冻结值）：

```bash
cargo run --release --bin catalog_baseline
# 期望：A20 / B2581 / C10479 / D0
# 组 13080 / 成员 48122 / 资源 105327
```

对不上就说明索引方式和当初不同，**先查清楚再继续**，不要改冻结值。

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

# mesh 夹具：用工作台「浏览」视图导出这两个同名文件到 crates/core/tests/
#   w1351_model_emiter_lf002.mesh
#   w1351_model_emiter_lf004.mesh
```

### 6. 环境变量（可选）

```
TLBB_ROOT=<客户端根>        # 默认 D:/TLGL
TLBB_DB=<resources.db 路径> # 默认 <root>/.scratch/resources.db
```

> 部分 `bin/` 下的开发期工具把 `D:/TLGL` 写成了默认值（历史原因），用 `--root` /
> `--db` / `--out` 覆盖即可，不影响正常使用。

---

## 当前进度：M3-0 地图灰模

**方向已锁**：先做地图灰模浏览器，不修 84.4%、不追贴图。

链已闭合：

```
.scene（物件清单）→ 网格名 → 已有 mesh 解析器 → WebGL 灰模
```

`.scene` 格式**已解**（全量 11,933 文件独立复算）：

```
偏移 0x00  u32  n_records    记录数（★会被低估，尾部还有附加段）
偏移 0x04  u32  tag          753 / 749 / 605 / 592 / 596 / 601 / 324 / 957
偏移 0x08  u32  zero

base   = 12        恒定，与 tag 无关
stride = tag + 8   753→761、749→757、605→613、592→600
记录   := [64B 列主序仿射矩阵] [名字区，长度 = stride-64，名字起点恒为 64]
平移在 m[12], m[13], m[14]；floor(m[12]/32)、floor(m[14]/32) 对上格子文件名
```

详细分派与验收标准见 `.scratch/M3-0_地图灰模_分派规格.md`。

**第一版明确不做**：地形、贴图、光照、碰撞、寻路、中文地图名。

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
