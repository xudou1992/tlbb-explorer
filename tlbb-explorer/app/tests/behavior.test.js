// 行为回归测试：在 node 里用真实 DOM 替身跑生产 ESM，钉住「五处曾经真出过错」的接线。
//
// 为什么不用源码 grep：这几条全是运行时时序（迟到的回包、动态追加的行、
// 重建与不重建两条路的高亮），源码里那行字在、行为却错的情况恰好就是它们
// 出问题的方式。这里只替掉 IPC 和 WebGL，detail.js / list.js / app.js /
// panels.js / ui.js 都是加载的真文件。
//
// 跑法（在 app/ 下，VM Modules 还是实验特性，要带开关）：
//   node --experimental-vm-modules --test tests/behavior.test.js

import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

if (typeof vm.SourceTextModule !== "function") {
  throw new Error("这套测试要在沙箱里加载真前端，跑它得带开关：node --experimental-vm-modules --test tests/*.test.js（npm test 已经写进去了）");
}

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.join(here, "..", "web");

class Element {
  constructor() {
    this.children = [];
    this.events = {};
    this.dataset = {};
    this.style = {};
    this.hidden = false;
    this.checked = false;
    this.value = "";
    this.className = "";
    this._html = "";
    this.textContent = "";
  }
  get innerHTML() {
    return this._html;
  }
  set innerHTML(v) {
    this._html = v;
    this.children = [];
  }
  classList = {
    add: (...c) => c.forEach((x) => this.classList.toggle(x, true)),
    remove: (...c) => c.forEach((x) => this.classList.toggle(x, false)),
    toggle: (c, on) => {
      const s = new Set(this.className.split(" ").filter(Boolean));
      if (on ?? !s.has(c)) s.add(c);
      else s.delete(c);
      this.className = [...s].join(" ");
    },
  };
  addEventListener(n, f) {
    (this.events[n] ??= []).push(f);
  }
  appendChild(n) {
    this.children.push(n);
    return n;
  }
  append(...n) {
    this.children.push(...n);
  }
  querySelectorAll(s) {
    return s === ".tab" ? this.children : [];
  }
  querySelector() {
    return new Element();
  }
  insertAdjacentHTML(_, html) {
    this._html += html;
  }
  scrollTo() {}
  scrollIntoView() {}
  closest() {
    return new Element();
  }
  setAttribute(n, v) {
    (this.attrs ??= {})[n] = String(v);
  }
  getAttribute(n) {
    return (this.attrs || {})[n] ?? null;
  }
}

/// 加载 entry 及其相对依赖：mock 里的路径换成假导出，expose 往真文件尾部追加 export。
async function sandbox(entry, mock = {}, expose = {}) {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  /// 面板清单从 index.html 现读，不手写：加一个标签页却忘了同步测试，
  /// 就等于让测试替身比真页面少一块，断言会假绿或假红（这次就撞上了）。
  const indexHtml = fs.readFileSync(path.join(web, "index.html"), "utf8");
  const paneNames = [...indexHtml.matchAll(/data-pane="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(paneNames.length >= 6, `index.html 里只找到 ${paneNames.length} 个面板，读法错了`);
  const panes = paneNames.map((pane) =>
    Object.assign(new Element(), { dataset: { pane } }),
  );
  el("dTabs").children = panes.map((p) => Object.assign(new Element(), { dataset: { tab: p.dataset.pane } }));
  const context = vm.createContext({
    console,
    window: {},
    document: {
      getElementById: el,
      createElement: () => new Element(),
      querySelectorAll: (s) => (s.includes("tabpane") ? panes : []),
      addEventListener() {},
    },
    localStorage: { getItem: () => null, setItem() {} },
    setTimeout: () => 0,
    clearTimeout() {},
    // 播放预览用得到：替身不给真定时器，测试里直接手动步进（见动作页的用例）
    setInterval: () => 0,
    clearInterval() {},
    IntersectionObserver: class {
      observe() {}
      disconnect() {}
    },
    Date,
  });
  const mods = new Map();
  const key = (p) => path.resolve(p);
  async function get(p) {
    p = key(p);
    if (mods.has(p)) return mods.get(p);
    const rel = path.relative(web, p).replaceAll("\\", "/");
    let m;
    if (mock[rel]) {
      m = new vm.SyntheticModule(Object.keys(mock[rel]), function () {
        for (const [k, v] of Object.entries(mock[rel])) this.setExport(k, v);
      }, { context, identifier: p });
    } else {
      m = new vm.SourceTextModule(fs.readFileSync(p, "utf8") + (expose[rel] || ""), { context, identifier: p });
    }
    mods.set(p, m);
    await m.link((s, ref) => get(path.resolve(path.dirname(ref.identifier), s)));
    return m;
  }
  const m = await get(path.join(web, entry));
  await m.evaluate();
  return { module: m.namespace, el, panes, get: (name) => mods.get(key(path.join(web, name))).namespace };
}

const noop = () => {};
const meshMock = { showMeshes: noop, hideMeshes: noop, applyTexture: () => true };

// 详情用的两份夹具直接从 detailState 的用例里借，免得两处夹具各写各的。
const fixtureSource = fs.readFileSync(path.join(here, "detailState.test.js"), "utf8");
const fixtures = vm.runInNewContext(
  fixtureSource.slice(fixtureSource.indexOf("const CARD_A"), fixtureSource.indexOf("function dirtyFields")) +
    "\n({DETAIL_A, INSPECT_A})",
);

test("切换资产失败：上一条资产的文件清单/原始数据/环形图必须收干净", async () => {
  let failDetail = false;
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => {
        if (failDetail) throw new Error("AUDIT: B read failed");
        return fixtures.DETAIL_A;
      },
      assetInspect: async () => fixtures.INSPECT_A,
    },
  });
  await detail.module.showDetail(245);
  detail.get("panels.js").showTabPane("files");
  // 先确认「A 的内容真的铺上过」，否则下面的空断言可能只是从来没写过。
  assert.ok(detail.el("fileList").innerHTML.includes("a.mesh"), "夹具应先铺出 A 的文件清单");
  const previous = Object.fromEntries(
    ["fileList", "rawJson", "ringBox"].map((id) => [id, detail.el(id).innerHTML || detail.el(id).textContent]),
  );
  failDetail = true;
  await detail.module.showDetail(999);
  for (const id of Object.keys(previous)) {
    assert.ok(previous[id], `夹具应让 ${id} 有内容`);
    assert.equal(detail.el(id).innerHTML || detail.el(id).textContent, "", `${id} 还留着上一条资产的内容`);
  }
  assert.equal(
    detail.panes.find((p) => p.dataset.pane === "files").hidden,
    true,
    "B 读失败了，「文件」那一页不该还亮着",
  );
});

