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

  stats: null,
  scanned: 0,
  total: 0,
  ready: false,

  selected: 0,

  health: null,
  healthBusy: false,
};

// ---- 界面状态持久化 ----
// 桌面工具的常识：昨天看到一半的东西，今天打开还在。只存用户摆出来的
// 筛选/选中，不存运行数据（stats/health 每次都要重算，存了反而旧）。
const KEY = "tlbb-explorer-ui";
const PERSIST_KEYS = ["query", "kind", "scenario", "grade", "onlyImage", "named", "selected", "mapMode"];

export function loadState() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "null");
    if (!saved || typeof saved !== "object") return;
    for (const k of PERSIST_KEYS) if (k in saved) state[k] = saved[k];
  } catch {
    /* 存坏了就当没存过，默认值接管 */
  }
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
