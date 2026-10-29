// 左栏筛选 + 中间列表。列表只回答「哪一条」，一条资产一行。
// 行首缩略图只有三态实话：组里真能解出像素→那张图；解不出但有网格→几何投影
// 的格子脚印（不是像素图，title 里说明）；两者都无→写「没图」。
// 不放类型轮廓那种装饰图：约 83% 的资产没有可解析的像素，占位图形只会让人
// 以为那是内容物。默认也不列未命名组：它们连路径都没记录，标题只能是 16 位编号。

import { el, esc, num, chips, errText } from "./ui.js";
import * as api from "./api.js";
import { state, saveState } from "./state.js";
import { showDetail } from "./detail.js";
import { listCount, railCount, rowMissChip, progressLine } from "./lib/wording.js";
import { isNotReadyMsg } from "./lib/detailState.js";
import { makeSeq } from "./lib/seq.js";

const ALL = { value: "全部", label: "全部" };
const seq = makeSeq();
/// 每页条数 = 一屏的十几倍：续载由触底观察器自动补，用户感知不到「页」。
const PAGE_SIZE = 300;
let offset = 0;
let loadingMore = false;
/// 当前列表里行的顺序（gid），键盘 ↑↓ 沿它走。
let visibleGids = [];

const GRADE_COLOR = { A: "gA", B: "gB", C: "gC", D: "gD" };

/// 一组筹码：整行、带色点徽章。与 ui.js::chips 同形，但完整程度这四档
/// 需要一眼看出等级，色点是唯一在这里值得多花的一个像素。
function gradeChips(node, options, current, pick) {
  node.innerHTML = "";
  for (const opt of options) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (opt.value === current ? " on" : "");
    const cls = GRADE_COLOR[String(opt.value)] || "gC";
    const head = String(opt.label).split(" ")[0];
    b.innerHTML =
      `<span class="gdot ${cls}">${esc(head)}</span><span>${esc(String(opt.label).replace(/^\S+\s*/, ""))}</span>` +
      (opt.count === undefined ? "" : `<em>${num(opt.count)}</em>`);
    b.onclick = () => pick(opt.value);
    node.appendChild(b);
  }
}

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
    gradeChips(
      el("grades"),
      [ALL, ...s.grades.map((g) => ({ value: g.value, label: `${g.value} ${g.label}`, count: g.count }))],
      state.grade,
      (v) => {
        state.grade = v;
        saveState();
        refresh({ top: true });
      },
    );
  }
  // 底部的总数一行：截图里左栏最下面那块「共有资源」。
  const rc = railCount(s);
  el("railCount").innerHTML = `<b>${rc.total}</b> 条资产 · 其中 <b>${rc.withImage}</b> 组贴图名能对上文件`;

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
  // 质量徽章：截图里带前缀词（A 主体定位），比光秃秃一个字母好扫。
  const qword = { A: "完整定位", B: "主体定位", C: "仅有名称", D: "只有线索" }[c.grade] || "";
  return `<button type="button" class="row-item${state.selected === c.gid ? " on" : ""}" data-gid="${c.gid}">
    <span class="thumb" data-gid="${c.gid}"></span>
    <span class="body">
    <span class="t"><strong title="${esc(title)}">${esc(title)}</strong><em class="grade g${esc(c.grade)}" title="${esc(c.gradeNote)}">${esc(c.grade)}${qword ? ` ${esc(qword)}` : ""}</em></span>
    <span class="s">${esc(sub)}</span>
    <span class="c">${
      miss > 0 && rowMissChip(miss) ? `<i>${esc(rowMissChip(miss))}</i>` : ""
    }${parts || `<i class="dim">没读到部件</i>`}<i>${num(c.memberTotal)} 文件</i></span>
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
  box.classList.remove("thumb-none");
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
  // 占位字给底纹 + 居中，白底上一行浅灰小字容易看成「没渲染出来」。
  box.classList.add("thumb-none");
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
    // 0 条时把「是谁把列表筛空的」说明白：有搜索词说搜索词，别让用户对着
    // 一句干巴巴的「没有符合条件的资产」猜自己点了什么。
    if (page.items.length === 0) {
      const strong = el("empty").querySelector("strong");
      const span = el("empty").querySelector("span");
      if (state.query) {
        strong.textContent = `没有命中「${state.query}」`;
        span.textContent = "换个关键词，或点上方「清空筛选」清掉全部条件。";
      } else if (!page.ready) {
        strong.textContent = "后台还在准备资产清单";
        span.textContent = "已就绪的会陆续出现，顶栏有进度。";
      } else {
        strong.textContent = "没有符合条件的资产";
        span.textContent = "换个关键词，或点「清空筛选」。";
      }
    }
    el("count").textContent = listCount(page.total, page.items.length, page.ready);
    el("words").textContent =
      page.queryWords.length > 1 ? `按这几种拼法都找了：${page.queryWords.join("、")}` : "";
    // 还有没列完的才把 sentinel 摆出来（它 hidden 时观察器不触发）。
    el("more").hidden = !(state.ready && page.total > page.items.length);
    if (opts.top) el("rows").closest(".pane")?.scrollTo?.({ top: 0 });
  } catch (e) {
    if (seq.isStale(my)) return;
    const msg = errText(e);
    // 「还没读到」不是「读取失败」，别吓人（list_groups 现在多半回中途页而不是
    // 报错，这个分支是给偶发排队失败留的保险）。钉子统一走 isNotReadyMsg，
    // 跟后端文案逐字对齐——见 lib/detailState.js 顶上的说明。
    if (isNotReadyMsg(msg)) {
      el("count").textContent = "后台准备中…";
      el("rows").innerHTML =
        '<p class="dim">资产清单正在后台准备（顶栏有进度），几秒后自动出现。</p>';
      setTimeout(() => {
        if (!seq.isStale(my)) refresh();
      }, 3000);
      return;
    }
    el("count").textContent = "读取失败";
    el("rows").innerHTML = `<p class="dim">${esc(msg)}</p>`;
  }
}

export async function refreshStats() {
  try {
    state.stats = await api.stats();
    state.scanned = state.stats.scanned;
    state.total = state.stats.totalGroups;
    state.ready = state.stats.ready;
    // 顶栏进度说的是「资产」标签那套检索库的预热。浏览第一屏靠的是 pak 容器
    // 本身，不等它——两套口径的分寸全在 lib/wording.js 的 progressLine（有测试盯着）。
    const line = progressLine(state.view, state.ready, state.scanned, state.total);
    el("bar").style.width = `${line.pct}%`;
    el("progressText").textContent = line.text;
    el("progressText").title = line.tip;
    paintRail();
  } catch (e) {
    /* stats() 在没预热时也会如实回（全 0 + ready:false），会走到这里的只剩
       外壳/IPC 层的问题（网页外壳、旧后端缺命令）。曾经这里静默吞掉，顶栏就
       永远停在上一句话——网页外壳下甚至是启动时的「正在读取…」——用户以为
       还在读，其实什么都没发生。失败必须可见：说「读不到」，不吓人也不装没事。
       列表自身的失败由 refresh() 的错误文案兜底，详情由 detail.js 兜底。 */
    el("bar").style.width = "0%";
    el("progressText").textContent = `资产库状态读不到：${errText(e)}`;
    el("progressText").title = "";
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