test("筛选筹码：不重建那一路也要把高亮挪到生效的那一颗", async () => {
  const list = await sandbox("list.js", {
    "detail.js": { showDetail: noop },
    "api.js": { listGroups: async () => ({ items: [], queryWords: [], ready: true, total: 0 }) },
  });
  const st = list.get("state.js").state;
  st.stats = {
    kinds: [{ value: "mesh", label: "Mesh", count: 2 }],
    scenarios: [],
    grades: [],
    totalGroups: 2,
    imageCandidates: 0,
    unnamed: 0,
  };
  list.module.paintRail();
  list.el("kinds").children[1].onclick(); // 点「Mesh」
  await Promise.resolve();
  assert.equal(st.kind, "mesh", "筛选值应已写入 state");
  assert.ok(list.el("kinds").children[1].className.includes("on"), "生效的那一颗必须高亮");
  assert.ok(!list.el("kinds").children[0].className.includes("on"), "「全部」已不生效，不该还高亮着");
});

test("触底追加的行要进键盘导航序列", async () => {
  const selectedCalls = [];
  let page = { items: [], queryWords: [], ready: true, total: 0 };
  const list = await sandbox("list.js", {
    "detail.js": { showDetail: (gid) => selectedCalls.push(gid) },
    "api.js": { listGroups: async () => page },
  }, { "list.js": "\nexport { loadMore };" });
  const st = list.get("state.js").state;
  st.ready = true; // 触底续载只在清单读完时才动
  page = { items: [{ gid: 1, named: true, name: "A", grade: "A" }], queryWords: [], ready: true, total: 2 };
  await list.module.refresh();
  page = { items: [{ gid: 2, named: true, name: "B", grade: "A" }], queryWords: [], ready: true, total: 2 };
  await list.module.loadMore();
  assert.ok(list.el("rows").innerHTML.includes('data-gid="2"'), "追加行应已进 DOM");
  st.selected = 1;
  list.module.moveSelect(1);
  assert.deepEqual(selectedCalls, [2], "从 A 按 ↓ 应选中追加出来的 B");
});

test("资产侧没被点开时，预热广播不得驱动资产链路", async () => {
  let reading;
  let statsCalls = 0;
  const app = await sandbox("app.js", {
    "api.js": { hasShell: true, onReading: (fn) => { reading = fn; }, startWarm: async () => {}, preview: () => new Promise(noop) },
    "list.js": { refresh: noop, refreshStats: async () => { statsCalls++; }, resetFilters: noop, toggleUnnamed: noop, moveSelect: noop },
    "health.js": { openHealth: noop, closeHealth: noop },
    "map.js": { openMap: noop, closeMap: noop },
    "detail.js": { clearDetail: noop, showDetail: noop },
    "browse.js": { initBrowse: noop, showTab: noop },
    "exportProgress.js": { initExportProgress: noop },
    "relations.js": { initRelations: noop, openRelations: noop, closeRelations: noop },
  });
  assert.equal(app.get("state.js").state.view, "browse", "默认视图应是浏览");
  await reading({ payload: { ready: false } });
  assert.equal(statsCalls, 0, "浏览首屏不该被广播拽去读资产库统计");
});

test("灯箱：迟到的大图回包不得顶掉当前那张", async () => {
  const deferred = {};
  const app = await sandbox("app.js", {
    "api.js": {
      hasShell: true,
      onReading: noop,
      startWarm: async () => {},
      preview: (hash) => new Promise((resolve) => { deferred[hash] = resolve; }),
    },
    "list.js": { refresh: noop, refreshStats: noop, resetFilters: noop, toggleUnnamed: noop, moveSelect: noop },
    "health.js": { openHealth: noop, closeHealth: noop },
    "map.js": { openMap: noop, closeMap: noop },
    "detail.js": { clearDetail: noop, showDetail: noop },
    "browse.js": { initBrowse: noop, showTab: noop },
    "exportProgress.js": { initExportProgress: noop },
    "relations.js": { initRelations: noop, openRelations: noop, closeRelations: noop },
  }, { "app.js": "\nexport { openLightbox, closeLightbox };" });
  app.module.openLightbox("thumbA", "A", "A");
  app.module.closeLightbox();
  app.module.openLightbox("thumbB", "B", "B");
  deferred.B({ url: "fullB" });
  await Promise.resolve();
  deferred.A({ url: "fullA" }); // A 那张迟到了
  await Promise.resolve();
  assert.equal(app.el("lightboxImg").src, "fullB", "画面应还是当前这张 B");
  assert.equal(app.el("lightboxCap").textContent, "B", "标题说的是 B");
});

test("后台批量试贴的接线不能被拆：没有候选榜时那颗按钮也得点得动", async () => {
  const src = fs.readFileSync(path.join(web, "detail.js"), "utf8");
  const warm = src.indexOf('b.dataset.act === "warm"');
  const guard = src.indexOf("if (!texReply) return;");
  assert.ok(warm >= 0, "那颗按钮的分支还在");
  assert.ok(guard >= 0, "texReply 守卫还在");
  assert.ok(warm < guard, "warm 分支必须在 texReply 守卫之前——没有榜时 texReply 正是空的");
  assert.match(src, /texBlock\(insp, warmStatus\)/, "状态要真传进纯函数那一层");
  assert.match(src, /api\s*\.\s*textureWarmStatus|\.textureWarmStatus\(\)/, "打开详情时要问一次还差多少只");
});

test("容器与清单的缺口必须自己说出来（不能让用户以为客户端里没这个文件）", async () => {
  const src = fs.readFileSync(path.join(web, "health.js"), "utf8");
  assert.match(src, /id="gapSec"/, "摘要里要有那一节的位置");
  assert.match(src, /await api\.catalogGap\(\)/, "数字只能来自后端，前端不算术");
  assert.match(src, /清单比容器少/, "有缺口时必须说清差多少、去哪重建");
  // 两条渲染路径（缓存回显 / 现查）都得填这一节，漏一条就是「有时不说」。
  assert.equal((src.match(/paintGap\(\);/g) || []).length, 2, "两条渲染路径都要调 paintGap");
});

