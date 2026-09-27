// 入口层与持久化的防呆测试。跑法（在 app/ 下）：
//   node --test tests/state.test.js
//
// 分两部分：
//   1) state.js 的载入净化（纯逻辑，node 里直接跑）；
//   2) app.js / health.js / index.html 的接线防呆——DOM 在 node 里开不了，
//      只能钉源码：关键语句被人顺手删掉时这里要红（参考 browseDom.test.js）。

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { state, loadState, normalizeView } from "../web/state.js";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "web");
const appJs = readFileSync(join(web, "app.js"), "utf8");
const healthJs = readFileSync(join(web, "health.js"), "utf8");
const html = readFileSync(join(web, "index.html"), "utf8");

// ---- 1) 载入净化（localStorage 兼容）----

// loadState 吃 localStorage：node 没有，摆一个最小桩。
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
};

function load(json) {
  store.set("tlbb-explorer-ui", json);
  loadState();
}

test("view 只有两个合法值：非法值一律落回浏览，绝不猜", () => {
  assert.equal(normalizeView("assets"), "assets");
  assert.equal(normalizeView("browse"), "browse");
  assert.equal(normalizeView("foo"), "browse");
  assert.equal(normalizeView(undefined), "browse");
  assert.equal(normalizeView(123), "browse");
  assert.equal(normalizeView(null), "browse");
});

test("老存档没有 view/browsePak 字段：默认值接管，其余字段照旧恢复", () => {
  assert.equal(state.view, "browse"); // 全新进程的模块默认值
  load(JSON.stringify({ query: "曹霜", kind: "全部", selected: 245 }));
  assert.equal(state.query, "曹霜");
  assert.equal(state.selected, 245);
  assert.equal(state.view, "browse", "老存档没写过 view → 默认第一屏是浏览");
  assert.equal(state.browsePak, "");
});

test("存档里的 view：合法值保留，坏值落回浏览", () => {
  load(JSON.stringify({ view: "assets" }));
  assert.equal(state.view, "assets");
  load(JSON.stringify({ view: "主页" }));
  assert.equal(state.view, "browse");
});

test("selected / browsePak 的坏值不许混进状态", () => {
  load(JSON.stringify({ selected: "abc", browsePak: 42 }));
  assert.equal(state.selected, 0, "非数字编号会去查一条不存在的资产");
  assert.equal(state.browsePak, "");
  load(JSON.stringify({ selected: "245", browsePak: "data.pak" }));
  assert.equal(state.selected, 245, "数字串宽容收下");
  assert.equal(state.browsePak, "data.pak");
  load(JSON.stringify({ selected: -5 }));
  assert.equal(state.selected, 0);
});

// ---- 2) 入口接线防呆（源码断言）----

/// 取 src 里 start 到 end 之间的源码（两个都是稳定锚点）。
function between(src, start, end) {
  const i = src.indexOf(start);
  const j = src.indexOf(end, i + start.length);
  assert.ok(i >= 0, `找不到 ${start}`);
  assert.ok(j > i, `找不到 ${end}`);
  return src.slice(i, j);
}

