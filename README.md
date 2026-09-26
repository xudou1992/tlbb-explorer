# TLBB Explorer

天龙八部（TLBB）客户端资源浏览器 —— 让人能看懂客户端里有什么。

> **本仓库只带源码与结论，不带客户端二进制。** 客户端 `data*.pak`（6GB）与 Rust
> 构建目录合计 40GB+，全部排除在版本控制之外。换机后按「首次运行」重建即可。

---

## 这是什么

一个只读的客户端资源浏览器/解包预览器。**不做资产知识图谱**，只回答
「客户端里有什么、长什么样」。三个模式：

- **浏览 / 预览 / 导出**：PNG、OBJ、FBX、JSON
- **分析模式**（开发者选项）：refs / dangling / evidence

### 路线图

| 版本 | 内容 | 状态 |
|---|---|---|
| v0.1 | 资源清单 + 引用健康度 | ✅ |
| v0.2 | mesh 稳定（几何解析 + WebGL 灰模） | ✅ |
| **v0.3** | **地图灰模浏览器** | ← **当前** |
| v0.4 | 84.4% 体验修复 + 材质关系 | 排队 |
| v0.5 | 地形 | 未开始 |
| v0.6 | shader | 未开始 |
| v0.7 | 骨骼动画 | 未开始 |
| v0.8 | 特效 | 未开始 |

---

## 项目纪律（改代码前必读）

这五条是硬规矩，违反它们比写出 bug 更严重：

1. **没解出像素不显图。** 绝不拿同目录的图顶替。
2. **名称一律客户端原文。** 不翻译、不编显示名。地图没有中文名表，所以只显示
   `w1351_ll_dl_003` 这种原文 ID。
3. **命名推断 ≠ 引用。** same-stem / model-part 只进 `relations`，不进 `refs`。
4. **数据层英文键，中文只在展示层映射。**
5. **悬空引用显示「缺」，不编造。** `resources.db` 一律只读。

### 已经推翻、不要再回头的结论

- ❌ 2.4 万无名贴图**不是**解析漏了 —— 名字唯一来源 JRPC 已穷尽
- ❌ 「共享」概念不存在
- ❌ 全自动资产恢复不成立
- ❌ `.tga` 断链是**客户端设计使然**（path 从未入命名表），工具无错

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
└── .workbuddy/memory/                # 项目长期记忆与工作日志
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

### 5. 环境变量（可选）

```
TLBB_ROOT=<客户端根>        # 默认 D:/TLGL
TLBB_DB=<resources.db 路径> # 默认 <root>/.scratch/resources.db
```

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