test("详情「导出」：点一下要把整组交出去，并把写了几个文件、写到哪儿说清", async () => {
  const calls = [];
  const reply = {
    written: 21,
    dest: "D:/TLGL/.scratch/exports/w1351_monster_xiyuqiezei",
    failed: [],
    failed_more: 0,
  };
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      browseExportGroup: async (gid) => {
        calls.push(gid);
        return reply;
      },
    },
  });
  await detail.module.showDetail(245);
  const btn = detail.el("btnExportOne");
  assert.ok(btn.events?.click?.length, "导出按钮没接上监听");
  await btn.events.click[0]();
  assert.deepEqual(calls, [245], "点导出应把当前组号交给后端，且只调一次");
  const sum = detail.el("dSum").textContent;
  assert.ok(sum.includes("已导出 21"), `回包要说清写了几个文件：${sum}`);
  assert.ok(sum.includes("exports"), `要报出落点目录，不能只说「已导出」：${sum}`);
  // 没选中资产时不该打后端
  detail.get("state.js").state.selected = 0;
  await btn.events.click[0]();
  assert.equal(calls.length, 1, "没选资产也去调后端，是多余的一次请求");
});

test("骨架页：解出来的骨名与动作要真铺进标签页，迟到的回包不许串台", async () => {
  const A = { mesh: "a_yifu.mesh", meshes: ["a_yifu.mesh", "a_shoutao.mesh"],
    declared: 46, note: "", skin_bones: 26, skin_pairs: 1163,
    nodes: [
      { name: "bip01", pos: null, scale: null, skin: 0, source: "ani" },
      { name: "origin", pos: [0, 0, 0], scale: 1, skin: 0, source: "mesh" },
      { name: "bip01_pelvis", pos: [0.05, 0.0007, -1.0979], scale: 1, skin: 71, source: "mesh+ani" },
    ],
    animations: [{ file: "a_walk.ani", bones: 46, frames: 21, tick: 40, moving: 12 }],
    missing: ["父骨链未解：只知道每根骨在模型里的位置"] };
  const B = { mesh: "b_yifu.mesh", declared: 12, note: "", skin_bones: 0, skin_pairs: 0,
    nodes: [{ name: "bone001", pos: [1, 2, 3], scale: 1, skin: 0 }], animations: [], missing: [] };
  let gate = null;
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async (gid) => (gid === 245 ? new Promise((r) => { gate = () => r(A); }) : Promise.resolve(B)),
    },
  });
  await detail.module.showDetail(245);
  // 先切到另一只，再放 A 的回包——它必须被丢掉
  await detail.module.showDetail(999);
  await Promise.resolve(); await Promise.resolve();
  assert.ok(detail.el("skelTable").innerHTML.includes("bone001"), "B 的骨架该铺出来");
  gate();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  const sum = detail.el("skelSum").textContent;
  assert.ok(!sum.includes("46"), `A 的迟到回包不许覆盖 B：${sum}`);
  assert.ok(sum.includes("12"), "停在当前资产 B 的数字上");
  // 正常一路：A 单独来时表、动作、未解项都要有
  const d2 = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async (gid, mesh) => ({ ...A, mesh: mesh || A.meshes[0] }),
    },
  });
  await d2.module.showDetail(245);
  await Promise.resolve(); await Promise.resolve();
  assert.ok(d2.el("skelTable").innerHTML.includes("bip01_pelvis"), "骨名必须出现在表里");
  // 人话导语：第一句是白话，术语让位到折叠区
  const skelSum = d2.el("skelSum").textContent;
  assert.ok(skelSum.includes("46 根骨头"), `导语要说清一共几根骨：${skelSum}`);
  assert.ok(skelSum.includes("2 根的位置已经读出来"), `导语要说清位置读出几根：${skelSum}`);
  assert.ok(!skelSum.includes("绑定位移"), "导语是人话，术语不许出现");
  const skelFold = d2.el("skelTable").innerHTML;
  assert.ok(skelFold.includes("46 根骨全列在这里"), "术语版注记要住进折叠区");
  assert.ok(skelFold.includes("其中 2 根在 .mesh 里有绑定位移"), "带矩阵的有几根也要说");
  assert.ok(d2.el("skelAnims").innerHTML.includes("a_walk.ani"), "动作表要列出同组 .ani");
  assert.ok(d2.el("skelMissing").innerHTML.includes("父骨链"), "没解出来的东西必须同屏写明");
  assert.equal(d2.el("tabSkelCount").textContent, "3", "标签上的数字是骨表行数");
  // 只有名字、矩阵不在 .mesh 里的那根骨：不许留空行，也不许编一个坐标
  assert.ok(d2.el("skelTable").innerHTML.includes("矩阵不在 .mesh 里"), "没矩阵的骨要写清缺的是什么");
  assert.ok(!d2.el("skelTable").innerHTML.includes("NaN"), "不许把空坐标算成 NaN 摆出来");
  // 蒙皮权重已解：影响顶点数要逐骨列出来，带表的骨数要在导语里说得出
  const skelTable = d2.el("skelTable").innerHTML;
  assert.ok(skelTable.includes("影响顶点"), "表头该有「影响顶点」这一列");
  assert.ok(skelTable.includes(">71<"), `这根骨带 71 个影响顶点，表里要看得见：${skelTable.slice(0, 120)}`);
  assert.ok(skelTable.includes(">—<"), "根骨不带表就留破折号，不写 0 充数");
  assert.ok(skelSum.includes("26 根记着哪些皮肤顶点"), `导语要报得出带表的骨数：${skelSum}`);
  assert.ok(skelFold.includes("26 根带影响顶点表"), "术语版注记也要报得出带表的骨数");
  // 一组多份网格：手套那份没有影响表，必须能点到衣服那份去
  assert.equal(d2.el("skelPick").children.length, 2, "两份网格该给两颗筹码");
  d2.el("skelPick").children[1].onclick();
  await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
  assert.ok(d2.el("skelTable").innerHTML.includes("a_shoutao.mesh"), `注记要跟在手后换：${d2.el("skelSum").textContent}`);
});

test("同一组的重刷不许把用户从正在看的标签拽回预览", async () => {
  const skel = { mesh: "a_yifu.mesh", declared: 46, note: "",
    nodes: [{ name: "origin", pos: [0, 0, 0], scale: 1 }], animations: [], missing: [] };
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async () => skel,
    },
  });
  const pane = (n) => detail.panes.find((p) => p.dataset.pane === n);
  await detail.module.showDetail(245);
  await Promise.resolve(); await Promise.resolve();
  detail.get("panels.js").showTabPane("skeleton");
  assert.equal(pane("skeleton").hidden, false, "骨架页该显示");
  // 后台刷新会重新走一遍同一组的 showDetail——这时不能动用户所在的标签
  await detail.module.showDetail(245);
  await Promise.resolve(); await Promise.resolve();
  assert.equal(pane("skeleton").hidden, false, "重刷同一组，用户该还停在他打开的那一页");
  assert.equal(pane("preview").hidden, true, "预览页不该被强行掀回来");
  // 真换一组才回位
  await detail.module.showDetail(777);
  await Promise.resolve(); await Promise.resolve();
  assert.equal(pane("preview").hidden, false, "换了资产该回到第一眼那页");
});

