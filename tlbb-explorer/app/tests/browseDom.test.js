// 浏览视图 DOM 接线的防呆测试：browse.js 里 el("xxx") 引用的每个 id，
// index.html 里都必须真的存在。跑法（在 app/ 下）：
//   node --test tests/browseDom.test.js

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "web");

const html = readFileSync(join(web, "index.html"), "utf8");
const browse = readFileSync(join(web, "browse.js"), "utf8");

test("browse.js 引用的每个元素 id 都在 index.html 里", () => {
  const used = [...browse.matchAll(/el\("([^"]+)"\)/g)].map((m) => m[1]);
  assert.ok(used.length > 10, `应能从 browse.js 提取到 id 引用，实际 ${used.length}`);
  const missing = [...new Set(used)].filter((id) => !html.includes(`id="${id}"`));
  assert.deepEqual(missing, [], `这些 id 在 index.html 里找不到：${missing.join(", ")}`);
});

test("顶栏两个主视图标签存在，浏览是默认视图", () => {
  for (const id of ["tabBrowse", "tabAssets", "browseView", "assetsView"]) {
    assert.ok(html.includes(`id="${id}"`), `缺 id=${id}`);
  }
  // 资产视图默认收起，浏览视图默认展开——软件第一屏是「打开 data」。
  assert.match(html, /id="browseView"[\s\S]{0,40}?>\s*<aside class="pane rail">/);
});

// ---- 接线防呆 ----
// 浏览视图的时序 bug（迟到的回包画错面板、导错对象）在 node 里开不了 DOM，
// 测不了运行时，只能钉住接线本身：关键的作废/守卫语句被人顺手删掉时这里要红。

/// 从 start 标记切到 end 标记之间的源码（两个都是顶层函数，边界稳定）。
function between(src, start, end) {
  const i = src.indexOf(start);
  const j = src.indexOf(end, i + start.length);
  assert.ok(i >= 0, `找不到 ${start}`);
  assert.ok(j > i, `找不到 ${end}`);
  return src.slice(i, j);
}

test("点文件夹行必须改 selectedDir：右栏摆的是它，导出的也得是它", () => {
  const seg = between(browse, "function dirRow(node)", "function fileRow(entry)");
  assert.match(seg, /selectedDir = node;/);
});

test("按钮文案与导出动作吃同一份裁决（exportTargetOf）", () => {
  assert.match(browse, /from "\.\/lib\/browseState\.js"/);
  assert.match(browse, /exportTargetOf/);
  assert.match(
    between(browse, "function updateExportButton()", "async function doExport()"),
    /exportTargetOf\(/,
    "按钮要按同一把尺子说话",
  );
  assert.match(
    between(browse, "async function doExport()", "// ---- 小工具 ----"),
    /exportTargetOf\(/,
    "真导出的 hash 表也要来自同一把尺子",
  );
});

test("导出进行中不许重入，收尾按现状重算按钮", () => {
  const seg = between(browse, "async function doExport()", "// ---- 小工具 ----");
  assert.match(seg, /if \(!t \|\| exporting\) return;/, "连点/回车要拦住");
  assert.match(seg, /exporting = false;[\s\S]*?updateExportButton\(\);/, "收尾别直接亮按钮");
  const upd = between(browse, "function updateExportButton()", "async function doExport()");
  assert.match(upd, /if \(exporting\) return;/, "导出中行点击不能把按钮重新点亮");
});

test("showFileDetail 领号在所有分支之前：文件夹/非图/灰模也要作废在途的贴图回包", () => {
  const iSeq = browse.indexOf("const seq = ++previewSeq");
  const iMesh = browse.indexOf("if (isMeshEntry(entry))");
  const iKind = browse.indexOf("!IMAGE_KINDS.has(entry.kind)");
  assert.ok(iSeq >= 0, "showFileDetail 里要先领号");
  assert.ok(iMesh >= 0 && iKind >= 0, "类型分支还在");
  assert.ok(iSeq < iMesh && iSeq < iKind, "领号必须在灰模/非图分支之前，不然在途的贴图回包会盖掉它们");
  // 只许领一次号：分支里再各领各的就会漏
  assert.equal((browse.match(/const seq = \+\+previewSeq/g) || []).length, 1);
});

test("文件夹详情也要作废在途的贴图回包", () => {
  const seg = between(browse, "function showDirDetail(node)", "async function showFileDetail(entry)");
  assert.match(seg, /previewSeq\+\+/);
});

test("openPak：迟到回包要过闸，失败要说话，旧包预览要作废", () => {
  const seg = between(browse, "async function openPak(name)", "/// 切换到某个目录");
  assert.match(seg, /const my = \+\+pakSeq;/);
  assert.ok((seg.match(/my !== pakSeq/g) || []).length >= 2, "成功与失败两条出路都要过闸");
  assert.match(seg, /previewSeq\+\+/, "旧包在途的预览回包不能画进新包面板");
  assert.match(seg, /pickedRow = null;/, "旧树的高亮行引用一并作废");
  assert.match(seg, /打开失败/, "标题不能永远停在「正在打开」");
  assert.match(seg, /retireBrowseMesh\(\)/, "换包要收灰模盒子");
});

test("清空搜索回到整棵树：回子目录会把人困在里面（树没有面包屑）", () => {
  const seg = between(
    browse,
    'el("treeFilter").addEventListener',
    'el("exportGo").addEventListener',
  );
  assert.match(seg, /showDir\(tree\);/);
  assert.ok(!/showDir\(selectedDir/.test(seg), "不能回子目录");
});

test("initBrowse 只接一遍事件", () => {
  const seg = browse.slice(browse.indexOf("export function initBrowse"));
  assert.match(seg, /if \(wired\) return;/);
  assert.match(seg, /wired = true;/);
});

test("空层要有一句话，不能一片空白", () => {
  const seg = between(browse, "function renderDirInto(node, host)", "function dirRow(node)");
  assert.match(seg, /!rows\.length/);
  assert.match(seg, /appendMsg\(host,/);
});

test("metaRows 的键要过 esc：拼接点不许留裸值", () => {
  const seg = between(browse, "function metaRows(pairs)", "function appendMsg(host, text)");
  assert.match(seg, /\$\{esc\(k\)\}/);
  assert.ok(!/\$\{k\}/.test(seg), "键不许直接进模板串");
});
