# M2-2: Mesh Viewer Integration — 完成报告

**日期**: 2026-09-23  
**状态**: ✅ 代码集成完成（待宿主环境验证）

---

## 已完成的修改

### 1. 修正后端接口参数 (`app.js`)

**问题**: 前端调用 `mesh_data` 时使用 `hash` 参数，但后端 Rust 函数签名要求 `name: String`

**修改**: `loadMeshPreview()` 函数
```javascript
// 前：调用 invoke("mesh_data", { hash })
// 后：调用 invoke("mesh_data", { name })
async function loadMeshPreview(name, displayName) {
  // ... 使用 name 而非 hash 调用后端
  const data = await invoke("mesh_data", { name });
  // 移除了对 data.ok 的检查，因为后端直接返回 MeshData 或 Err
}
```

**位置**: `D:\TLGL\tlbb-explorer\app\web\app.js` 行 951-977

---

### 2. 修正预览按钮绑定 (`app.js`)

**问题**: 按钮点击处理器传递 `hash` 和 `name` 两个参数，但 `loadMeshPreview` 已改为只需 `name`

**修改**: `bindMeshPreviewButtons()` 函数
```javascript
// 前：
btn.onclick = () => {
  const hash = btn.dataset.hash;
  const name = btn.dataset.name;
  loadMeshPreview(hash, name);
};

// 后：
btn.onclick = () => {
  const name = btn.dataset.name;
  loadMeshPreview(name, name);
};
```

**位置**: `D:\TLGL\tlbb-explorer\app\web\app.js` 行 979-987

---

### 3. 修正按钮 HTML 生成 (`app.js`)

**问题**: 模型详情视图中的"预览网格"按钮生成时检查 `b.mesh.hash` 并传递 `data-hash` 属性，但后端不需要 hash

**修改**: `inspMdlHtml()` 中的按钮生成逻辑
```javascript
// 前：
const meshBtn = b.mesh && b.mesh.resolved && b.mesh.hash
  ? ` <button ... data-hash="${esc(b.mesh.hash)}" data-name="${esc(b.mesh.name)}">预览网格</button>`
  : "";

// 后：
const meshBtn = b.mesh && b.mesh.resolved
  ? ` <button ... data-name="${esc(b.mesh.name)}">预览网格</button>`
  : "";
```

**位置**: `D:\TLGL\tlbb-explorer\app\web\app.js` 行 787-789

---

### 4. 移除 ES6 模块语法 (`index.html`)

**问题**: `mesh-viewer.js` 使用 ES5 class 语法但被标记为 `type="module"`，导致全局 `MeshViewer` 无法访问

**修改**: 
```html
<!-- 前：-->
<script type="module" src="mesh-viewer.js"></script>

<!-- 后：-->
<script src="mesh-viewer.js"></script>
```

**位置**: `D:\TLGL\tlbb-explorer\app\web\index.html` 行 152

---

## 技术核对

### 后端接口确认
- ✅ 函数签名: `async fn mesh_data(app: State<'_, Arc<AppData>>, name: String) -> Result<MeshData, String>`
- ✅ 返回类型: `MeshData` 包含 `positions: Vec<[f32; 3]>`, `indices: Vec<u16>`, `normals: Vec<[f32; 3]>` 等字段
- ✅ 无需 `ok` 包装：成功时直接返回 `MeshData`，失败时 Tauri 自动转换为 rejected promise

### 前端 WebGL Viewer
- ✅ `MeshViewer` 类已实现完整的 WebGL 渲染管线（shader、buffer、matrix math）
- ✅ `loadMesh(data)` 方法接受的数据结构与后端返回的 `MeshData` 匹配
- ✅ 交互已实现：鼠标拖拽旋转、滚轮缩放、双击重置
- ✅ 自动计算边界框并调整相机距离

### UI 集成
- ✅ 初始化：`initMeshViewer()` 在页面加载时调用（行 1000）
- ✅ 显示/隐藏：`showMeshViewer()` / `hideMeshViewer()` 控制面板可见性
- ✅ 状态提示：`showMeshViewerState()` / `hideMeshViewerState()` 处理加载状态
- ✅ 按钮绑定：`bindMeshPreviewButtons()` 在 `selectInsp()` 后调用（行 656）

---

## 无法在当前环境验证的原因

Linux VM 缺少 Rust 工具链：
```bash
$ cargo build
bash: cargo: command not found
```

Tauri 桌面应用需要在 Windows 宿主环境编译和运行。所有代码修改已完成，但需要在宿主的开发环境中：

1. 重新编译 Tauri 应用：
   ```cmd
   cd D:\TLGL\tlbb-explorer\app
   npm run tauri build
   ```

2. 运行并测试：
   - 启动应用
   - 切换到"模型 Inspector"视图
   - 选择一个包含网格的模型资产（如 `w1351_monster_xiyuqiezei`）
   - 点击"预览网格"按钮
   - 验证灰模正确加载并可交互

---

## 预期结果

点击"预览网格"后：
1. 网格预览面板从隐藏状态滑入
2. 显示"正在从客户端解析网格数据…"
3. 后端解析 `.mesh` 文件并返回几何数据
4. WebGL canvas 渲染灰色模型（diffuse + ambient + rim lighting）
5. 顶点/面数统计显示在标题下方
6. 用户可拖拽旋转、滚轮缩放、双击重置视角

---

## 文件清单

| 文件 | 修改行数 | 说明 |
|------|---------|------|
| `app/web/app.js` | 3 处编辑 | 修正接口调用、按钮绑定、HTML 生成 |
| `app/web/index.html` | 1 处编辑 | 移除 module 标记 |
| `app/web/mesh-viewer.js` | 无修改 | 已有完整实现 |
| `app/src-tauri/src/mesh_view.rs` | 无修改 | 已有后端命令 |

---

**备注**: 所有修改均遵循"不依赖打包器或三方库"的设计原则，保持与现有代码风格一致。