test("动作页：点开才取数，拖游标只重画不再打后端", async () => {
  let calls = 0;
  const rep = {
    file: "a_walk.ani",
    files: ["a_walk.ani", "a_run.ani"],
    bones: 2,
    frames: 3,
    tick: 40,
    moving: 1,
    tracks: [
      { bone: "bip01",
        rotations: [[1, 0, 0, 0], [1, 0, 0, 0], [0.5, 0.5, 0, 0.707]],
        positions: [[0, 0, 0], [0, 0, 0], [0, 1, 0]], scales: [1, 1, 1] },
      { bone: "still",
        rotations: [[1, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]],
        positions: [[0, 0, 0], [0, 0, 0], [0, 0, 0]], scales: [1, 1, 1] },
    ],
    missing: ["父骨链未解：摆不出整具骨架怎么动"],
  };
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async () => ({ mesh: "a.mesh", declared: 0, nodes: [], animations: [], missing: [], note: "" }),
      animationView: async () => {
        calls++;
        return rep;
      },
    },
  });
  await detail.module.showDetail(245);
  await Promise.resolve(); await Promise.resolve();
  assert.equal(calls, 0, "没点开动作文，不该为一条 0.6 秒的取数白等");
  detail.el("animOnlyChanged").checked = true; // 真页面默认勾上，替身读不到 HTML 属性
  detail.get("panels.js").showTabPane("animation");
  // 桩里的 setTimeout 不会真的排程，只能用微任务把 async 链抽干
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(calls, 1, "点开动作页才取数");
  assert.ok(detail.el("animSum").textContent.includes("画布把顶点按这条动作摆出来"), `导语要说清画布摆的是哪路顶点：${detail.el("animSum").textContent}`);
  assert.ok(detail.el("animTable").innerHTML.includes("第 1 / 3 帧"), `帧数注记该从第 1 帧起：${detail.el("animTable").innerHTML.slice(0, 160)}`);
  assert.ok(detail.el("animTable").innerHTML.includes("没有骨在动"), "第 1 帧相对自己没变化");
  const slider = detail.el("animFrame");
  slider.value = "2";
  for (const f of slider.events.input || []) f({ target: slider });
  assert.equal(calls, 1, "拖游标只重画，不该再打后端");
  assert.ok(detail.el("animTable").innerHTML.includes("第 3 / 3 帧"), "游标与折叠区注记要同步");
  assert.ok(detail.el("animTable").innerHTML.includes("bip01"), "动过的骨要列出来");
  assert.ok(!detail.el("animTable").innerHTML.includes(">still<"), "勾了「只列变了的骨」就不该出现没动的骨");
  assert.ok(detail.el("animMissing").innerHTML.includes("父骨链"), "未解项要同屏写明");
  // 切动作：点筹码要走后端拿那一条
  const chip = detail.el("animPick").children[1];
  assert.ok(chip, "同组多条动作要给得出来");
  chip.onclick();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(calls, 2, "换一条动作要重新取数");
});

test("特效页：点开才取数，材质链要真列成表、参数块未解要同屏", async () => {
  const rep = {
    file: "a.pu", name: "a", group: "skill", label: "a_1",
    materials: ["x.mtl", "y.mtl"], textures: ["t.tga"], meshes: [], blends: ["add"],
    renderers: ["Billboard"], emitters: ["Circle"], updaters: ["TextureAnimator"],
    dynamics: ["dyn_random"], other: [], string_total: 59, files: ["a.pu"],
    param_floats: 72, param_bytes: 6739, anims: 0,
    missing: ["参数块的字段语法未解：块里 6739 字节、72 个像浮点的数", "播放未做"],
  };
  let calls = 0;
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async () => ({ mesh: "a.mesh", declared: 0, nodes: [], animations: [], missing: [], note: "" }),
      effectView: async () => {
        calls++;
        return rep;
      },
    },
  });
  await detail.module.showDetail(245);
  for (let i = 0; i < 4; i++) await Promise.resolve();
  assert.equal(calls, 0, "没点开特效页不该取数");
  detail.get("panels.js").showTabPane("effect");
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(calls, 1, "点开才取一次");
  const table = detail.el("fxTable").innerHTML;
  assert.ok(table.includes("x.mtl") && table.includes("y.mtl"), `材质链要列得出：${table.slice(0, 80)}`);
  assert.ok(!table.includes(">网格<"), "空的类别不摆行——空行不等于「没有」");
  assert.ok(detail.el("fxSum").textContent.includes("还没破译完"), "导语要说清参数还没破译完");
  assert.ok(!detail.el("fxSum").textContent.includes("参数块"), "导语是人话，术语不许出现");
  assert.ok(detail.el("fxTable").innerHTML.includes("6739"), "参数块大小要写进折叠区注记");
  assert.ok(detail.el("fxMissing").innerHTML.includes("参数块"), "字段语法未解必须同屏");
  assert.equal(detail.el("tabFxCount").textContent, "59");
  assert.equal(detail.el("fxPick").children.length, 0, "只登记一份特效时不该摆选择条");
});

test("特效页：一组登记多份 .pu 时要点名字能换，不许列着 A 的表写着 B 的名", async () => {
  const base = {
    name: "grp", group: "other", label: "", materials: ["a.mtl"], textures: [], meshes: [],
    blends: [], renderers: [], emitters: [], updaters: [], dynamics: [], other: [],
    string_total: 12, param_floats: 5, param_bytes: 2438, anims: 0,
    missing: ["参数块的字段语法未解：块里 2438 字节、5 个像浮点的数"],
    files: ["grp.pu", "w1351_boss_sss_mrb_rm_buff02.pu"],
  };
  const asked = [];
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async () => ({ mesh: "", declared: 0, nodes: [], animations: [], missing: [], note: "" }),
      effectView: async (gid, file) => {
        asked.push(file);
        const want = file === "w1351_boss_sss_mrb_rm_buff02.pu" ? base.files[1] : base.files[0];
        return { ...base, file: want, name: want.replace(/\.pu$/, "") };
      },
    },
  });
  await detail.module.showDetail(245);
  for (let i = 0; i < 4; i++) await Promise.resolve();
  detail.get("panels.js").showTabPane("effect");
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.deepEqual(asked, [""], "首屏要问「默认那一份」，把选择权交给后端");
  assert.ok(detail.el("fxTable").innerHTML.includes("grp.pu ·"), `默认该是本名那份：${detail.el("fxTable").innerHTML.slice(0, 120)}`);
  assert.ok(detail.el("fxTable").innerHTML.includes("还登记了 1 份"), "同组还有几份要写在折叠区注记上");
  assert.equal(detail.el("fxPick").children.length, 2, "两份都要给得出");
  detail.el("fxPick").children[1].onclick();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.deepEqual(asked.slice(-1), ["w1351_boss_sss_mrb_rm_buff02.pu"], "点这份就要这份");
  assert.ok(detail.el("fxTable").innerHTML.includes("w1351_boss_sss_mrb_rm_buff02.pu ·"), "表头文件名要跟着换");
  assert.ok(detail.el("fxTable").innerHTML.includes("a.mtl"), "换的仍是特效表");
});

