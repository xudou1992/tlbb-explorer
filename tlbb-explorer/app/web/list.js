// 左栏筛选 + 中间列表。列表只回答「哪一条」，一条资产一行。
// 行首缩略图只有三态实话：组里真能解出像素→那张图；解不出但有网格→几何投影
// 的格子脚印（不是像素图，title 里说明）；两者都无→写「没图」。
// 不放类型轮廓那种装饰图：约 83% 的资产没有可解析的像素，占位图形只会让人
// 以为那是内容物。默认也不列未命名组：它们连路径都没记录，标题只能是 16 位编号。

import { el, esc, num, chips, line, errText } from "./ui.js";
import * as api from "./api.js";
import { state, saveState } from "./state.js";
import { showDetail } from "./detail.js";
import { listCount, railStats, rowMissChip } from "./lib/wording.js";
import { makeSeq } from "./lib/seq.js";

const ALL = { value: "全部", label: "全部" };
const seq = makeSeq();
/// 每页条数 = 一屏的十几倍：续载由触底观察器自动补，用户感知不到「页」。
const PAGE_SIZE = 300;
let offset = 0;
let loadingMore = false;
/// 当前列表里行的顺序（gid），键盘 ↑↓ 沿它走。
let visibleGids = [];

export function paintRail() {
  const s = state.stats;
  if (!s) return;
  // 筹码区只在「候选集」变化时重建：预热期每 700ms 一次 stats，重建会让
  // 正要点击的 chip 在指下消失。内容没变就只刷数字和选中态。
  const sig = JSON.stringify([s.kinds, s.scenarios, s.grades.map((g) => g.value)]);
  if (sig !== paintRail.sig) {
    paintRail.sig = sig;
    chips(el("kinds"), [ALL, ...s.kinds], state.kind, (v) => {
      state.kind = v;
      saveState();
      refresh({ top: true });
    });
    chips(el("scenarios"), [ALL, ...s.scenarios], state.scenario, (v) => {
      state.scenario = v;
      saveState();
      refresh({ top: true });
    });
    chips(el("grades"), [ALL, ...s.grades.map((g) => ({ value: g.value, label: `${g.value} ${g.label}`, count: g.count }))], state.grade, (v) => {
      state.grade = v;
      saveState();
      refresh({ top: true });
    });
  }
  // 分母写在标签里，措辞集中在 lib/wording.js（有测试盯着）。
  // 实算纠正过两处：「主体能打开的」恒等于顶栏那句「已读完 N 组」，是同一件事说两遍；
  // 「有贴图线索的」曾经写 25，其实真有线索的是 9,589 组，25 是**能对上**的组数。
  el("stats").innerHTML = railStats(s).map(([k, v]) => line(k, v)).join("");

  const btn = el("unnamed");
  btn.textContent = state.named ? `看未命名资产 ${num(s.unnamed)}` : "回到有名字的资产";
  btn.classList.toggle("on", !state.named);
}

function rowHtml(c) {
  const parts = (c.parts || [])
    .slice(0, 4)
    .map((p) => `<i>${esc(p.label)} ${num(p.count)}</i>`)
    .join("");
  const miss = c.refTotal - c.locatedTotal;
  const title = c.named ? c.name : "未命名资产";
  const sub = c.named ? c.subtitle : `${c.kind} · 客户端没留下名字和路径`;
  return `<button type="button" class="row-item${state.selected === c.gid ? " on" : ""}" data-gid="${c.gid}">
    <span class="thumb" data-gid="${c.gid}"></span>
    <span class="body">
    <span class="t"><strong title="${esc(title)}">${esc(title)}</strong><em class="grade g${esc(c.grade)}" title="${esc(c.gradeNote)}">${esc(c.grade)}</em></span>
    <span class="s">${esc(sub)}</span>
    <span class="c">${parts || `<i class="dim">没读到部件</i>`}<i>${num(c.memberTotal)} 文件</i>${
      rowMissChip(miss) ? `<i>${esc(rowMissChip(miss))}</i>` : ""
    }</span>
    </span>
  </button>`;
}

// ---- 行缩略图：进视口才取数，三态如实 ----
// 缓存按 gid 记住结果，筛选来回切重画列表后命中缓存只补画不重取。
// 上限 600 条（LRU，Map 插入序即使用序）：正常翻列表远碰不到，
// 但它必须有顶——base64 图串是内存大户，无顶就是「用一晚上越用越卡」。
const THUMB_CACHE_MAX = 600;
const thumbCache = new Map(); // gid → { state: "img"|"mesh"|"none"|"fail", image?, outline? }
/// 在途去重 + 并发闸：IntersectionObserver 会把视口里的行全推过来，
/// 没有闸的话快速一滚就是几十个解码任务同时打进去，IPC 队列被塞满。
const inflight = new Map(); // gid → Promise
let running = 0;
const waiting = [];
const MAX_PARALLEL = 6;

