import io

p = r"D:\TLGL\.workbuddy\memory\2026-09-22.md"

note = """
## P3-E 资产证据浏览器 —— 第二刀：引用健康度 + 反向引用（已完成）

用户两轮修正方向后的最终目标：不做「关系网络」，做「证据浏览器」——
不问「谁跟谁共享」，只问「谁引用了谁、哪里真的落到文件、哪里悬空、有多少依据」。

### 后端（新增，全部只读）
- catalog/sqlite.rs：RefHealth / RefExt / DanglingName 三个结构 + 五个查询：
  ref_health()（总数/已解析/悬空名/有引用资产/按后缀分组）、top_dangling()、
  cited_by(hash, limit)、assets_citing_resolved()、top_cited(limit)。
- catalog/mod.rs：导出新类型。
- app/src-tauri/src/data.rs：ref_view() / cited_by() / top_cited() 三个视图层方法，
  外加 pct_of() / ext_of() 两个纯函数（百分比与后缀只在后端算一次，前端不重算）。
- app/src-tauri/src/lib.rs：新增 ref_health / cited_by 两个 Tauri command；
  --probe 扩展为打印整份健康度回包，命令行就能核对面板数字。
- app/src-tauri/src/model.rs：RefExtView / DanglingView / RefView /
  CitationView / CitedByView。

### 前端
- web/index.html：左栏加 #views 视图切换（资产 / 引用健康度），
  #assetControls 包裹原过滤区；中栏加 #health 容器。
- web/app.js：healthHtml() 渲染四张概览卡 + 按类型表格 + 引用最多/悬空最多两列；
  showCitations() 反查某名字被哪些文件提到；paintView() / setView() 管视图切换；
  loadHealth() 带缓存（切回来只重挂事件，不重查）。
- web/style.css：.views / .view 切换按钮、.hl-cards / .hl-card、.hl-table、
  .mini-bar、.refs.cite 等。

### 关键数据（2026-09-22 基线，与 SQLite 直查逐项一致）
- 引用 98,504 · 已解析 61,408（62%）· 悬空名字 14,377 · 有引用资产 20,576/21,352
- 按后缀：.mtl 38,694→37,779（98%）、.tga 30,585→25（0%）、.ani 15,622→11,294（72%）、
  .mesh 9,316→8,549（92%）、.ske 4,210→3,734（89%）、.png 36→0、.dds 14→0、.pu 7→7
- 被提到最多且能对上：template_default.mtl 2,933 处
  （实测被 mobile_maps_source/ 下数百份 .mtl 文件引用）
- 悬空最多：w1351_point_l007.tga 347 次

### 三个自己抓出来并修掉的口径坑
1. refs.kind 是文件后缀，不是中文类名（我先前误判 ref_kind_word 坏了）。
   后缀→中文由 ref_kind_word("x" + ext) 处理，本身正确；但 .tga / .png / .dds
   都会显示成「贴图」，表格必须把 ext 一起显示，否则同一句话「贴图」出现三次。
2. dangling.n_refs（引用条目数）与「对不上的名字数」不是同一单位，
   面板分两列显示并注明不可相加。
3. cited_by 原本 ORDER BY from_path 会把空路径排在前面（空串小于字母），
   前 200 条可能全是无路径的组内边。改成 ORDER BY (from_path = '') ASC, from_path。

### 验证
- cargo test -p tlbb-core → 132 passed / 0 failed / 4 ignored（与改动前一致，无回归）
- --probe 输出与 Python 直查 SQLite 五项数字逐项相同（无视图层/基表偏差）
- node --check app.js 通过；web/build.mjs 构建通过

### 沙箱坑（本轮新增）
- Bash 工具内 python -c 里若出现反引号，会被 bash 当命令替换执行掉，
  写进文件的内容会被掏空。写中文长文本一律用 Write 工具落 .py 再由 python 执行。
- Bash 工具传 /d/... 路径会被拼成 d:\\d\\...；必须用 Windows 绝对路径。

### 待办
- ① 已完成（本轮）。② 反查已作为卡片/健康度增强落地。
- ③ 启动速度：冷启动已从 114.6s 降到 ~2-3s（前一轮覆盖索引 + ANALYZE 的成果）。
- Signals 口径统一（工作台 vs 基线两套构造）仍未做。
"""

with io.open(p, "a", encoding="utf-8") as f:
    f.write(note)
print("ok")