test("材质页：点开才取数，槽位要列得出类型与原文，对不上实体的写「缺」", async () => {
  const rep = {
    file: "grp.mtl",
    files: ["grp.mtl", "template_default.mtl"],
    slots: [
      { role: "贴图", name: "w1351_a.tga", path: "data/effect/textures/w1351_a.tga" },
      { role: "着色器", name: "DynModelShader", path: "" },
      { role: "材质", name: "template_default.mtl", path: "data/sharematerial/template_default.mtl" },
    ],
    unresolved: 1,
    missing: ["1 个槽位在资源清单里对不上实体（界面写「缺」）——这是客户端的设计"],
  };
  const asked = [];
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async () => ({ mesh: "", declared: 0, nodes: [], animations: [], missing: [], note: "" }),
      materialView: async (gid, file) => {
        asked.push(file);
        const want = file === "template_default.mtl" ? file : "grp.mtl";
        return { ...rep, file: want };
      },
    },
  });
  await detail.module.showDetail(245);
  for (let i = 0; i < 4; i++) await Promise.resolve();
  assert.equal(asked.length, 0, "没点开材质页不该取数");
  detail.get("panels.js").showTabPane("material");
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.deepEqual(asked.slice(0, 1), [""], "首屏问「默认那一份」");
  const table = detail.el("mtlTable").innerHTML;
  assert.ok(table.includes("w1351_a.tga"), `贴图槽位要列得出：${table.slice(0, 90)}`);
  assert.ok(table.includes("data/effect/textures/w1351_a.tga"), "对得上实体的要报出路径");
  assert.ok(table.includes(">缺<"), "对不上的写「缺」，不猜一个名字顶上");
  assert.ok(table.includes("着色器"), "槽位类型要原样列");
  assert.ok(detail.el("mtlMissing").innerHTML.includes("客户端的设计"), "「缺」是设计这件事必须同屏");
  assert.equal(detail.el("tabMtlCount").textContent, "3", "标签上的数字是槽位数");
  assert.equal(detail.el("mtlPick").children.length, 2, "两份材质该给两颗筹码");
  detail.el("mtlPick").children[1].onclick();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.deepEqual(asked.slice(-1), ["template_default.mtl"], "点这份就要这份");
  assert.ok(detail.el("mtlTable").innerHTML.includes("template_default.mtl · 槽位"), "表头文件名要跟着换");
});

test("筹码区有上限：巨无霸组不许把要看的表挤出屏幕", async () => {
  const ui = await sandbox("ui.js", {});
  const node = ui.makeEl ? null : null;
  // 替身 DOM 要跟真 DOM 一样：innerHTML = "" 必须把子节点清掉，
  // 不然「重画」在这里看起来像「追加」，测出来的数永远是错的。
  const box = {
    children: [],
    _html: "",
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; if (v === "") this.children = []; },
    appendChild(c) { this.children.push(c); },
  };
  // 直接验纯逻辑：838 项只摆 24 颗，并说明还剩多少
  ui.module.chips(box, Array.from({ length: 838 }, (_, i) => ({ value: `f${i}.mdl`, label: `f${i}` })), "f900", () => {}, 24);
  const 按钮 = box.children.filter((c) => c.className === "chip");
  assert.equal(按钮.length, 24, `只该摆 24 颗，实际 ${按钮.length}`);
  const 说明 = box.children.find((c) => c.className === "chip-more");
  assert.ok(说明 && /还有 814 项/.test(说明.textContent), `要写明还剩多少：${说明 && 说明.textContent}`);
  // 说明不能只是一句话：点它要把下一批真的摆出来，否则是指路给一个不存在的地方
  assert.equal(typeof 说明.onclick, "function", "这句说明得能点");
  说明.onclick();
  const 第二次 = box.children.filter((c) => /^chip( |$)/.test(String(c.className)));
  assert.equal(第二次.length, 124, `点一次该多出 100 颗，实际 ${第二次.length}`);
  assert.ok(box.children.find((c) => c.className === "chip-more" && /还有 714 项/.test(c.textContent)), "剩下的数要跟着减");
});

test("筹码区当前选中的那颗即使排在 cap 之后也要摆出来", async () => {
  const ui = await sandbox("ui.js", {});
  // 替身 DOM 要跟真 DOM 一样：innerHTML = "" 必须把子节点清掉，
  // 不然「重画」在这里看起来像「追加」，测出来的数永远是错的。
  const box = {
    children: [],
    _html: "",
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = v; if (v === "") this.children = []; },
    appendChild(c) { this.children.push(c); },
  };
  const opts = Array.from({ length: 60 }, (_, i) => ({ value: `f${i}.mdl`, label: `f${i}` }));
  ui.module.chips(box, opts, "f59.mdl", () => {}, 24);
  // 选中的那颗会被 markChips 加成 class="chip on"，按等号筛会把它漏掉——
  // 这条断言验的正是「选中的那颗在不在」，别被自己的筛法筛没了。
  const 值 = box.children
    .filter((c) => /^chip( |$)/.test(String(c.className)))
    .map((c) => String(c.innerHTML));
  assert.ok(值.some((h) => h.includes("f59")), "选中那颗不见了，用户会以为没选上");
  assert.equal(值.length, 25, `前 24 颗 + 选中那颗，实际 ${值.length}`);
  assert.ok(box.children.some((c) => String(c.className).includes("on")), "选中态要打上");
});

