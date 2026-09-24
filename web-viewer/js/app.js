// 接线层：清单 → 筛选 → 图墙 → 详情。业务判断都在 data.js / viewer.js 里。

import { state, loadManifest, categories, filtered, matches, num, nice } from "./data.js";
import { thumb, cached, depth } from "./thumbs.js";
import { DetailViewer } from "./viewer.js";

const BATCH = 120;
const $ = (id) => document.getElementById(id);
let shown = 0;
let list = [];
let viewer = null;
let current = null;
const io = new IntersectionObserver(
  (entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      io.unobserve(e.target);
      fillTile(e.target);
    }
  },
  { rootMargin: "240px" },
);

function pill(box, items, get, onPick) {
  box.innerHTML = "";
  for (const it of items) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = it.label;
    if (it.n != null) {
      const i = document.createElement("i");
      i.textContent = num(it.n);
      b.appendChild(i);
    }
    if (get() === it.label) b.classList.add("on");
    b.onclick = () => {
      onPick(it.label);
      for (const c of box.children) c.classList.toggle("on", c === b);
      reset();
      paint();
    };
    box.appendChild(b);
  }
}

function sideControls() {
  pill($("cats"), [{ label: "全部", n: state.assets.length }, ...categories().map(([k, n]) => ({ label: k, n }))], () => state.cat, (v) => (state.cat = v));
  pill($("slots"), ["全部", "单个材质槽", "多个材质槽"].map((label) => ({ label })), () => state.slot, (v) => (state.slot = v));
  pill($("tris"), ["全部", "1 千面以内", "1 千 – 1 万面", "1 万面以上"].map((label) => ({ label })), () => state.tri, (v) => (state.tri = v));
}

function tileFor(a) {
  const t = document.createElement("div");
  t.className = "tile";
  t.dataset.id = a.id;
  const ph = document.createElement("div");
  ph.className = "ph";
  t.appendChild(ph);
  const nm = document.createElement("div");
  nm.className = "nm";
  nm.textContent = nice(a.name);
  nm.title = a.path;
  t.appendChild(nm);
  const mt = document.createElement("div");
  mt.className = "mt";
  mt.textContent = `${num(a.tris)} 面 · ${a.slots > 1 ? `${a.slots} 槽` : "单槽"}`;
  t.appendChild(mt);
  t.onclick = () => open(a, t);
  return t;
}

async function fillTile(el) {
  const a = list.find((x) => x.id === el.dataset.id);
  if (!a || !el.isConnected) return;
  const hit = cached(a.id);
  const put = (r) => {
    if (!el.isConnected) return;
    const old = el.firstChild;
    if (r.url) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = r.url;
      el.replaceChild(img, old);
    } else {
      old.title = "这个模型这次没能画出小图：" + (r.error || "未知原因");
      old.style.background = "#241a1a";
    }
  };
  if (hit) put({ url: hit });
  else put(await thumb(a));
}

function reset() {
  shown = 0;
  $("wall").innerHTML = "";
  list = filtered();
}

function paint() {
  const wall = $("wall");
  const next = list.slice(shown, shown + BATCH);
  const added = [];
  for (const a of next) {
    const t = tileFor(a);
    wall.appendChild(t);
    io.observe(t);
    added.push(t);
  }
  shown += next.length;
  // 页面没在画时观察器不触发（视口高度会是 0），所以这一批开头无条件先画 24 个。
  const vh = window.innerHeight || 720;
  for (const [i, t] of added.entries()) {
    if (i < 24 || t.getBoundingClientRect().top < vh * 1.6) {
      io.unobserve(t);
      fillTile(t);
    }
  }
  $("count").textContent = `筛出 ${num(list.length)} 个` + (list.length !== state.assets.length ? ` / 共 ${num(state.assets.length)} 个` : "");
  $("loading").textContent = shown < list.length ? "继续往下滚会自动接着排" : "";
}

function row(dt, dd) {
  return `<dt>${dt}</dt><dd>${dd == null || dd === "" ? "—" : dd}</dd>`;
}

function factsFor(a) {
  return [
    row("顶点", num(a.verts)),
    row("三角面", num(a.tris)),
    row("材质槽", a.slots > 1 ? `${a.slots} 个（引擎里一槽一次绘制）` : "1 个"),
    row("表面朝向", a.normals ? "文件里带着" : "没读到，明暗会平"),
    row("贴图坐标", a.uv ? "读到了" : "没读到"),
    row("所在目录", a.dir),
    row("库里归类", a.groupKind || "没归到资产组"),
    row("标签", (a.tags || []).slice(0, 6).join("、") || "—"),
    row(
      "引用是否落到实体",
      a.refsTotal ? `共 ${num(a.refsTotal)} 条，其中 ${num(a.refsLocated)} 条找到了文件` : "这一组没有登记引用",
    ),
  ].join("");
}

function partsFor(a) {
  const faces = a.slotFaces || [];
  const out = [];
  if (faces.length) {
    faces.forEach((f, i) => out.push(`<li>材质槽 ${i + 1}：<b>${num(f)}</b> 个三角面</li>`));
  } else {
    out.push(`<li>${a.slots} 个材质槽，每槽一次绘制</li>`);
  }
  out.push(`<li>${a.normals ? "表面朝向自带（明暗是真的）" : "表面朝向没读到，明暗按面推"}</li>`);
  out.push(`<li>${a.uv ? "有贴图坐标，接上图就能上花纹" : "没有贴图坐标"}</li>`);
  return out.join("");
}

