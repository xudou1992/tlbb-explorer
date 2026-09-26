// 入口：把模块接起来、把事件接上、把首屏跑起来。业务逻辑不住在这里。
//
// 前端刻意不依赖任何打包器或三方库：Tauri 把接口注入到 window.__TAURI__，
// 中文检索、解码、判定全部在 Rust 侧完成，这里只负责把结果摆出来。

import { el } from "./ui.js";
import * as api from "./api.js";
import { state, loadState, saveState } from "./state.js";
import { refresh, refreshStats, resetFilters, toggleUnnamed, moveSelect } from "./list.js";
import { openHealth, closeHealth } from "./health.js";
import { openMap, closeMap } from "./map.js";
import { clearDetail, showDetail } from "./detail.js";

// ---- 图片放大（lightbox），壳与事件全在这一处 ----
// 预览格子里是 160px 的缩略图，看不清一张服装图标就等于任务没完成。
// 缩略图先顶上，后端按 hash 现解的大图回来就替换；figure 没带 hash
// （老回包 / 解码失败条目）就直接放大现有图，两档都比格子里的强。
// 放在入口层而不是 detail.js：pvGrid 的内容每次重画都会被换掉，
// 监听器只能挂在容器上，而容器事件归全局 UI 管。
function openLightbox(src, label, hash) {
  el("lightboxImg").src = src;
  el("lightboxCap").textContent = label || "";
  el("lightbox").hidden = false;
  if (!hash) return;
  api
    .preview(hash)
    .then((img) => {
      if (el("lightbox").hidden || !img || !img.url) return;
      el("lightboxImg").src = img.url;
    })
    .catch(() => {
      /* 大图没拿到就继续放缩略图，不打断 */
    });
}
function closeLightbox() {
  el("lightbox").hidden = true;
  el("lightboxImg").src = "";
}
el("pvGrid").addEventListener("click", (e) => {
  const fig = e.target.closest("figure.pv");
  if (!fig) return;
  const img = fig.querySelector("img");
  if (img) openLightbox(img.src, fig.querySelector("figcaption")?.textContent || "", fig.dataset.hash || null);
});
el("lightbox").addEventListener("click", closeLightbox);

// 上次的筛选/选中/地图视图先恢复，再谈别的——桌面工具的常识：
// 昨天看到一半的东西，今天打开还在。
loadState();

let searchTimer = 0;
el("q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.query = e.target.value.trim();
    saveState();
    refresh({ top: true });
  }, 260);
});
el("onlyImage").addEventListener("change", (e) => {
  state.onlyImage = e.target.checked;
  saveState();
  refresh({ top: true });
});
el("reset").addEventListener("click", () => {
  resetFilters();
  clearDetail();
});
el("unnamed").addEventListener("click", toggleUnnamed);
el("openHealth").addEventListener("click", openHealth);
el("closeHealth").addEventListener("click", closeHealth);
el("openMap").addEventListener("click", openMap);
el("closeMap").addEventListener("click", closeMap);

// ---- 键盘 ----
// Esc 逐层退：先关最上层的东西（lightbox → 浮层），都不开着才轮到清搜索框。
// 以前一键全关还会把焦点扔到 body 上，键盘用户得从头再 Tab 一遍。
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!el("lightbox").hidden) {
      closeLightbox();
      return;
    }
    if (!el("health").hidden) {
      closeHealth();
      el("openHealth").focus();
      return;
    }
    if (!el("maps").hidden) {
      closeMap();
      el("openMap").focus();
      return;
    }
    if (e.target === el("q") && el("q").value) {
      el("q").value = "";
      state.query = "";
      saveState();
      refresh({ top: true });
    }
    return;
  }
  // Ctrl+F / /：聚焦搜索。斜杠只在非输入框里生效，免得把斜杠打字吞了。
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
    e.preventDefault();
    el("q").focus();
    el("q").select();
    return;
  }
  if (e.key === "/" && !/input|textarea|select/i.test(e.target.tagName)) {
    e.preventDefault();
    el("q").focus();
    return;
  }
  // ↑↓ 在列表里选行（输入框里正常移动光标）。
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !/input|textarea|select/i.test(e.target.tagName)) {
    if (moveSelect(e.key === "ArrowDown" ? 1 : -1)) e.preventDefault();
  }
});

// Rust 侧每读完一批广播一次：界面因此能边读边用，但用户正在操作时不打断。
// 滚轮/滚动也是「正在操作」——否则用户安静地翻列表，每 700ms 被程序拽一下。
// 广播在 ready 之后就停了，所以最后一发如果撞上"正在操作"的抑制窗，必须补一次，
// 否则列表会永久停在预热中途的条数。
let lastAction = 0;
let afterReadyRefreshed = false;
const touched = () => {
  lastAction = Date.now();
  saveState(); // 300ms 合并写：chips 连点、键入、翻列表都汇成一次
};
["input", "click", "keydown", "change", "wheel", "scroll"].forEach((t) =>
  document.addEventListener(t, touched, { capture: true, passive: true }),
);
api.onReading(async () => {
  await refreshStats();
  restoreDetail();
  const idle = Date.now() - lastAction > 1600;
  if (idle) refresh();
  // 广播在 ready 之后就停了：最后一发如果被"正在操作"抑制掉，就再也没人补，
  // 列表会永久停在预热中途的条数。读完之后强制补一次。
  if (state.ready && !afterReadyRefreshed) {
    afterReadyRefreshed = true;
    if (!idle) refresh();
  }
});

// 上次选中的资产：库就绪后把它请回来（预热没完成时资产还读不到，急不得）。
let restored = false;
function restoreDetail() {
  if (restored || !state.selected) return;
  restored = true;
  showDetail(state.selected);
}

refreshStats().then(restoreDetail);
refresh();

if (!api.hasShell) {
  el("lead").textContent = "这是网页外壳，需在桌面端里运行才会读到客户端数据。";
}
