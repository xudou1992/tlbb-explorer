// 浏览右栏灰模盒子（browseMeshBox.js）的纯逻辑测试。跑法（在 app/ 下，
// 显式列文件名，node --test 吃目录会 MODULE_NOT_FOUND）：
//   node --test tests/browseMeshBox.test.js
//
// WebGL/DOM 在 node 里开不了，盒子本体（createBrowseMeshBox）测不了——
// 和 instanceMath.js 头上那条注释是同一个理由。这里钉住三件纯的事：
// 类型判断（isMeshEntry）、mesh_data 的取数键（meshDataRequestOf）、
// 技术栏的字段口径（meshTechRows）；再防一笔接线：browse.js 必须真的
// import 了盒子并做类型分支，分支被人顺手删掉时这里要红。

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { isMeshEntry, meshDataRequestOf, meshTechRows } from "../web/browseMeshBox.js";

const here = dirname(fileURLToPath(import.meta.url));
const web = join(here, "..", "web");

const entry = (over) => ({
  hash: "ab" + "0".repeat(14),
  path: null,
  kind: "",
  ext: "",
  size: 100,
  name: "ab" + "0".repeat(14),
  ...over,
});

test("有名字的网格：kind 是 mesh 就认", () => {
  assert.equal(
    isMeshEntry(entry({ path: "data/source/npc/c.mesh", kind: "mesh", ext: "mesh", name: "c.mesh" })),
    true,
  );
});

test("无名网格：kind 空着，靠 ext 或树行名的后缀认出来", () => {
  const h = "ab" + "0".repeat(14);
  // 树行名是 buildTree 按编号+扩展名拼的，两种证据各自都要能认
  assert.equal(isMeshEntry(entry({ ext: "mesh", name: h + ".mesh" })), true);
  assert.equal(isMeshEntry(entry({ ext: ".mesh" })), true); // 扩展名带点也认
  assert.equal(isMeshEntry(entry({ name: "FF" + "0".repeat(12) + ".MESH" })), true); // 大小写不敏感
});

test("不是网格的：贴图不认，.mdl 也不认（组装文件第一版不装会）", () => {
  assert.equal(isMeshEntry(entry({ path: "a/b.png", kind: "texture", ext: "tga", name: "b.png" })), false);
  assert.equal(isMeshEntry(entry({ path: "a/b.mdl", kind: "mdl", ext: "mdl", name: "b.mdl" })), false);
  assert.equal(isMeshEntry(entry({ name: "abc123" })), false); // 编号本身不带后缀
  assert.equal(isMeshEntry(null), false);
});

test("meshDataRequestOf：hash 是定位键，name 只是出错时的称呼", () => {
  const h = "ab" + "0".repeat(14);
  assert.deepEqual(meshDataRequestOf(entry({ path: "data/source/npc/c.mesh", name: "c.mesh" })), {
    name: "data/source/npc/c.mesh",
    hash: h,
  });
  // 无名文件没有路径，用树里那行名字当称呼
  assert.deepEqual(meshDataRequestOf(entry({ ext: "mesh", name: h + ".mesh" })), {
    name: h + ".mesh",
    hash: h,
  });
  // 两个都空时给空串：后端会管它叫「这个网格」，而不是把 undefined 拼进文案
  assert.deepEqual(meshDataRequestOf(entry({ name: "" })), { name: "", hash: h });
});

test("meshTechRows：口径与资产视图 mesh.js 一字不差，但不重复上面说过的行", () => {
  const rows = meshTechRows({
    hasNormals: false,
    hasUvs: true,
    submeshCount: 2,
    middleBytes: 12345,
    trailingBytes: 0,
  });
  assert.deepEqual(
    rows.map(([k]) => k),
    ["表面朝向", "贴图坐标", "材质槽数", "还没读懂的字节"],
  );
  const text = rows.map(([k, v]) => `${k}=${v}`).join(" | ");
  assert.ok(text.includes("文件里没读到，明暗按面自己算"), text);
  assert.ok(text.includes("贴图坐标=读到了"), text);
  assert.ok(text.includes("顶点之后 12,345"), text);
  // 客户端路径在 bfMeta 里说过、顶点数在 meta 行里说过——同一件事不说两遍
  assert.ok(!text.includes("客户端路径"), text);
  assert.ok(!text.includes("顶点 /"), text);
});

test("browse.js 确实接上了灰模盒子（接线防呆）", () => {
  const browse = readFileSync(join(web, "browse.js"), "utf8");
  assert.match(browse, /from "\.\/browseMeshBox\.js"/);
  assert.match(browse, /isMeshEntry\(/);
  assert.match(browse, /retireBrowseMesh\(\)/);
});

test("右栏每条换内容的路都要收灰模盒子（retire 停动画+摘节点）", () => {
  const browse = readFileSync(join(web, "browse.js"), "utf8");
  // 三条换内容的路：换包、点文件夹、点文件。少一处，旧画布就会在
  // 新内容底下空转（泄漏+空转的动画循环）。
  const sites = [
    ["async function openPak(name)", "换包"],
    ["function showDirDetail(node)", "点文件夹"],
    ["async function showFileDetail(entry)", "点文件"],
  ];
  for (const [start, what] of sites) {
    const i = browse.indexOf(start);
    assert.ok(i >= 0, `找不到 ${start}`);
    const seg = browse.slice(i, i + 2500);
    assert.match(seg, /retireBrowseMesh\(\)/, `${what}这条路必须 retire 灰模盒子`);
  }
});

test("灰模盒子的样式在 style.css 里（动态画布 id 与折叠态）", () => {
  const css = readFileSync(join(web, "style.css"), "utf8");
  assert.match(css, /#browseMeshCanvas/);
  assert.match(css, /\.mesh-stage\.bm-folded/);
});