function gapsFor(a) {
  const g = [
    "没有花纹：这批模型的贴图名字在客户端里没存对应文件，接不上图，所以看到的是形状本身。",
    "不会动：蒙皮权重不在模型文件里（已逐字段验过），骨骼矩阵也不在骨骼文件里，所以只有静止姿态。",
  ];
  if (!a.uv) g.push("这个文件里没读到贴图坐标，将来接上图也不一定能直接穿。");
  if (a.refsTotal && !a.refsLocated)
    g.push("这一组登记的引用一条都没落到实体文件——客户端打包时只留了名字，不是解析失败。");
  if (a.trailing > 0) g.push(`文件末尾还有 ${num(a.trailing)} 字节没读懂（是带名字的节点表，还没解完）。`);
  return g.map((x) => `<li>${x}</li>`).join("");
}

async function open(a, tile) {
  current = a;
  document.querySelectorAll(".tile.on").forEach((t) => t.classList.toggle("on", t === tile));
  $("detail").hidden = false;
  $("layout").classList.add("withdetail");
  $("dName").textContent = nice(a.name);
  $("dSub").textContent = `${a.category} · ${num(a.verts)} 顶点 · ${num(a.tris)} 三角面`;
  $("facts").innerHTML = factsFor(a);
  $("parts").innerHTML = partsFor(a);
  $("gaps").innerHTML = gapsFor(a);
  $("tech").innerHTML = [
    row("客户端路径", a.path),
    row("立体文件", a.glb),
    row("内容编号", a.id),
    row("资产组", a.group ?? "未归组"),
    row("没读懂的字节", `顶点之后 ${num(a.leftover)} · 结尾 ${num(a.trailing)}`),
  ].join("");
  $("slotbar").innerHTML = "";
  viewer = viewer || new DetailViewer($("cv"));
  $("stageHint").textContent = "正在取这个模型…";
  try {
    const r = await viewer.load("./model/" + a.glb);
    if (r.dropped) return;
    r.parts.forEach((o, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "on";
      b.textContent = `槽 ${i + 1}`;
      b.title = "点一下只看这一槽 / 隐藏这一槽";
      let on = true;
      b.onclick = () => {
        on = !on;
        b.classList.toggle("on", on);
        viewer.setVisible(i, on);
      };
      $("slotbar").appendChild(b);
    });
    $("stageHint").textContent = "拖动转 · 滚轮远近 · 双击回到正面";
  } catch (e) {
    $("stageHint").textContent = "这个模型这次没能打开：" + (e && e.message ? e.message : e);
  }
}

function header() {
  const s = state.stats;
  $("sum").textContent = `${num(s.mesh)} 个立体模型 · ${num(s.vertices)} 顶点 · ${num(s.triangles)} 三角面 · 解析失败 ${s.failed} 个`;
  $("sideNote").innerHTML =
    `这一层只收<b>客户端里带名字的立体模型</b>（${num(s.mesh)} 个，去掉重复内容后 ${num(s.uniqueGlb)} 份）。` +
    `库里还有 13,080 个资产组，多数是贴图 / 材质 / 动作，不在这面墙里。` +
    (s.failed ? `<br><b style="color:var(--warn)">${s.failed} 个没能解析，原因在清单的 failures 里。</b>` : "");
  const why = $("why");
  why.innerHTML =
    `看到的是<b>形状本身</b>（灰模）。两件事做不到，都不是这里偷懒：<br>` +
    `<i>① 没有花纹</i>：模型靠材质文件指出用哪张贴图，而客户端发布时把 2.4 万张贴图的路径剥掉了，名字接不到文件。<br>` +
    `<i>② 不会动</i>：蒙皮权重不在网格文件里、骨骼矩阵也不在骨骼文件里（都是逐字段验过的结论），所以只有静止姿态。<br>` +
    `法线与贴图坐标是真的：${num(state.stats.withNormals)} 个带朝向、${num(state.stats.withUv)} 个带贴图坐标。`;
  const box = document.querySelector(".honest");
  box.querySelector("b").onclick = (e) => {
    e.stopPropagation();
    why.hidden = !why.hidden;
  };
  document.addEventListener("click", (e) => {
    if (!why.hidden && !box.contains(e.target)) why.hidden = true;
  });
}

async function boot() {
  try {
    await loadManifest();
  } catch (e) {
    $("sum").textContent = "读不到清单：先跑 mesh2glb 导出，再刷新这一页";
    $("wall").innerHTML = `<p class="dim">${e.message}</p>`;
    return;
  }
  header();
  sideControls();
  list = filtered();
  let t = 0;
  $("q").addEventListener("input", (e) => {
    clearTimeout(t);
    t = setTimeout(() => {
      state.q = e.target.value;
      reset();
      paint();
    }, 160);
  });
  $("close").onclick = () => {
    $("detail").hidden = true;
    $("layout").classList.remove("withdetail");
    if (viewer) viewer.stop();
  };
  window.addEventListener("scroll", () => {
    if (shown >= list.length || document.documentElement.scrollHeight - window.scrollY - window.innerHeight > 900) return;
    paint();
  });
  reset();
  paint();
  setInterval(() => {
    const d = depth();
    if (d) $("loading").textContent = `正在画小图，还有 ${d} 个排队`;
  }, 600);
}

boot();
