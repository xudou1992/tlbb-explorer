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
import { initBrowse, showTab } from "./browse.js";
import { initExportProgress } from "./exportProgress.js";
import { initRelations, openRelations, closeRelations } from "./relations.js";

// ---- 图片放大（lightbox），壳与事件全在这一处 ----
// 预览格子里是 160px 的缩略图，看不清一张服装图标就等于任务没完成。
// 缩略图先顶上，后端按 hash 现解的大图回来就替换；figure 没带 hash
// （老回包 / 解码失败条目）就直接放大现有图，两档都比格子里的强。
// 放在入口层而不是 detail.js：pvGrid 的内容每次重画都会被换掉，
// 监听器只能挂在容器上，而容器事件归全局 UI 管。
// 一次灯箱一个令牌：只有当前这次打开的回包才准写画面。
// 曾经 A 的大图还在路上、用户已经关掉又开了 B，A 迟到的回包会把 B 的画面
// 顶掉，而标题还写着 B——图和名字说的不是同一个东西，比不放大图更误导人。
let lightboxSeq = 0;
function openLightbox(src, label, hash) {
  const my = ++lightboxSeq;
  el("lightboxImg").src = src;
  el("lightboxCap").textContent = label || "";
  el("lightbox").hidden = false;
  if (!hash) return;
  api
    .preview(hash)
    .then((img) => {
      if (my !== lightboxSeq) return; // 已经不是这一张了
      if (el("lightbox").hidden || !img || !img.url) return;
      el("lightboxImg").src = img.url;
    })
    .catch(() => {
      /* 大图没拿到就继续放缩略图，不打断；换张了同样不动 */
    });
}
function closeLightbox() {
  lightboxSeq++; // 作废在途回包：关灯之后迟到的大图不该把画面又点亮
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
// 恢复的搜索词必须看得见。血泪教训：state.query 恢复了、输入框却是空的，
// 用户看到的就是「啥也没搜却 0 条」的隐形筛选——比报错还坑人。
el("q").value = state.query || "";

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
initRelations();

// ---- 主视图标签：浏览（第一屏）/ 资产检索 ----
// 资产侧懒预热：只有真的用到「资产」标签才开始后台读取（有缓存则秒级载入）。
// 浏览第一屏不依赖资产库，启动时也不替用户付这份成本。
let assetsInited = false;
function initAssets() {
  if (assetsInited) return;
  assetsInited = true;
  // 预热开关是懒预热这版新增的命令，旧后端/网页外壳可能没有它——但 stats 与
  // list_groups 本身也会触发预热，这里吞掉的是「开关不存在」，不是读取失败；
  // 真正的失败由 refreshStats / refresh 各自的可见文案兜底，不会静默死掉。
  api.startWarm().catch(() => {});
  refreshStats().then(restoreDetail);
  refresh();
}
el("tabAssets").addEventListener("click", initAssets);

// ---- 跳转链接（skip-link）----
// 旧结构写死 href="#list"，那个 id 早就没了，点了等于没点；指向默认藏着的
// assetsView 又会让浏览首屏的跳转落空。跟着当前视图指：指到哪儿，哪儿就是主内容。
function aimSkipLink() {
  el("skipLink").href = `#${state.view === "assets" ? "assetsView" : "browseView"}`;
}

initBrowse();
initExportProgress();
// 瞄准要挂在 browse.js 的标签处理器之后：它先把 state.view 改掉，这里再读。
el("tabBrowse").addEventListener("click", aimSkipLink);
el("tabAssets").addEventListener("click", aimSkipLink);

if (state.view === "assets") {
  initAssets();
} else {
  // 还没预热也没载缓存，顶栏别挂着一句「正在读取…」的谎。
  el("progressText").textContent = "浏览不依赖资产库 · 「资产」标签用时才读取";
}
showTab(state.view); // loadState 已把 view 收窄到两个合法值
aimSkipLink();

// ---- 键盘 ----
// Esc 逐层退：先关最上层的东西（lightbox → 浮层），都不开着才轮到清当前视图的搜索框。
// 以前一键全关还会把焦点扔到 body 上，键盘用户得从头再 Tab 一遍。
// 清空要走各自的输入链路：补发 input，browse.js 的去抖监听才会把树画回整棵
// （只清值不发事件就只是字面清空，列表还停在搜索结果上）。
function clearBox(box) {
  box.value = "";
  box.dispatchEvent(new Event("input", { bubbles: true }));
}
// 聚焦当前视图的搜索框：资产是 q，浏览是 treeFilter。q 在浏览视图里藏在看不见
// 的资产视图中，聚焦它等于没反应；treeFilter 还没开出树时是藏着的，那就不动。
function focusSearchBox() {
  const box = state.view === "browse" ? el("treeFilter") : el("q");
  if (!box.hidden) {
    box.focus();
    if (typeof box.select === "function") box.select();
  }
}
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
    if (!el("relations").hidden) {
      closeRelations();
      return;
    }
    if (e.target === el("treeFilter") && el("treeFilter").value) {
      clearBox(el("treeFilter"));
      return;
    }
    if (e.target === el("q") && el("q").value) {
      clearBox(el("q"));
      state.query = "";
      saveState();
      refresh({ top: true });
    }
    return;
  }
  // Ctrl+F / /：聚焦当前视图的搜索框。斜杠只在非输入框里生效，免得把斜杠打字吞了。
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
    e.preventDefault();
    focusSearchBox();
    return;
  }
  if (e.key === "/" && !/input|textarea|select/i.test(e.target.tagName)) {
    e.preventDefault();
    focusSearchBox();
    return;
  }
  // ↑↓ 在资产列表里选行（输入框里正常移动光标）。只在资产视图生效：
  // 浏览视图里按方向键不该去「选中」藏在另一个视图里的行，把详情画进看不见的面板。
  if (
    state.view === "assets" &&
    (e.key === "ArrowDown" || e.key === "ArrowUp") &&
    !/input|textarea|select/i.test(e.target.tagName)
  ) {
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
  // 资产侧还没被点开（懒预热没启动）：用户看到的是浏览首屏，顶栏那句话是
  // 「浏览不依赖资产库 · 「资产」标签用时才读取」。这时广播不该来改动它——
  // 动了就等于替用户启动了资产链路，还把详情画进藏着的视图里。
  // 点开「资产」标签由 initAssets() 自己拉一遍 stats/list，不缺这一发。
  if (!assetsInited) return;
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
// 只在资产链路里恢复（initAssets / onReading）。曾经模块末尾还无条件跑过一遍
// refreshStats()+refresh()：view=browse 启动也会调 stats/list_groups，后端就把
// 懒预热当启动了——顶栏「浏览不依赖资产库」成了谎话，上次的资产详情还会被
// 画进还藏着的资产视图里。所以这里绝不能再有顶层调用。
let restored = false;
function restoreDetail() {
  if (restored || !state.selected) return;
  restored = true;
  showDetail(state.selected);
}

if (!api.hasShell) {
  el("lead").textContent = "这是网页外壳，需在桌面端里运行才会读到客户端数据。";
}
