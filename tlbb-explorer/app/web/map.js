// 地图浏览器：一层的「有什么 / 缺什么」都按资产页那套口径说话。
//
// 为什么走浮层而不是新页面：`health` 已经是这个形状（整屏浮层 + 一个返回按钮），
// 复用同一套壳，资产链路一行都不用改。地图不是新的一套工具，是同一个客户端的
// 另一类资源。
//
// 两个视图共用同一份 map_scene 回包，切换只是换画布、不重新取数：
//   * 灰模（WebGL，mesh-viewer.js）：立体、有明暗、能转；
//   * 俯视量测（2D，topdown.js）：正交、坐标可读、单击回查「哪个格子第几条」。
// 这一版都画不出三样东西：地形（.map 格式未解，高度不在这里）、贴图（全线断链）、
// 中文地图名（全库没有）。朝向是第四件：R 还是 Rᵀ 未证，灰模默认原样直读。

import { el, esc, num } from "./ui.js";
import * as api from "./api.js";
import { state, saveState } from "./state.js";
import { MeshViewer } from "./mesh-viewer.js";
import { TopDownView } from "./topdown.js";
import { makeSeq } from "./lib/seq.js";
import { rowLabel, factsHeader, unresolvedHtml } from "./lib/mapView.js";
import { mapNoObjects } from "./lib/wording.js";
import { drawThumb } from "./lib/mapThumb.js";

const seq = makeSeq();
let viewer = null; // 灰模（WebGL）
let top = null; // 俯视（2D）
let rows = [];
let mode = "gray"; // "gray" | "top"
let scene = null; // 最近一次读通的 map_scene 回包，两个视图共用
let sceneId = null;
let grayLoaded = null; // viewer 里装着的是哪张图（scene.id）
let topLoaded = null;

function banner(html) {
  el("mapBanner").innerHTML = html;
}

function status(msg) {
  const box = el("mapState");
  box.textContent = msg || "";
  box.hidden = !msg;
}

/// 量测读数要能对得上回包里的原始数字，保留一位小数、不进千分位。
const fmtCoord = (v) => Number(v).toFixed(1);

function hintFor(m) {
  return m === "top"
    ? "拖动平移 · 滚轮缩放 · 单击查物件 · 双击复位"
    : "按住拖动旋转 · 滚轮远近 · 双击回到正面";
}

function paintBanner() {
  if (!sceneId) {
    banner("");
    return;
  }
  if (mode === "top") {
    banner(
      `<b>俯视量测</b> 正对地面读坐标，格线间距 32。` +
        `<span class="warn">哪边是北未证</span><span class="warn">地形没解出</span>` +
        `<span class="dim">${scene && scene.alias ? esc(scene.alias) + " · " : ""}地图原名 ${esc(sceneId)}</span>`,
    );
  } else {
    banner(
      `<b>灰模预览</b> 只把物件摆在该在的位置上。` +
        `<span class="warn">地形没解出</span><span class="warn">没有花纹</span><span class="warn">朝向待比对</span>` +
        `<span class="dim">${scene && scene.alias ? esc(scene.alias) + " · " : ""}地图原名 ${esc(sceneId)}</span>`,
    );
  }
}

