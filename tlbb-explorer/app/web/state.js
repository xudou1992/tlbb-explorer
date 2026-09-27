// 全局只有一份：筛选条件 + 库状态 + 当前选中的资产。
// 请求序号不在这里——每个模块各有一把锁（lib/seq.js），因为它们各自作废各自的迟到回包。

export const state = {
  query: "",
  kind: "全部",
  scenario: "全部",
  grade: "全部",
  onlyImage: false,
  // 默认只列有名字的组：既没名字又没路径的那批只能靠 16 位编号区分，
  // 摆进首屏就是一墙编号。看它们要走左栏那个显式入口。
  named: true,
  // 地图浏览器的上一次视图（"gray" | "top"）：重启后回到用户熟悉的那一面。
  mapMode: "gray",
  // 主视图（"browse" | "assets"）：软件第一屏是「打开 data → 树 → 预览 → 导出」。
  view: "browse",
  // 浏览视图上一次打开的 pak：重启后接着看。
  browsePak: "",

  stats: null,
  scanned: 0,
  total: 0,
  ready: false,

  selected: 0,

  // 最近一次的 asset_inspect 回包 + 算好的展示状态。关系网浮层和右栏都按它铺图，
  // 点开时不再重查一遍——同一份数据铺两处，口径天然一致。
  lastInspect: null,
  lastState: null,

  health: null,
  healthBusy: false,
};

// ---- 界面状态持久化 ----
// 桌面工具的常识：昨天看到一半的东西，今天打开还在。只存用户摆出来的
// 筛选/选中，不存运行数据（stats/health 每次都要重算，存了反而旧）。
const KEY = "tlbb-explorer-ui";
const PERSIST_KEYS = ["query", "kind", "scenario", "grade", "onlyImage", "named", "selected", "mapMode", "view", "browsePak"];

export function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (!saved || typeof saved !== "object") return;
    for (const k of PERSIST_KEYS) if (k in saved) state[k] = saved[k];
    // 老存档没有 view/browsePak 字段：上面的循环不会碰它们，默认值接管——
    // 这正是默认值存在的意义。但已写入的 view 必须收窄到两个合法值：首屏
    // 分支和顶栏进度口径都直接吃它，一个坏值（旧版本写脏 / 手改）会让两处各说各话。
    state.view = normalizeView(state.view);
    // selected 是资产编号：坏值会让启动恢复去查一条不存在的资产。
    state.selected = Number(state.selected);
    if (!Number.isFinite(state.selected) || state.selected < 0) state.selected = 0;
    // browsePak 只参与字符串全等比较，非字符串一律当作没选过。
    if (typeof state.browsePak !== "string") state.browsePak = "";
  } catch {
    /* 存坏了就当没存过，默认值接管 */
  }
}

/// view 只有两个合法值，单独拎出来是为了能被 node --test 钉住：
/// 非法值一律落回默认第一屏「浏览」，绝不猜。
export function normalizeView(v) {
  return v === "assets" ? "assets" : "browse";
}

let saveTimer = 0;
export function saveState() {
  clearTimeout(saveTimer);
  // 300ms 合并：chips 连点、键入、翻列表都是一串事件，逐个写就太吵了。
  saveTimer = setTimeout(() => {
    try {
      const out = {};
      for (const k of PERSIST_KEYS) out[k] = state[k];
      localStorage.setItem(KEY, JSON.stringify(out));
    } catch {
      /* 存不进（无痕等）就算了，这只是锦上添花 */
    }
  }, 300);
}