test("材质页也管模型定义：.mdl 组要列得出骨架与网格·材质对，不许绕开本名去列别份", async () => {
  const rep = {
    file: "grp.mdl",
    files: ["grp.mdl", "a.mtl"],
    kind: "模型定义",
    model_name: "grp_model",
    base_dir: "data/source/npc/model/grp/",
    skeletons: [{ role: "骨架", name: "grp.ske", path: "data/source/npc/model/grp/grp.ske" }],
    bodies: [{ label: "LOD0", mesh: "grp_body.mesh", mesh_path: "", material: "a.mtl", material_path: "data/x/a.mtl" }],
    others: ["tx_head", "variation_01"],
    slots: [],
    unresolved: 0,
    missing: ["挂点/变体这些剩下的字符串按文件出现序原样带着（列在「其他名字」里），语义没断言"],
  };
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async () => ({ mesh: "", declared: 0, nodes: [], animations: [], missing: [], note: "" }),
      materialView: async () => rep,
    },
  });
  await detail.module.showDetail(245);
  for (let i = 0; i < 4; i++) await Promise.resolve();
  detail.get("panels.js").showTabPane("material");
  for (let i = 0; i < 8; i++) await Promise.resolve();
  const sum = detail.el("mtlSum").textContent;
  assert.ok(sum.includes("说明书"), `导语要说清这屏是模型说明书：${sum}`);
  assert.ok(sum.includes("一共 2 条"), `导语要报条数：${sum}`);
  assert.ok(detail.el("mtlTable").innerHTML.includes("模型定义"), "术语注记要住进折叠区");
  assert.ok(detail.el("mtlTable").innerHTML.includes("模型名 grp_model"), "模型名要看得见");
  const table = detail.el("mtlTable").innerHTML;
  assert.ok(table.includes("grp.ske"), "骨架引用要列出来");
  assert.ok(table.includes("grp_body.mesh"), "网格要列出来");
  assert.ok(table.includes("a.mtl"), "材质要列出来");
  assert.ok(table.includes("LOD0"), "段名/LOD 标签要跟着，不然多组时分不清谁是谁");
  assert.ok(table.includes(">缺<"), "对不上实体的那行写「缺」");
  assert.ok(table.includes("tx_head"), "其他名字原样带着，不丢掉");
  assert.ok(detail.el("mtlMissing").innerHTML.includes("语义没断言"), "不许把挂点说成已看懂");
  assert.equal(detail.el("tabMtlCount").textContent, "2", "标签上的数是骨架+网格材质对的条数");
});

test("换资产要立刻清空骨架/动作/特效三页，不许留着上一件的文字", async () => {
  const skelA = { mesh: "a_yifu.mesh", declared: 1, note: "", animations: [], missing: [],
    nodes: [{ name: "aaa_only_in_A", pos: [0, 0, 0], scale: 1 }] };
  const skelB = { mesh: "", declared: 0, nodes: [], animations: [], missing: [],
    note: "这一组里没有网格文件，骨架跟着网格走。" };
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async (gid) => (gid === 245 ? skelA : skelB),
      animationView: async () => {
        throw new Error("这一组旁边没有 ani/ 目录");
      },
      effectView: async () => {
        throw new Error("这一组里没有特效文件");
      },
    },
  });
  await detail.module.showDetail(245);
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.ok(detail.el("skelTable").innerHTML.includes("aaa_only_in_A"), "夹具得先真铺上 A 的骨架，否则下面的空断言没意义");
  await detail.module.showDetail(999);
  // 换的那一瞬间就该是空的——旧文字挂在新资产上是编故事
  assert.equal(detail.el("skelTable").innerHTML, "", "换资产的瞬间必须清掉上一件的表");
  assert.equal(detail.el("tabSkelCount").textContent, "", "标签上的数字也要跟着清");
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.ok(!detail.el("skelTable").innerHTML.includes("aaa_only_in_A"), "B 不许带着 A 的骨名");
  assert.ok(detail.el("skelSum").textContent.includes("没有网格文件"), `B 该带上自己的原因：${detail.el("skelSum").textContent}`);
});

// 「挂在谁」这一列（2026-10-05 父骨链解出后加的）。要钉住三件事：
// 列整列有或整列无（看回包里有没有 parent/root，不许摆半列空「—」）；
// 挂在谁写在骨名旁边、指向父骨原文名；链上补进来的行（source="chain"、矩阵不在
// .mesh 里）的 colspan 只许盖住数值四列，多盖一格就是把「影响顶点」顶串。
test("骨架页：读出挂接才加「挂在谁」列，补进行与有矩阵的行各归各位", async () => {
  const panels = await sandbox("panels.js");
  const 链 = {
    mesh: "a_yifu.mesh", meshes: ["a_yifu.mesh"], declared: 4,
    skin_bones: 1, skin_pairs: 71, chain: true, animations: [], missing: [],
    nodes: [
      { name: "bip01", pos: null, scale: null, skin: 0, source: "ani", parent: null, root: true },
      { name: "bip01_pelvis", pos: [0.05, 0, -1.09], scale: 1, skin: 71, source: "mesh+ani", parent: "bip01", root: false },
      { name: "body_center", pos: null, scale: null, skin: 0, source: "chain", parent: "bip01_pelvis", root: false },
    ],
  };
  panels.module.paintSkeleton(链, noop);
  const html = panels.el("skelTable").innerHTML;
  assert.ok(html.includes("<th>挂在谁</th>"), `有挂接就得有这一列：${html.slice(0, 200)}`);
  assert.ok(html.includes("<td>bip01_pelvis</td><td>bip01</td>"), "挂在谁要紧跟骨名，指向父骨原文名");
  assert.ok(html.includes(">这是根<"), "根骨要说它是根，不许留破折号");
  assert.ok(
    html.includes('<td>body_center</td><td>bip01_pelvis</td><td class="dim" colspan="4">矩阵不在 .mesh 里</td>'),
    "链上补进来的行要带着挂接，且 colspan 只盖数值四列",
  );
  assert.ok(panels.el("skelSum").textContent.includes("谁挨着谁"), "导语也要跟着 chain 翻出那句人话");
  // 列对齐：每行按 colspan 展开后的格数都得等于表头列数，哪一行串了列就是这条不过
  const 行 = [...html.matchAll(/<tr>([\s\S]*?)<\/tr>/g)].map((m) => m[1]);
  assert.ok(行.length >= 2, "表头加骨行至少两行，正则没吃到说明 HTML 变了");
  const cols = 行[0].match(/<th>/g).length;
  for (const r of 行.slice(1)) {
    const n = [...r.matchAll(/<td([^>]*)>/g)].reduce((a, [, attrs]) => {
      const span = attrs.match(/colspan="(\d+)"/);
      return a + (span ? Number(span[1]) : 1);
    }, 0);
    assert.equal(n, cols, `这一行按 colspan 展开后 ${n} 格，对不上表头 ${cols} 列：${r}`);
  }
  // 没读出挂接的回包（老格式 / 静态网格）：一字不多，别摆一列破折号充数
  const 无链 = {
    mesh: "b.mesh", meshes: ["b.mesh"], declared: 1, skin_bones: 0, skin_pairs: 0,
    chain: false, animations: [], missing: [],
    nodes: [{ name: "bone001", pos: [1, 2, 3], scale: 1, skin: 0, parent: null, root: false }],
  };
  panels.module.paintSkeleton(无链, noop);
  const html2 = panels.el("skelTable").innerHTML;
  assert.ok(!html2.includes("挂在谁"), `没挂接就不该有这一列：${html2.slice(0, 200)}`);
  assert.ok(!panels.el("skelSum").textContent.includes("谁挨着谁"), "导语同理，没读出挂接就不补那句");
});

