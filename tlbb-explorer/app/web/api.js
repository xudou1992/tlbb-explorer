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
