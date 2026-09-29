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
}

/// 加载 entry 及其相对依赖：mock 里的路径换成假导出，expose 往真文件尾部追加 export。
async function sandbox(entry, mock = {}, expose = {}) {
  const elements = new Map();
  const el = (id) => {
    if (!elements.has(id)) elements.set(id, new Element());
    return elements.get(id);
  };
  const panes = ["preview", "resource", "relations", "missing", "files", "origin"].map((pane) =>
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