function info(s) {
  const line = (k, v) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
  // 「能画出形状」的分母是**实测走通的摆位记录**，不是文件头声明的条数（声明是上界，
  // 全库 n<declared 3,620 例）。而且这一版要把"不是网格"从"缺"里摘出去：
  // 大理这张图 6,112 条里 10 条是 .pu 特效、1 条名字认不出来，
  // 真正的 .mesh 一条不缺 —— 说成「99.8% 命中、11 条缺」是把好消息报成坏消息。
  const meshMissing = s.missingMeshes + s.unreadableMeshes;
  const bits = factsHeader(s).map(([k, v]) => line(k, v));
  bits.push(line("格子文件", `${num(s.grids)} 个`));
    line("摆位记录", `${num(s.records)} 条`),
    line("画得出形状", `${num(s.resolved)} 条 · 分母是上面那个实测条数`),
    line(
      "摆不出来的",
      meshMissing
        ? `<span class="miss">${num(s.missingMeshes)} 条记的是网格，但客户端里没有这个文件</span>` +
          (s.unreadableMeshes ? `<br /><span class="miss">${num(s.unreadableMeshes)} 条清单说有、容器里取不到字节</span>` : "")
        : `<span class="ok">0 条 —— 凡记成 .mesh 的都在客户端里找到了</span>`,
    ),
    line(
      "本来就不是网格",
      s.notMesh
        ? `${num(s.notMesh)} 条引用的是别的类型（${s.otherExt.map((x) => `.${esc(x.ext)} ${num(x.records)} 条`).join("、")}）—— 文件在客户端里存在，这一版只摆网格、不画这些`
        : "0 条",
    ),
    line("去重后的模型", `${num(s.uniqueMeshes)} 个 · 实例 ${num(s.instances.length)} 个`),
  ];
  if (s.oddNames) bits.push(line("认不出的名字", `${num(s.oddNames)} 条：既不像文件名也不像路径，没猜它是什么`));
  if (s.emptyGrids) bits.push(line("空着的格子", `${num(s.emptyGrids)} 个：那一格本来就没摆东西`));
  if (s.unreadableGrids)
    bits.push(line("读不通的格子", `${num(s.unreadableGrids)} 个：不是物件清单那类文件（逐条原因在下面）`));
  if (s.emptyNamed) bits.push(line("名字为空", `${num(s.emptyNamed)} 条`));
  if (s.catalogErrors)
    bits.push(
      line(
        "目录查询失败",
        `${num(s.catalogErrors)} 条没查成目录（是数据库抖动，不是客户端没有这些文件）——样本按原因聚合在下面`,
      ),
    );
  bits.push(line("还没解的", unresolvedHtml()));
  const reasons = s.gridReasons
    .map(
      (r) =>
        `<li class="a-missing"><span class="kd">${esc(r.reason)}</span><em>${num(r.grids)} 个</em>` +
        `<span>${r.sample.map(esc).join("、")}</span></li>`,
    )
    .join("");
  el("mapInfo").innerHTML = bits.join("");
  el("mapAbs").innerHTML = reasons || `<li class="a-ok"><span>这一版没有读不通的格子</span></li>`;
  const miss = s.missingSample.map((n) => `<li>${esc(n)}</li>`).join("");
  el("mapMiss").innerHTML =
    miss + (s.missingTruncated ? `<li class="dim">…只显示前 60 个，其余按个数计在上面</li>` : "");
  el("secMapMiss").hidden = !miss;
}

function ensureViewer() {
  if (viewer) return viewer;
  viewer = new MeshViewer(el("mapCanvas"));
  viewer.onlost = () => {
    seq.next();
    grayLoaded = null;
    status("显卡上下文被系统收回了，重新点一下这张图就能再看。");
  };
  return viewer;
}

function ensureTop() {
  if (top) return top;
  top = new TopDownView(el("mapTop"));
  top.onhover = (h) => {
    const box = el("topCoords");
    if (!h) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.textContent =
      `x ${fmtCoord(h.wx)} · z ${fmtCoord(h.wz)} · 格 ${h.gx},${h.gz}` +
      (h.gridName ? ` · ${h.gridName}` : "");
  };
  top.onpick = (p) => {
    const box = el("topPick");
    if (!p) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    box.innerHTML =
      `<b>${esc(p.gridName || "格子名缺失")}</b> 第 ${num(p.recordNo)} 条<br />` +
      `<span>${esc(p.meshPath || "（模型名缺失）")}</span>` +
      `<span class="dim">x ${fmtCoord(p.wx)} · z ${fmtCoord(p.wz)} · 矩形近似，指到哪件报哪件</span>`;
  };
  return top;
}

/// 俯视图左下角的状态行：把取景口径说清（主簇多少格、有没有孤悬），
/// 让「为什么一打开看不见那棵孤悬的树」有答案：缩放出去就有。
function topStatus() {
  const n = scene.instances.length;
  const ci = top && top.clusterInfo;
  if (!ci || !top.view) return `${num(n)} 件 · 都算不出可画的矩形`;
  const stray = ci.cells - ci.mainCells;
  return (
    `${num(n)} 件 · ${num(ci.cells)} 格有物件 · 主簇 ${num(ci.mainCells)} 格` +
    (stray > 0 ? ` · 孤悬 ${num(stray)} 格（缩远可见）` : "") +
    ` · 单击一件查它出自哪个格子`
  );
}

