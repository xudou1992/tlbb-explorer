// 清单与筛选：这一层只管数据，不碰界面。
// 数据来自 mesh2glb 导出的 manifest.json；缺的字段就是缺的，不补。

export const state = {
  assets: [],
  stats: null,
  failures: [],
  q: "",
  cat: "全部",
  slot: "全部",
  tri: "全部",
};

export async function loadManifest() {
  const r = await fetch("./model/manifest.json");
  if (!r.ok) throw new Error(`读不到清单 model/manifest.json（${r.status}）`);
  const doc = await r.json();
  state.assets = doc.assets || [];
  state.stats = doc.stats || {};
  state.failures = doc.failures || [];
  return doc;
}

export function categories() {
  const h = new Map();
  for (const a of state.assets) h.set(a.category, (h.get(a.category) || 0) + 1);
  return [...h.entries()].sort((x, y) => y[1] - x[1]);
}

const SLOT = { 全部: () => true, 单个材质槽: (a) => a.slots <= 1, "多个材质槽": (a) => a.slots > 1 };
const TRI = {
  全部: () => true,
  "1 千面以内": (a) => a.tris < 1000,
  "1 千 – 1 万面": (a) => a.tris >= 1000 && a.tris < 10000,
  "1 万面以上": (a) => a.tris >= 10000,
};

export function matches(a) {
  if (!SLOT[state.slot](a)) return false;
  if (!TRI[state.tri](a)) return false;
  if (state.cat !== "全部" && a.category !== state.cat) return false;
  const q = state.q.trim().toLowerCase();
  if (!q) return true;
  if (a.name.toLowerCase().includes(q)) return true;
  if ((a.dir || "").toLowerCase().includes(q)) return true;
  if ((a.path || "").toLowerCase().includes(q)) return true;
  return (a.tags || []).some((t) => t.toLowerCase().includes(q));
}

export function filtered() {
  return state.assets.filter(matches);
}

export function num(n) {
  return (n || 0).toLocaleString("zh-CN");
}

export function nice(name) {
  return String(name || "").replace(/^w1351_/, "");
}
