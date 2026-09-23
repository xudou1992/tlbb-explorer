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

  stats: null,
  scanned: 0,
  total: 0,
  ready: false,

  selected: 0,

  health: null,
  healthBusy: false,
};