function schedule(job) {
  return new Promise((resolve) => {
    waiting.push({ job, resolve });
    pump();
  });
}
function pump() {
  while (running < MAX_PARALLEL && waiting.length) {
    const { job, resolve } = waiting.shift();
    running++;
    job().then((v) => {
      running--;
      resolve(v);
      pump();
    });
  }
}

function cacheSet(gid, entry) {
  if (thumbCache.has(gid)) thumbCache.delete(gid); // 先删再插，让 Map 序保持「最近用」
  thumbCache.set(gid, entry);
  if (thumbCache.size > THUMB_CACHE_MAX) {
    const oldest = thumbCache.keys().next().value;
    thumbCache.delete(oldest);
  }
}

let thumbIO = null;

/// 观察一批行。IO 常驻，只在整表重建时整体断开——追加行时旧的观察必须留着。
function observeThumbs(nodes) {
  if (!thumbIO) {
    thumbIO = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (en.isIntersecting) loadThumb(en.target);
      }
    });
  }
  for (const n of nodes) thumbIO.observe(n);
}
function resetThumbIO() {
  if (thumbIO) thumbIO.disconnect();
  observeThumbs(el("rows").querySelectorAll(".thumb"));
}

/// 把几何投影回包画成格子脚印。cells 是 [[u,v]…]（各 0..=47），
/// u 是横向、v 纵向直读——后端已按「长边铺满、短边居中」排好，前端只管铺格子。
/// 底色与 style.css 的 --stage 同源（canvas 吃不到 CSS 变量）。
function drawOutline(canvas, o) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width));
  const h = Math.max(1, Math.round(r.height));
  const pw = Math.max(1, Math.round(w * dpr));
  const ph = Math.max(1, Math.round(h * dpr));
  if (canvas.width !== pw || canvas.height !== ph) {
    canvas.width = pw;
    canvas.height = ph;
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#14100b";
  ctx.fillRect(0, 0, w, h);
  const cell = w / 48;
  ctx.fillStyle = "rgba(116, 195, 164, 0.75)";
  for (const [u, v] of o.cells || []) {
    ctx.fillRect(Math.floor(u * cell), Math.floor(v * cell), Math.max(1, cell), Math.max(1, cell));
  }
  return (o.cells || []).length > 0;
}

/// 三态里的「占位字」两种：真没图（两条命令都如实回了 null）和读取失败
/// （命令报错）。字面必须分开——把失败写成「没图」就是在替后端撒谎。
function applyThumbState(box, thumb, image, outline) {
  box.textContent = "";
  if (thumb === "img" && image) {
    const img = document.createElement("img");
    img.className = "thumb-img";
    img.alt = "";
    img.src = image.url;
    box.appendChild(img);
    return;
  }
  if (thumb === "mesh" && outline) {
    const cv = document.createElement("canvas");
    cv.className = "thumb-cv";
    cv.setAttribute("aria-hidden", "true");
    box.appendChild(cv);
    if (!drawOutline(cv, outline)) {
      // 后端明明白白回了「这组有几何」，只是这一格都画不出来——那是画不出，
      // 不是没图。写成「没图」就是拿界面的失败去替客户端编一条假事实。
      box.textContent = "画不出";
      box.title = "数据侧说这组有可解的网格，但一个格子都没画出来";
      return;
    }
    box.title = `几何投影（${outline.face} 面 · ${num(outline.vertexCount)} 顶点）——不是像素图`;
    return;
  }
  box.textContent = thumb === "fail" ? "没读到" : "没图";
  box.title =
    thumb === "fail"
      ? "缩略图读取失败：这条不是「没图」，是数据侧报了错"
      : "这组资产没有可解析的像素，也没有可解的网格";
}

/// 给一行装缩略图（导出给自测台用：那个环境里页面不可见时
/// IntersectionObserver 不触发，只能对指定行直接调）。
/// 先问图、没有再问几何投影；两条都如实回 null 才是「没图」。
export async function loadThumb(box) {
  const gid = Number(box.dataset.gid);
  if (!gid || Number.isNaN(gid)) return;
  const hit = thumbCache.get(gid);
  if (hit) {
    applyThumbState(box, hit.state, hit.image, hit.outline);
    return;
  }
  const busy = inflight.get(gid);
  if (busy) {
    const entry = await busy;
    if (entry) applyThumbState(box, entry.state, entry.image, entry.outline);
    return;
  }
  const job = schedule(async () => {
    let image = null;
    let outline = null;
    let failed = false;
    try {
      image = await api.groupPreview(gid);
      if (!image) outline = await api.groupMeshOutline(gid);
    } catch {
      failed = true;
    }
    return { state: failed ? "fail" : image ? "img" : outline ? "mesh" : "none", image, outline };
  });
  inflight.set(gid, job);
  const entry = await job;
  inflight.delete(gid);
  cacheSet(gid, entry);
  // 行可能已经随一次重画换人了：只有还在文档里的才补画。
  if (box.isConnected) applyThumbState(box, entry.state, entry.image, entry.outline);
}

