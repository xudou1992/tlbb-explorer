// 所有跨 IPC 的调用集中在这一处：其余模块不认识 Tauri，只认这些函数。
// 参数名要和 Rust 侧的命令签名对齐（Tauri 把 camelCase 的 JS 参数映射到 snake_case）。

const tauri = window.__TAURI__;

export const hasShell = Boolean(tauri && tauri.core);

async function call(cmd, args) {
  if (!hasShell) throw new Error("这个界面要在桌面端里运行才会读到客户端数据");
  return tauri.core.invoke(cmd, args);
}

/// 后台每读完一批广播一次；没桌面端就当没有这回事。
export function onReading(fn) {
  if (!hasShell || !tauri.event) return;
  tauri.event.listen("reading", fn).catch(() => {});
}

export const stats = () => call("stats");
export const listGroups = (filter) => call("list_groups", { filter });
export const cardDetail = (gid) => call("card_detail", { gid });
export const assetInspect = (gid) => call("asset_inspect", { gid });
export const preview = (hash) => call("preview", { hash });
export const meshData = (name, hash) => call("mesh_data", { name, hash: hash || null });
export const refHealth = (danglingLimit) => call("ref_health", { danglingLimit });
/// 容器与清单的缺口：pak 索引里有多少条、清单登记了多少条、差多少条没进清单。
export const catalogGap = () => call("catalog_gap");
/// key 是 16 位编号或客户端原文名：悬空的名字没有编号，只能按名字反查。
export const citedBy = (key, limit) => call("cited_by", { key, limit });
/// 地图侧两个命令：清单 + 一张图的全部格子（一次回包，不逐个物件问）。
export const mapList = (limit) => call("map_list", { limit });
export const mapScene = (id) => call("map_scene", { id });
/// 列表缩略图专用：回包与 map_scene 逐字段一致，只是网格不带顶点流。
export const mapFootprint = (id) => call("map_footprint", { id });
/// 行缩略图两问：组里第一张真能解出来的图；解不出图再问几何投影。
/// 两个都可能如实回 null——「没图」本身就是一条真实回包。
export const groupPreview = (gid) => call("group_preview", { gid });
export const groupMeshOutline = (gid) => call("group_mesh_outline", { gid });
/// 贴图覆盖表：人工确认候选后写入 / 撤销。只写 .scratch 下的表，不碰原资源。
export const textureOverrideSet = (slotName, cfgPath, hash, note) =>
  call("texture_override_set", { slotName, cfgPath: cfgPath || null, hash, note: note || "" });
export const textureOverrideClear = (slotName, cfgPath) =>
  call("texture_override_clear", { slotName, cfgPath: cfgPath || null });
/// 批量候选的按需缩略图：全库批量缓存只存元数据，卡片先摆占位，再按候选自带的
/// 编号现解一张 256px 图。读不到如实回 null / 报错，前端保持占位。
/// 按编号、不按「第几名」：榜单出栈前会按综合分重排，名次从此不等于缓存里的
/// 下标——按名次取图就是拿 A 的纹样去摆 B 的卡，那是编造证据。
export const candidatePng = (hash) => call("candidate_png", { hash });
// ---- 浏览视图（第一屏）：打开一个 data → 文件夹树 → 预览 → 导出 ----
export const browsePaks = () => call("browse_paks");
export const browseTree = (pakName) => call("browse_tree", { pakName });
export const browsePreview = (pakName, hash) => call("browse_preview", { pakName, hash });
/// hashes 传空数组表示整包导出。
export const browseExport = (pakName, hashes, dest) =>
  call("browse_export", { pakName, hashes, dest });
/// 详情面板「导出」：一次把这一组的文件导到目录。dest 传空串走默认
/// `<客户端根>/.scratch/exports/<组名>`，不必先选目录。
export const browseExportGroup = (gid, dest = "") =>
  call("browse_export_group", { gid, dest });
/// 骨架页：节点（名字 + 绑定位移）与同组动作清单。解不出的原因由后端原话带回。
export const skeletonView = (gid) => call("skeleton_view", { gid });
/// 动作页：一次拿整条动作的全部关键帧，前端拖游标本地取帧。
export const animationView = (gid, file) => call("animation_view", { gid, file });
/// 资产侧懒预热开关：只有进「资产」标签才触发后台预热（有缓存时秒级载入）。
export const startWarm = () => call("start_warm");
/// 全库批量试贴（贴图候选榜的原料）：问还差多少只模型、发起后台跑、听进度。
export const textureWarmStatus = () => call("texture_warm_status");
export const textureWarmStart = () => call("texture_warm_start", {});
/// 批量试贴的进度广播。没桌面端就当没有这回事（与 onReading 同一口径）。
export function onTextureWarming(fn) {
  if (!hasShell || !tauri.event) return;
  tauri.event.listen("textureWarming", fn).catch(() => {});
}
