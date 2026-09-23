# 天龙八部·归来 — 资产理解工作台（Tauri 2 外壳）

三栏桌面应用：左检索过滤 · 中资产卡片 · 右证据链。只读浏览 `D:\TLGL\data*.pak` 与
`D:\TLGL\.scratch\resources.db`，不写任何游戏文件；本目录内也不留缓存。

## 目录

```
app/
├── package.json          零依赖：只有 build / icons 两条脚本
├── web/                  前端（原生 ES module，无框架、无打包器）
│   ├── index.html        三栏骨架 + 7 类类型轮廓
│   ├── app.js            取数、渲染、懒加载缩略图
│   ├── style.css         深色工作台外观
│   └── build.mjs         把 web/ 原样拷进 web/dist/（供 Tauri 内嵌）
├── scripts/make-icons.mjs 手写 PNG/ICO 生成，离线
└── src-tauri/
    ├── Cargo.toml        独立 workspace（刻意不挂到 D:\TLGL\tlbb-explorer 的 workspace 上）
    ├── tauri.conf.json
    ├── capabilities/default.json   只给 core:default，不开文件/网络/进程能力
    ├── icons/
    └── src/
        ├── main.rs       入口，--probe 走自检
        ├── lib.rs        #[tauri::command] 与 Builder
        ├── data.rs       只读数据层：清单查询 + 容器现场解码 + 后台预热
        ├── model.rs      过 IPC 的视图模型（键是代码，值才是给人看的中文）
        └── present.rs    展示口径：场景 / 占位轮廓 / 名称 / 等级说法
```

## 构建与运行

```bash
cd app
npm run build          # web -> web/dist（改了前端必须重跑，资源是编译期内嵌的）
cargo build --manifest-path src-tauri/Cargo.toml
./target/debug/tlbb-shell.exe            # 打开窗口
./target/debug/tlbb-shell.exe --probe 曹霜  # 无窗口自检：读库、解码、检索
```

`cargo install tauri-cli` 或 `npx @tauri-apps/cli` 不是必需的：没有 devUrl 时
`tauri dev` 与上面的 build + 直接跑 exe 等价。

数据位置可用环境变量覆盖（默认 `TLBB_ROOT=D:/TLGL`、
`TLBB_DB=D:/TLGL/.scratch/resources.db`）。

## 界面口径

- 中文检索在 Rust 侧完成（`tlbb_core::catalog::search::query_keys`），输入「曹霜」会
  同时按 `caoshuang` 比对，命中 `w1351_boss_caoshuang`。
- 名称一律按客户端原文展示，不翻译、不编中文名。
- 约 83% 的资产没有可解析图形：卡片先放 7 类类型轮廓（character / beast / building /
  effect / panel / item / node），真从容器里解出像素才替换成图，解不出就写「暂无可解析图形」。
- 证据等级 A/B/C/D 与缺口全部来自 `catalog::evidence`，主体是否「能打开」以现场读回并
  展开成功为准。
- 编号、所在数据容器、容器内位置、内容指纹、判定依据等技术字段收在右栏「技术信息」折叠区。

## 命令一览（前端 `window.__TAURI__.core.invoke`）

| 命令 | 作用 |
| --- | --- |
| `list_groups(filter)` | 左栏条件（关键词 / 用途 / 类别 / 证据等级 / 只看能出图）→ 中栏卡片分页 |
| `search(query, limit)` | 只做中文检索的快捷入口，内部同样走 `list_groups` 的过滤 |
| `card_detail(gid)` | 右栏证据链：结论、缺口、引用名称及状态、附属文件、技术信息 |
| `preview(hash)` | 现场解出一个资源的图形，返回 `data:` URL；解不出返回 null |
| `group_preview(gid)` | 整组里第一个真能解出来的图（缩略图用） |
| `stats()` | 总数、已读进度、各筛选项计数 |
| 事件 `reading` | 后台预热每批广播一次，界面边读边可用 |