/// 键盘 ↑↓：沿当前可见行移动选中。导出给 app.js 的全局键位。
export function moveSelect(delta) {
  if (!visibleGids.length) return false;
  const cur = visibleGids.indexOf(state.selected);
  const next = cur === -1 ? (delta > 0 ? 0 : visibleGids.length - 1) : Math.min(visibleGids.length - 1, Math.max(0, cur + delta));
  if (next === cur) return true;
  showDetail(visibleGids[next]);
  el("rows").querySelector(`.row-item[data-gid="${visibleGids[next]}"]`)?.scrollIntoView({ block: "nearest" });
  return true;
}

function bindListEvents() {
  // 事件委托挂一次：以前每次刷新给 300 行各挂一个闭包，刷新即重建 300 个。
  el("rows").addEventListener("click", (e) => {
    const row = e.target.closest(".row-item");
    if (row) showDetail(Number(row.dataset.gid));
  });
  // 触底续载：sentinel 露头且还有没列的就补下一页。
  new IntersectionObserver((entries) => {
    if (entries.some((en) => en.isIntersecting)) loadMore();
  }).observe(el("more"));
}

async function loadMore() {
  if (loadingMore || !state.ready || offset === 0) return;
  loadingMore = true;
  el("more").classList.add("loading");
  const my = seq.next();
  try {
    const page = await api.listGroups({ ...currentFilter(), offset });
    if (seq.isStale(my)) return;
    offset += page.items.length;
    const box = el("rows");
    box.insertAdjacentHTML("beforeend", page.items.map(rowHtml).join(""));
    observeThumbs(box.querySelectorAll(".row-item:not(.seen) .thumb"));
    box.querySelectorAll(".row-item").forEach((n) => n.classList.add("seen"));
    el("count").textContent = listCount(page.total, box.querySelectorAll(".row-item").length, page.ready);
  } catch {
    /* 续载失败不吭声会把人晾着：让 sentinel 停住即可，滚回顶部重筛一次就恢复。 */
  } finally {
    loadingMore = false;
    el("more").classList.remove("loading");
  }
}

function currentFilter() {
  return {
    query: state.query || null,
    scenario: state.scenario,
    kind: state.kind,
    grade: state.grade,
    onlyWithImage: state.onlyImage,
    named: state.named,
    limit: PAGE_SIZE,
  };
}

/// 重画整表。opts.top = 筛选驱动的刷新（主动换了一批结果），回顶部；
/// 预热广播驱动的刷新不传 top——用户正用滚轮安静地翻，把他拽回顶是抢他的手。
export async function refresh(opts = {}) {
  paintRail();
  const my = seq.next();
  try {
    const page = await api.listGroups(currentFilter());
    if (seq.isStale(my)) return;
    offset = page.items.length;
    visibleGids = page.items.map((c) => c.gid);
    const box = el("rows");
    box.innerHTML = page.items.map(rowHtml).join("");
    box.querySelectorAll(".row-item").forEach((n) => n.classList.add("seen"));
    resetThumbIO();
    // 首屏 14 个直接取（不等观察者的下一帧），滚动到的行再由观察者补。
    for (const n of Array.from(box.querySelectorAll(".thumb")).slice(0, 14)) loadThumb(n);
    el("empty").hidden = page.items.length > 0;
    el("count").textContent = listCount(page.total, page.items.length, page.ready);
    el("words").textContent =
      page.queryWords.length > 1 ? `按这几种拼法都找了：${page.queryWords.join("、")}` : "";
    // 还有没列完的才把 sentinel 摆出来（它 hidden 时观察器不触发）。
    el("more").hidden = !(state.ready && page.total > page.items.length);
    if (opts.top) el("rows").closest(".pane")?.scrollTo?.({ top: 0 });
  } catch (e) {
    if (seq.isStale(my)) return;
    el("count").textContent = "读取失败";
    el("rows").innerHTML = `<p class="dim">${esc(errText(e))}</p>`;
  }
}

export async function refreshStats() {
  try {
    state.stats = await api.stats();
    state.scanned = state.stats.scanned;
    state.total = state.stats.totalGroups;
    state.ready = state.stats.ready;
    const p = state.total ? Math.round((state.scanned / state.total) * 100) : 0;
    el("bar").style.width = `${p}%`;
    el("progressText").textContent = state.ready
      ? `已读完 ${num(state.total)} 组`
      : `正在读取 ${p}% · ${num(state.scanned)}/${num(state.total)}`;
    paintRail();
  } catch {
    /* 启动早期状态还没就绪，这一轮先跳过 */
  }
}

/// 有名字的 ↔ 未命名的，两边互斥地看，混在一起就又是一墙编号。
export function toggleUnnamed() {
  state.named = !state.named;
  saveState();
  refresh({ top: true });
}

export function resetFilters() {
  Object.assign(state, {
    query: "",
    kind: "全部",
    scenario: "全部",
    grade: "全部",
    onlyImage: false,
    named: true,
  });
  el("q").value = "";
  el("onlyImage").checked = false;
  saveState();
  refresh({ top: true });
}

bindListEvents();