test("浏览首屏启动不许碰 stats/list：模块顶层没有无守卫的 refreshStats()/refresh()", () => {
  // 曾经模块末尾无条件跑 refreshStats()+refresh()：view=browse 启动也会调
  // stats/list_groups，后端就把懒预热当启动了，顶栏「浏览不依赖资产库」成了
  // 谎话，restoreDetail 还会把资产详情画进藏着的资产视图。初始化只许走
  // initAssets()（assetsInited 闸门管着）。
  assert.ok(!/^refreshStats\(\)/m.test(appJs), "顶层 refreshStats() 会替浏览首屏触发预热");
  assert.ok(!/^refresh\(\)/m.test(appJs), "顶层 refresh() 会替浏览首屏触发预热");
  assert.match(appJs, /if \(state\.view === "assets"\) \{\s*initAssets\(\);/);
  assert.match(appJs, /showTab\(state\.view\)/, "loadState 已收窄 view，启动分支不该再猜一遍");
  // 浏览启动分支赋给顶栏的那句话必须说清「不依赖」：不许冒充「正在读取」。
  const msg = appJs.match(/progressText"\)\.textContent = "([^"]+)"/);
  assert.ok(msg, "启动分支要给顶栏一句人话");
  assert.ok(msg[1].includes("浏览不依赖资产库"), msg[1]);
  assert.ok(!msg[1].includes("正在读取"), msg[1]);
});

test("initAssets：懒预热只跑一次，startWarm 失败不能拦住 stats/list 的恢复", () => {
  const seg = between(appJs, "function initAssets()", 'el("tabAssets").addEventListener');
  assert.match(seg, /if \(assetsInited\) return;/);
  assert.match(seg, /assetsInited = true;/);
  assert.match(seg, /api\.startWarm\(\)\.catch/);
  assert.match(seg, /refreshStats\(\)\.then\(restoreDetail\)/);
  assert.match(seg, /refresh\(\)/);
});

test("Esc 要清浏览视图的 treeFilter：清值 + 补发 input 让 browse.js 把树画回整棵", () => {
  // clearBox 定义在键盘监听之前，一并圈进来。
  const seg = between(appJs, "function clearBox(box)", "let lastAction = 0;");
  assert.match(seg, /e\.target === el\("treeFilter"\)/, "treeFilter 没有 Esc 清空是已知遗留");
  assert.match(seg, /dispatchEvent\(new Event\("input"/, "只清值不发事件，列表会停在搜索结果上");
  assert.match(seg, /e\.target === el\("q"\)/, "资产视图的 q 清空分支还在");
});

test("Ctrl+F 与 / 按视图聚焦：浏览聚焦 treeFilter，资产聚焦 q", () => {
  const seg = between(appJs, "function focusSearchBox", 'document.addEventListener("keydown"');
  assert.match(
    seg,
    /state\.view === "browse" \? el\("treeFilter"\) : el\("q"\)/,
    "浏览视图里聚焦藏在资产视图里的 q 等于没反应",
  );
  const keys = between(appJs, "Ctrl+F", "moveSelect");
  assert.match(keys, /focusSearchBox\(\);/, "Ctrl+F 与 / 都要走同一个分流");
});

test("↑↓ 选行只在资产视图生效：浏览视图不该把详情画进藏着的面板", () => {
  const seg = between(appJs, "state.view === \"assets\" &&", "if (moveSelect");
  assert.match(seg, /ArrowDown/);
  assert.match(seg, /ArrowUp/);
});

test("skip-link 跟着当前视图瞄准，不再指向死锚点 #list", () => {
  assert.match(appJs, /function aimSkipLink\(\)/);
  assert.match(appJs, /el\("tabBrowse"\)\.addEventListener\("click", aimSkipLink\)/);
  assert.match(appJs, /el\("tabAssets"\)\.addEventListener\("click", aimSkipLink\)/);
  assert.match(html, /id="skipLink"/);
  assert.ok(!html.includes('href="#list"'), "死锚点 #list 已不存在");
  for (const id of ["browseView", "assetsView"]) {
    assert.ok(html.includes(`id="${id}"`), `缺 #${id}`);
    assert.match(html, new RegExp(`id="${id}"[^>]*tabindex="-1"`), `#${id} 要能接住跳转的焦点`);
  }
});

test("顶栏进度行初始不许说「正在读取…」——预热还没开始就是一句谎", () => {
  const m = html.match(/id="progressText"[^>]*>([^<]*)</);
  assert.ok(m, "progressText 在 index.html 里");
  assert.ok(!m[1].includes("正在读取"), `初始文案不该是「${m[1]}」`);
});

test("浏览视图的树搜索框要有无障碍名（placeholder 不能当 label）", () => {
  assert.match(html, /id="treeFilter"[^>]*aria-label="/);
});

test("库状态浮层：预热从未跑过时给指路文案，不把「还没读」摆成全 0", () => {
  const seg = between(healthJs, "export async function openHealth", "export function closeHealth");
  assert.match(seg, /state\.stats && state\.stats\.totalGroups > 0/, "冷启动要有闸，ref_health 不触发预热");
  assert.match(seg, /它还没开始读取/, "误导性的「读取中 0%」换成人话");
  assert.match(seg, /el\("tabAssets"\)\.click\(\)/, "指路要给出路：走顶栏标签自己的切换流程");
  assert.match(seg, /已读部分的统计/, "预热中途的统计要说明只是部分真相");
  assert.match(seg, /state\.view === "browse" \? "返回浏览" : "返回资产"/, "退回按钮按进入时的视图说话");
});
