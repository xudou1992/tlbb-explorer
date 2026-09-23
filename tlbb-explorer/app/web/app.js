// 入口：把模块接起来、把事件接上、把首屏跑起来。业务逻辑不住在这里。
//
// 前端刻意不依赖任何打包器或三方库：Tauri 把接口注入到 window.__TAURI__，
// 中文检索、解码、判定全部在 Rust 侧完成，这里只负责把结果摆出来。

import { el } from "./ui.js";
import * as api from "./api.js";
import { state } from "./state.js";
import { refresh, refreshStats, resetFilters, toggleUnnamed } from "./list.js";
import { openHealth, closeHealth } from "./health.js";

let searchTimer = 0;
el("q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.query = e.target.value.trim();
    refresh();
  }, 260);
});
el("onlyImage").addEventListener("change", (e) => {
  state.onlyImage = e.target.checked;
  refresh();
});
el("reset").addEventListener("click", resetFilters);
el("unnamed").addEventListener("click", toggleUnnamed);
el("openHealth").addEventListener("click", openHealth);
el("closeHealth").addEventListener("click", closeHealth);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeHealth();
});

// Rust 侧每读完一批广播一次：界面因此能边读边用，但用户正在操作时不打断。
// 广播在 ready 之后就停了，所以最后一发如果撞上"正在操作"的抑制窗，必须补一次，
// 否则列表会永久停在预热中途的条数。
let lastAction = 0;
let afterReadyRefreshed = false;
const touched = () => (lastAction = Date.now());
["input", "click", "keydown", "change"].forEach((t) => document.addEventListener(t, touched, true));
api.onReading(async () => {
  await refreshStats();
  const idle = Date.now() - lastAction > 1600;
  if (idle) refresh();
  // 广播在 ready 之后就停了：最后一发如果被"正在操作"抑制掉，就再也没人补，
  // 列表会永久停在预热中途的条数。读完之后强制补一次。
  if (state.ready && !afterReadyRefreshed) {
    afterReadyRefreshed = true;
    if (!idle) refresh();
  }
});

refreshStats();
refresh();

if (!api.hasShell) {
  el("lead").textContent = "这是网页外壳，需在桌面端里运行才会读到客户端数据。";
}