// ---------------------------------------------------------------------------
// 动作页 3D 预览（anim_pose）：接线、在途闸门、播放、降级、切资产清状态。
// viewer 用替身——WebGL 在 node 里开不了，这里钉的是 detail.js 的时序，
// setPose 自己的校验（顶点数/有限数）由 mesh-viewer 的实现与网格页测试盯着。
// ---------------------------------------------------------------------------

const ANIM_REP = {
  file: "a_walk.ani",
  files: ["a_walk.ani", "a_run.ani"],
  bones: 2,
  frames: 3,
  tick: 40,
  moving: 1,
  tracks: [
    { bone: "bip01",
      rotations: [[1, 0, 0, 0], [1, 0, 0, 0], [0.5, 0.5, 0, 0.707]],
      positions: [[0, 0, 0], [0, 0, 0], [0, 1, 0]], scales: [1, 1, 1] },
    { bone: "still",
      rotations: [[1, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]],
      positions: [[0, 0, 0], [0, 0, 0], [0, 0, 0]], scales: [1, 1, 1] },
  ],
  missing: [],
};

/// 一份合格的 anim_pose 回包（契约见命令包装处的注释：camelCase、positions 同序）。
const poseReply = (mesh, frame, extra = {}) => ({
  mesh,
  anim: "a_walk.ani",
  frame,
  frames: 3,
  vertexCount: 4,
  positions: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
  notes: ["锚定口径：顶点按这条动作的第 1 帧对齐。"],
  ...extra,
});

/// 把第 frame 帧那张在途请求从队列里取走（resolve 一次就作废，别重复拿）。
function take(deferred, frame) {
  const i = deferred.findIndex((d) => d.frame === frame);
  assert.ok(i >= 0, `没有第 ${frame} 帧的在途 pose 请求（现有：${deferred.map((d) => d.frame)}）`);
  return deferred.splice(i, 1)[0];
}

async function poseSandbox(expose = "") {
  const poseCalls = [];
  const meshDataCalls = [];
  const deferred = [];
  const viewers = [];
  class FakeViewer {
    constructor(canvas) {
      this.canvas = canvas;
      this.loads = [];
      this.poses = [];
      viewers.push(this);
    }
    load(data, bones) {
      this.loads.push({ data, bones });
    }
    setPose(p) {
      this.poses.push(p);
      return true;
    }
    draw() {}
    stop() {}
  }
  const detail = await sandbox("detail.js", {
    "mesh.js": meshMock,
    "mesh-viewer.js": { MeshViewer: FakeViewer },
    "api.js": {
      cardDetail: async () => fixtures.DETAIL_A,
      assetInspect: async () => fixtures.INSPECT_A,
      skeletonView: async (gid) =>
        gid === 245
          ? { mesh: "a_yifu.mesh", meshes: ["a_yifu.mesh", "a_shoutao.mesh"], declared: 0, nodes: [], animations: [], missing: [], note: "" }
          : { mesh: "b_only.mesh", meshes: ["b_only.mesh"], declared: 0, nodes: [], animations: [], missing: [], note: "" },
      meshData: async (name, hash) => {
        meshDataCalls.push({ name, hash });
        return { path: name, vertexCount: 4, faceCount: 2, buffer: "", hasNormals: false, hasUvs: false };
      },
      animationView: async () => ANIM_REP,
      animPose: async (gid, anim, mesh, frame) => {
        poseCalls.push({ gid, anim, mesh, frame });
        return new Promise((resolve) => deferred.push({ gid, mesh, frame, resolve }));
      },
    },
  }, expose ? { "detail.js": expose } : {});
  const drain = async (n = 14) => {
    for (let i = 0; i < n; i++) await Promise.resolve();
  };
  return { detail, poseCalls, meshDataCalls, deferred, viewers, drain };
}

test("动作页 3D 预览：游标→pose 参数正确、在途只留最新、切资产后陈旧回包丢弃", async () => {
  const { detail, poseCalls, deferred, viewers, drain } = await poseSandbox();
  await detail.module.showDetail(245);
  await drain();
  assert.equal(poseCalls.length, 0, "没点开动作页不该问 pose");
  detail.get("panels.js").showTabPane("animation");
  await drain();
  assert.deepEqual(
    poseCalls,
    [{ gid: 245, anim: "a_walk.ani", mesh: "a_yifu.mesh", frame: 0 }],
    "首帧 pose 的参数：组号 / 动作文件 / 默认第一份网格 / 第 0 帧",
  );
  const viewer = viewers[0];
  assert.ok(viewer, "预览 viewer 该建出来");
  assert.equal(viewer.loads.length, 1, "几何取一次");
  assert.equal(viewer.loads[0].bones, null, "动作预览不摆骨线——那是网格页绑定姿态的事");
  assert.equal(detail.el("animPoseBox").hidden, false, "画布块该露出来");
  take(deferred, 0).resolve(poseReply("a_yifu.mesh", 0));
  await drain();
  assert.equal(viewer.poses.length, 1, "第 0 帧的顶点要摆进画布");
  assert.ok(detail.el("animPoseNote").textContent.includes("锚定口径"), `注记行取回包 notes 的第一条：${detail.el("animPoseNote").textContent}`);
  // 游标连动：在途时只保留最新一帧，不排队积压
  const slider = detail.el("animFrame");
  const move = (v) => {
    slider.value = v;
    for (const f of slider.events.input || []) f({ target: slider });
  };
  move("2");
  move("1");
  await drain();
  assert.equal(poseCalls.length, 2, "在途期间游标再动不该叠出第二个请求");
  take(deferred, 2).resolve(poseReply("a_yifu.mesh", 2));
  await drain();
  assert.deepEqual(poseCalls.map((c) => c.frame), [0, 2, 1], "回包落地后补发的必须是攒下的最新帧");
  take(deferred, 1).resolve(poseReply("a_yifu.mesh", 1));
  await drain();
  assert.equal(viewer.poses.length, 3);
  // 资产切走：在途回包必须被丢，预览收摊，不许把旧怪的姿势或错误留给新怪
  move("2");
  await detail.module.showDetail(999);
  assert.equal(detail.el("animPoseBox").hidden, true, "切资产立刻收掉预览");
  take(deferred, 2).resolve(poseReply("a_yifu.mesh", 2));
  await drain();
  assert.equal(viewer.poses.length, 3, "陈旧回包不得再进画布");
  assert.equal(detail.el("animPoseErr").hidden, true, "被丢的回包也不该冒出错误行");
});

