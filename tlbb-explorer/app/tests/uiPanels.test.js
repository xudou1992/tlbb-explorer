// 新增 UI 模块的接线防呆：panels.js / relations.js / index.html 三方对齐。
// 跑法（在 app/ 下）：node --test tests/uiPanels.test.js
//
// 与别的测试同一套路：DOM 在 node 里开不了，只能钉源码与 id 对应关系。
// 重点盯两件事：① 新模块 el("x") 引用的 id 在 index.html 里都真有；
// ② 详情标签页的 data-pane 与 HTML 里的 tabpane 一一对上。

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "web");

const html = readFileSync(join(web, "index.html"), "utf8");
const panels = readFileSync(join(web, "panels.js"), "utf8");
const relations = readFileSync(join(web, "relations.js"), "utf8");
const detail = readFileSync(join(web, "detail.js"), "utf8");

/// 提取一份源码里所有 el("id") 的静态 id 引用。
function idsIn(src) {
  return [...src.matchAll(/el\("([^"]+)"\)/g)].map((m) => m[1]);
}

const TABS = ["preview", "resource", "relations", "missing", "files", "origin"];

test("panels.js 引用的每个元素 id 都在 index.html 里", () => {
  const used = idsIn(panels);
  assert.ok(used.length > 6, `应能提取到 id 引用，实际 ${used.length}`);
  const missing = [...new Set(used)].filter((id) => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, [], `这些 id 在 index.html 里找不到：${missing.join(", ")}`);
});

test("relations.js 引用的每个元素 id 都在 index.html 里", () => {
  const used = idsIn(relations);
  assert.ok(used.length > 3, `应能提取到 id 引用，实际 ${used.length}`);
  const missing = [...new Set(used)].filter((id) => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, [], `这些 id 在 index.html 里找不到：${missing.join(", ")}`);
});

test("detail.js 引用的每个元素 id 都在 index.html 里", () => {
  const used = idsIn(detail);
  // texSlotPick 是 lib/textureState.js 铺候选卡时动态生成的 <select>，
  // 不在 index.html 里，属于白名单（textureState.test.js 另有断言盯着它）。
  const dynamic = new Set(["texSlotPick"]);
  const missing = [...new Set(used)].filter((id) => !dynamic.has(id) && !html.includes(`id="${id}"`));
  assert.deepEqual(missing, [], `这些 id 在 index.html 里找不到：${missing.join(", ")}`);
});

test("六个标签按钮的 data-tab 与六个面板的 data-pane 一一对上", () => {
  const tabs = [...html.matchAll(/class="tab[^"]*"\s+data-tab="([^"]+)"/g)].map((m) => m[1]);
  // 第一个「预览」标签 class 是 "tab on"，单独补一遍正则匹配
  const allTabs = [...html.matchAll(/data-tab="([^"]+)"/g)].map((m) => m[1]);
  assert.ok(allTabs.length >= TABS.length, `标签数不足：${allTabs.join(",")}`);
  const panes = [...html.matchAll(/data-pane="([^"]+)"/g)].map((m) => m[1]);
  for (const t of TABS) {
    assert.ok(allTabs.includes(t), `缺标签按钮 data-tab=${t}`);
    assert.ok(panes.includes(t), `缺面板 data-pane=${t}`);
  }
  assert.equal(new Set(allTabs).size, allTabs.length, "标签 data-tab 不许重复");
  assert.equal(new Set(panes).size, panes.length, "面板 data-pane 不许重复");
  void tabs;
});

test("切标签只改一处：按钮高亮与面板显隐同源", () => {
  const seg = panels.slice(panels.indexOf("export function showTabPane"), panels.indexOf("let tabsWired"));
  assert.match(seg, /classList\.toggle\("on", b\.dataset\.tab === name\)/);
  assert.match(seg, /p\.hidden = p\.dataset\.pane !== name/);
});

test("换资产回到「预览」标签：不让人对着上一条的缺失清单发懵", () => {
  assert.match(detail, /showTabPane\("preview"\)/);
});

test("失败/未就绪也要把右栏清干净，不留上一条的概况", () => {
  const seg = detail.slice(detail.indexOf("export async function showDetail"));
  assert.ok((seg.match(/paintSide\(null\)/g) || []).length >= 2, "未就绪与失败两条路都要收右栏");
  assert.ok((seg.match(/paintFixBar/g) || []).length >= 2, "修复条也要跟着收");
});

test("修复建议条只在真有缺失时出现，且跳的是「缺失资源」标签", () => {
  const seg = panels.slice(panels.indexOf("export function paintFixBar"));
  assert.match(seg, /if \(!gaps\) \{/);
  assert.match(seg, /showTabPane\("missing"\)/);
  // 条子挂在滚动容器外面，才能稳在详情栏底边而不是随内容浮动。
  assert.match(seg, /el\("fixBarHost"\)/);
  assert.match(html, /id="fixBarHost"/);
  assert.ok(!/host\.append\(bar\)/.test(seg), "别再往可滚的正文里塞条子");
});

test("关系网浮层：从顶栏与详情都能进，Esc 能退", () => {
  assert.match(relations, /el\("openRelations"\)\.addEventListener/);
  assert.match(relations, /el\("btnRel"\)\.addEventListener/);
  assert.match(relations, /el\("profRelOpen"\)\.addEventListener/);
  assert.match(html, /id="openRelations"/);
  assert.match(html, /id="relations"[^>]*hidden/);
});

test("关系网只画回包里真有的类别，缺的不省略（0 命中本身是结论）", () => {
  const seg = relations.slice(relations.indexOf("function buildGraph"), relations.indexOf("function nodeSvg"));
  assert.match(seg, /for \(const m of insp\.members \|\| \[\]\)/, "成员一律入图");
  assert.match(seg, /for \(const s of b\.textureSlots \|\| \[\]\)/, "材质槽一律入图");
  assert.ok(!/slice\(0, \d+\)/.test(seg), "不许悄悄截断：截了就等于把缺的藏起来");
});

test("关系网的边只在回包里有对应项时才画（命名相似不算引用）", () => {
  const seg = relations.slice(relations.indexOf("const edges = []"));
  assert.match(seg, /pos\.get\(n\.id\)/);
  assert.match(seg, /if \(!p\) continue;/);
});

// ---- 长名字的排版防呆 ----
//
// 曾经的症状：详情大标题「w1351_nan_s_shukuanganxiang_001」折成两截
// （「…shukuanganxiang_」+「001」），右栏「类型：界面资源」也被后面折行的
// 名字顶歪，看着像两行数据串了。数据没错，是排版。三处一起钉住。

test("详情大标题走 titleHtml（下划线后断行），不许退回裸 textContent", () => {
  assert.match(detail, /import \{[^}]*titleHtml[^}]*\} from "\.\/lib\/wording\.js"/s);
  assert.match(detail, /el\("dName"\)\.innerHTML = titleHtml\(/);
  assert.ok(!/el\("dName"\)\.textContent/.test(detail), "退回 textContent 就没有 <wbr> 断点了");
});

test("概况表的 dd 能收缩：min-width:0 与 flex 缺一不可", () => {
  const css = readFileSync(join(web, "style.css"), "utf8");
  const seg = css.slice(css.indexOf(".kv dd {"), css.indexOf(".kv dd.mono"));
  assert.ok(seg.length > 0, "找不到 .kv dd 规则");
  assert.match(seg, /min-width:\s*0/, "不给 min-width:0，长名字会把 dt 挤走");
  assert.match(seg, /flex:\s*1/, "dd 要能吃满剩余宽度");
  assert.match(seg, /overflow-wrap:\s*anywhere/, "长无空格串必须能折");
});

test("长标题不硬折：用 break-word 而不是 everywhere", () => {
  const css = readFileSync(join(web, "style.css"), "utf8");
  const seg = css.slice(css.indexOf(".d-head h2 {"), css.indexOf(".d-head h2 {") + 200);
  assert.ok(!/overflow-wrap:\s*anywhere/.test(seg), "anywhere 会在任意字符处硬折，读者看到半截名字");
  assert.match(seg, /overflow-wrap:\s*break-word/);
});

// ---- 「组成成员」不许再被叫成「引用关系」 ----
//
// 侧栏和标签页那两个数字数的是 members（这组登记的文件），
// 不是 refs（引用边，另一张表，且不在 asset_inspect 回包里）。
// 把成员数标成「引用关系」正是项目纪律里「命名推断 ≠ 引用」禁止的事。

test("详情里数成员的地方一律叫「组成成员」，不许写「引用关系」", () => {
  assert.match(html, /data-tab="relations"[^>]*>组成成员/, "标签名要跟它数的东西对上");
  assert.match(html, /组成成员 <em id="profRefCount"><\/em>/, "侧栏标题同理");
  assert.ok(!/>引用关系 <em id="tabRelCount"/.test(html), "标签不许再写「引用关系」");
  assert.ok(!/>引用关系 <em id="profRefCount"/.test(html), "侧栏不许再写「引用关系」");
});

test("统计函数叫 memberStats：名字本身说明它数的是什么", () => {
  assert.match(panels, /function memberStats\(insp\)/);
  assert.ok(!/function refStats\(/.test(panels), "refStats 这个名字在骗人，已经改名");
  assert.ok(!/refStats\(/.test(panels), "调用点也要一起改名");
  // 数据源必须是 members，不是 refs。
  const seg = panels.slice(panels.indexOf("function memberStats"), panels.indexOf("function paintSide"));
  assert.match(seg, /for \(const m of insp\.members \|\| \[\]\)/);
});