/// 按当前模式摆好画布、提示和横幅，并把 scene 按需装进对应视图。
/// 装载可能失败（3D 上下文、数据对不上）：失败就收起画布说原因，不亮空盒子。
function applyMode() {
  const hasObjects = Boolean(scene && scene.instances && scene.instances.length);
  el("modeGray").classList.toggle("on", mode === "gray");
  el("modeTop").classList.toggle("on", mode === "top");
  el("stageHint").textContent = hintFor(mode);
  el("topPick").hidden = true;
  el("topCoords").hidden = true;
  paintBanner();
  if (!hasObjects) {
    if (viewer) viewer.stop();
    el("mapCanvas").hidden = true;
    el("mapTop").hidden = true;
    if (scene) status(mapNoObjects(scene));
    return;
  }
  if (mode === "gray") {
    el("mapTop").hidden = true;
    el("mapCanvas").hidden = false;
    let v;
    try {
      v = ensureViewer();
    } catch (e) {
      el("mapCanvas").hidden = true;
      status(`这台机器开不了 3D 预览：${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    if (grayLoaded !== scene.id) {
      try {
        // instances 的形状就是 expandInstances 吃的那个；矩阵是 .scene 原样直读，
        // 中间不许再转置（转一次全图叠到原点且不报错）。
        v.loadInstances({ meshes: scene.meshes, instances: scene.instances });
        grayLoaded = scene.id;
      } catch (e) {
        el("mapCanvas").hidden = true;
        status(`画不出来：${e instanceof Error ? e.message : String(e)}`);
        return;
      }
    } else {
      // 从俯视切回来时 WebGL 那边已停帧：画一帧把画面找回来，否则可能是块黑布。
      v.start();
    }
    status(`${num(scene.instances.length)} 件 · ${num(scene.uniqueMeshes)} 个模型 · 平地是代替物（地形未解）`);
  } else {
    if (viewer) viewer.stop();
    el("mapCanvas").hidden = true;
    // 必须先显示再装载：隐藏的 canvas 量不到尺寸，取景会按 1px 画布算。
    el("mapTop").hidden = false;
    if (topLoaded !== scene.id) {
      let t;
      try {
        t = ensureTop();
      } catch (e) {
        el("mapTop").hidden = true;
        status(`这台机器开不了 2D 画布：${e instanceof Error ? e.message : String(e)}`);
        return;
      }
      try {
        t.load(scene);
        topLoaded = scene.id;
      } catch (e) {
        status(`画不出来：${e instanceof Error ? e.message : String(e)}`);
        return;
      }
    } else {
      // 同图切回：隐藏期间窗口 resize 可能把位图清成 1×1（灰模侧同样的问题
      // 靠 start() 找回画面，这边是纯 2D，补一次量尺寸 + 重画）。
      t.syncViewport();
      t.draw();
    }
    status(topStatus());
  }
}

function setMode(m) {
  if (mode === m) return;
  mode = m;
  state.mapMode = m; // 重启后回到用户熟悉的那一面
  saveState();
  applyMode();
}

// 回包级缓存（LRU 4 张）：客户端资源只读，缓存安全。一张大图冷装配 1-5s
// 加 7MB 回包，A→B→A 来回点不该每次都全额重付。存的是 Promise，两个视图
// 同时等同一张图也只发一次请求。
const SCENE_CACHE_MAX = 4;
const sceneCache = new Map(); // id → Promise<MapScene>

function fetchScene(id) {
  const hit = sceneCache.get(id);
  if (hit) {
    sceneCache.delete(id);
    sceneCache.set(id, hit); // 触摸即提新：Map 插入序就是 LRU 序
    return hit;
  }
  const p = api.mapScene(id).catch((e) => {
    sceneCache.delete(id); // 失败的别占坑
    throw e;
  });
  sceneCache.set(id, p);
  if (sceneCache.size > SCENE_CACHE_MAX) {
    sceneCache.delete(sceneCache.keys().next().value);
  }
  return p;
}

async function openScene(id) {
  const my = seq.next();
  rows.forEach((r) => r.classList.toggle("on", r.dataset.id === id));
  scene = null;
  grayLoaded = null;
  topLoaded = null;
  sceneId = id;
  status(`正在读 ${id} 的格子…`);
  paintBanner();
  let s;
  try {
    s = await fetchScene(id);
  } catch (e) {
    if (seq.isStale(my)) return;
    if (viewer) viewer.stop();
    el("mapCanvas").hidden = true;
    el("mapTop").hidden = true;
    el("topPick").hidden = true;
    el("topCoords").hidden = true;
    status(`这张图没读出来：${e instanceof Error ? e.message : String(e)}`);
    el("mapInfo").innerHTML = "";
    el("mapAbs").innerHTML = "";
    // 上一张图的缺件清单也必须收走：A 图的「缺 60 条」挂在 B 图的失败页上，
    // 看起来就像 B 图缺了 60 条——比空白更害人。
    el("secMapMiss").hidden = true;
    el("mapMiss").innerHTML = "";
    return;
  }
  if (seq.isStale(my)) return; // 已经切到别的图了
  scene = s;
  paintBanner();
  info(s);
  // 一个实例都没有：画不出东西，但那不是失败，别把画布亮着假装在渲染。
  applyMode();
}

export async function openMap() {
  el("maps").hidden = false;
  // 上次的视图先恢复再摆画布：默认灰模，存过俯视就回俯视。
  mode = state.mapMode === "top" ? "top" : "gray";
  el("modeGray").onclick = () => setMode("gray");
  el("modeTop").onclick = () => setMode("top");
  applyMode();
  if (rows.length) {
    ensureThumbIO();
    return;
  }
  status("正在列地图…");
  try {
    const list = await api.mapList(500);
    rows = list.map((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "maprow";
      b.dataset.id = m.id;
      b.dataset.alias = m.alias || "";
      b.innerHTML =
        '<canvas class="mthumb" aria-hidden="true"></canvas>' +
        `<span class="mtxt"><span class="malias">${esc(rowLabel(m.alias))}</span>` +
        `<span class="mid">${esc(m.id)}</span>` +
        `<span class="mg" data-g="${m.grids}">${num(m.grids)} 格</span></span>`;
      b.onclick = () => openScene(m.id);
      el("mapRows").appendChild(b);
      return b;
    });
    // 左栏搜索：纯前端内存过滤，敲几个字符就能在几百张图里找到那张。
    el("mapFilter").oninput = () => {
      const q = el("mapFilter").value.trim().toLowerCase();
      for (const b of rows) b.hidden = Boolean(q) && !(b.dataset.id.toLowerCase().includes(q) || (b.dataset.alias || "").toLowerCase().includes(q));
    };
    ensureThumbIO();
    // 首屏不等 IntersectionObserver 的下一帧回调：浮层一打开就先取第一屏，
    // 滚动到的行再由观察者补——打开就能看见图，而不是先闪一列空格子。
    for (const b of rows.slice(0, 14)) loadThumb(b);
    status(
      `共 ${num(list.length)} 张图：口径是"至少有一个格子文件的目录"，不是客户端承认存在的地图全集`,
    );
  } catch (e) {
    status(`列不出地图：${e instanceof Error ? e.message : String(e)}`);
  }
}

/// 列表行缩略图：进视口才取数——map_footprint 每张都是一次全图装配，
/// 300 张一起拉会把窗口冻住。取过的记在 thumbCache，关浮层再开不重新装配。
/// 缓存有顶（LRU 120）：回包是带全实例表的整份对象，无顶的话滚一遍
/// 几百张图就是几百 MB 驻留，用一晚上越用越胀。
const THUMB_CACHE_MAX = 120;
const thumbCache = new Map(); // id → { state: "ok"|"empty"|"fail", payload? }
let thumbIO = null;

function ensureThumbIO() {
  if (!thumbIO) {
    thumbIO = new IntersectionObserver((entries) => {
      for (const en of entries) {
        if (en.isIntersecting) loadThumb(en.target);
      }
    });
  }
  for (const b of rows) thumbIO.observe(b);
}

/// 行尾小字的三种实话：没物件可画（回包里一条摆位矩形都没有）、缩略图没读出来
/// （装配报错）。都不许留一块空画布装作在渲染。画出来的那部分在画布里。
function applyThumbState(btn, state) {
  const cv = btn.querySelector("canvas.mthumb");
  if (cv) cv.classList.add("none");
  const mg = btn.querySelector(".mg");
  if (!mg) return;
  mg.textContent =
    state === "fail"
      ? `${mg.dataset.g} 格 · 缩略图没读出来`
      : `${mg.dataset.g} 格 · 没物件可画`;
}

/// 给一行列表装缩略图（导出给自测台用：那个环境里页面不可见，
/// IntersectionObserver 不触发，只能对指定行直接调）。取数 → 画脚印 →
/// 画不出就如实改行尾小字；取过就缓存，重复调用只补画不重取。
export async function loadThumb(btn) {
  const id = btn.dataset.id;
  const hit = thumbCache.get(id);
  if (hit) {
    // 缓存命中后仍可能要补画：回包回来时浮层若已关上，画布量不到尺寸，
    // 会画进 1px 的兜底画布——浮层再开、行再进视口时在这里画第二次。
    if (hit.state === "ok") {
      const cv = btn.querySelector("canvas.mthumb");
      if (cv && cv.width < 8) {
        try {
          drawThumb(cv, hit.payload);
        } catch {
          // 画布坏了也不改成「没物件」——数据是取到过的，定性不许翻案。
        }
      }
    }
    return;
  }
  let s;
  try {
    s = await api.mapFootprint(id);
  } catch {
    cacheSet(id, { state: "fail" });
    applyThumbState(btn, "fail");
    return;
  }
  let ok = false;
  try {
    ok = drawThumb(btn.querySelector("canvas.mthumb"), s);
  } catch {
    ok = false;
  }
  cacheSet(id, ok ? { state: "ok", payload: s } : { state: "empty" });
  if (!ok) applyThumbState(btn, "empty");
}

/// LRU 写入：Map 插入序即使用序，超顶淘汰最旧的一条。
function cacheSet(id, entry) {
  if (thumbCache.has(id)) thumbCache.delete(id);
  thumbCache.set(id, entry);
  if (thumbCache.size > THUMB_CACHE_MAX) {
    thumbCache.delete(thumbCache.keys().next().value);
  }
}

export function closeMap() {
  el("maps").hidden = true;
  seq.next(); // 关掉就把在途回包作废：否则切回来会看到上一张图的残留
  if (viewer) viewer.stop();
}