test("动作页 3D 预览：播放步进到尾回卷、暂停恢复、切走 tab 自动停", async () => {
  const { detail, poseCalls, deferred, drain } = await poseSandbox("\nexport { playStep, setPlaying };");
  await detail.module.showDetail(245);
  await drain();
  detail.get("panels.js").showTabPane("animation");
  await drain();
  take(deferred, 0).resolve(poseReply("a_yifu.mesh", 0));
  await drain();
  const btn = detail.el("animPlay");
  // 按钮的初始文案/可读名是 index.html 的静态属性，替身 DOM 不含它，按源码钉
  const html = fs.readFileSync(path.join(web, "index.html"), "utf8");
  assert.match(html, /<button type="button" id="animPlay" class="mini" aria-label="播放">播放<\/button>/, "播放按钮初始态：文案与可读名都是「播放」");
  assert.match(html, /<canvas id="animCanvas" aria-label="动作预览"><\/canvas>/, "画布要带「动作预览」的可读名");
  assert.match(html, /id="animPlayHint"[^>]*>参考速度</, "按钮旁要有「参考速度」小字");
  assert.ok(!/25\s*fps/.test(html), "帧率刻度含义未证，不许把 25fps 当真值写进页面");
  detail.module.setPlaying(true);
  assert.equal(btn.textContent, "暂停", "播放中按钮要说「暂停」");
  assert.equal(btn.getAttribute("aria-label"), "暂停");
  assert.equal(detail.el("animFrame").value, "1", "点播放立刻走一步");
  // 替身定时器不跑，手动步进；每步都同步游标值并把当前帧交给 pose
  take(deferred, 1).resolve(poseReply("a_yifu.mesh", 1));
  await drain();
  detail.module.playStep();
  assert.equal(detail.el("animFrame").value, "2");
  take(deferred, 2).resolve(poseReply("a_yifu.mesh", 2));
  await drain();
  detail.module.playStep();
  assert.equal(detail.el("animFrame").value, "0", "到尾要回卷，别停在最后一帧");
  assert.deepEqual(poseCalls.map((c) => c.frame), [0, 1, 2, 0], "每步都要把当前帧交给 pose");
  detail.module.setPlaying(false);
  assert.equal(btn.textContent, "播放", "再点一次回到「播放」");
  assert.equal(btn.getAttribute("aria-label"), "播放");
  // 切走 tab 自动暂停
  detail.module.setPlaying(true);
  assert.equal(btn.textContent, "暂停");
  detail.get("panels.js").showTabPane("skeleton");
  assert.equal(btn.textContent, "播放", "切走 tab 该自动暂停");
  assert.equal(btn.getAttribute("aria-label"), "播放");
});

test("动作页 3D 预览：部件筹码换网格、坏回包降级成一行话、切资产清网格缓存", async () => {
  const { detail, poseCalls, meshDataCalls, deferred, viewers, drain } = await poseSandbox();
  await detail.module.showDetail(245);
  await drain();
  detail.get("panels.js").showTabPane("animation");
  await drain();
  assert.deepEqual(meshDataCalls[0], { name: "a_yifu.mesh", hash: null }, "取几何按路径找，hash 传 null");
  take(deferred, 0).resolve(poseReply("a_yifu.mesh", 0));
  await drain();
  // 坏回包：没有顶点 → 画布下一行人话，关键帧表格与游标照常
  const slider = detail.el("animFrame");
  const move = (v) => {
    slider.value = v;
    for (const f of slider.events.input || []) f({ target: slider });
  };
  move("1");
  take(deferred, 1).resolve({ mesh: "a_yifu.mesh", anim: "a_walk.ani", frame: 1, frames: 3, notes: [] });
  await drain();
  assert.equal(detail.el("animPoseErr").hidden, false, "坏回包的错误行要露出来");
  assert.ok(detail.el("animPoseErr").textContent.includes("这一帧没摆出来"), `坏回包要说人话：${detail.el("animPoseErr").textContent}`);
  // 好回包来了把错误行收掉
  move("2");
  take(deferred, 2).resolve(poseReply("a_yifu.mesh", 2));
  await drain();
  assert.equal(detail.el("animPoseErr").hidden, true, "摆出来之后错误行要收掉");
  // 部件筹码：点哪份就取哪份的几何、摆哪份的顶点
  const pick = detail.el("animMeshPick");
  assert.equal(pick.children.length, 2, "两份网格该给两颗筹码");
  pick.children[1].onclick();
  await drain();
  assert.deepEqual(meshDataCalls[meshDataCalls.length - 1], { name: "a_shoutao.mesh", hash: null }, "点这份就要这份的几何");
  take(deferred, 2).resolve(poseReply("a_shoutao.mesh", 2));
  await drain();
  assert.deepEqual(
    poseCalls[poseCalls.length - 1],
    { gid: 245, anim: "a_walk.ani", mesh: "a_shoutao.mesh", frame: 2 },
    "换网格后摆的是当前帧",
  );
  assert.equal(viewers[0].loads.length, 2, "换网格要重新 load 几何");
  // 切资产：网格清单缓存失效——新资产的清单与几何都按新的组号取
  await detail.module.showDetail(999);
  detail.get("panels.js").showTabPane("animation");
  await drain();
  assert.deepEqual(meshDataCalls[meshDataCalls.length - 1], { name: "b_only.mesh", hash: null }, "切资产后网格缓存必须失效");
  assert.equal(detail.el("animMeshPick").children.length, 0, "只有一份网格不摆筹码");
  assert.ok(detail.el("animPoseMeta").textContent.includes("b_only.mesh"), `meta 行要写实际用的网格（客户端原文）：${detail.el("animPoseMeta").textContent}`);
});
