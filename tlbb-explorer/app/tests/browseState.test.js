// 浏览视图树逻辑的测试。跑法（在 app/ 下，显式列文件名，Node 25 的 node --test
// 吃目录会 MODULE_NOT_FOUND）：
//   node --test tests/browseState.test.js

import test from "node:test";
import assert from "node:assert/strict";

import {
  buildTree,
  childrenOf,
  searchTree,
  collectHashes,
  countTree,
  exportTargetOf,
  fileNameOf,
  fmtSize,
  namelessLabel,
  kindZh,
} from "../web/lib/browseState.js";

const entry = (over) => ({
  hash: "ab" + "0".repeat(14),
  path: null,
  kind: "",
  ext: "",
  size: 100,
  ...over,
});

test("有名条目按路径建成嵌套目录，文件名取最后一段", () => {
  const tree = buildTree([
    entry({ path: "data/source/ui/icon/a.tga", kind: "texture", ext: "tga" }),
    entry({ path: "data/source/ui/icon/b.tga", kind: "texture", ext: "tga" }),
    entry({ path: "data/source/npc/c.mesh", kind: "mesh", ext: "mesh" }),
  ]);
  const data = tree.dirs.get("data");
  const source = data.dirs.get("source");
  assert.equal(source.dirs.get("ui").dirs.get("icon").files.length, 2);
  assert.equal(source.dirs.get("npc").files[0].name, "c.mesh");
});

test("无名条目进「(未命名) · 类型」桶，文件名是编号+已知扩展名", () => {
  const tree = buildTree([
    entry({ hash: "ab" + "0".repeat(14), kind: "texture" }),
    entry({ hash: "cd" + "1".repeat(14), ext: "tga" }),
  ]);
  // 类型是内容分类器判定的事实，分桶展示；文件名仍是编号，不编名字。
  const texBucket = tree.dirs.get("(未命名) · 贴图");
  const otherBucket = tree.dirs.get("(未命名) · 其他");
  assert.ok(texBucket, "判定过类型的无名条目要进对应类型桶");
  assert.ok(otherBucket, "没有类型判定的进「其他」桶");
  assert.deepEqual(texBucket.files.map((f) => f.name), ["ab" + "0".repeat(14)]);
  assert.deepEqual(otherBucket.files.map((f) => f.name), [
    "cd" + "1".repeat(14) + ".tga",
  ]);
});

test("kindZh：已知类型给中文词，未知给杂项，空给其他", () => {
  assert.equal(kindZh("texture"), "贴图");
  assert.equal(kindZh("geom"), "未知数据块");
  assert.equal(kindZh("GEOM"), "未知数据块");
  assert.equal(kindZh("什么新类型"), "杂项");
  assert.equal(kindZh(""), "其他");
});

test("fileNameOf：有名取 basename；无名补扩展名时不重复点号", () => {
  assert.equal(fileNameOf(entry({ path: "a/b/c.png" })), "c.png");
  assert.equal(fileNameOf(entry({ hash: "ff" + "2".repeat(14), ext: ".tga" })), "ff" + "2".repeat(14) + ".tga");
  assert.equal(fileNameOf(entry({ hash: "ff" + "2".repeat(14) })), "ff" + "2".repeat(14));
});

test("childrenOf：目录在前文件在后，按本地化排序；超量截断要报数", () => {
  const tree = buildTree([
    entry({ path: "z/last.png" }),
    entry({ path: "a/first.png" }),
    entry({ path: "m/mid.png" }),
  ]);
  const source = tree.dirs.get("data") ?? tree; // 直接用根也行
  const { rows, hidden } = childrenOf(source, 2);
  assert.equal(hidden, 1);
  assert.equal(rows[0].type, "dir");
});

test("searchTree：命中路径片段；无名命中编号；空关键字表示不在搜索态", () => {
  const tree = buildTree([
    entry({ path: "data/source/ui/icon/x.tga" }),
    entry({ hash: "ef" + "3".repeat(14) }),
  ]);
  assert.equal(searchTree(tree, ""), null);
  const byPath = searchTree(tree, "icon");
  assert.equal(byPath.length, 1);
  const byHash = searchTree(tree, "ef" + "3");
  assert.equal(byHash.length, 1);
  assert.equal(searchTree(tree, "不存在的词").length, 0);
});

test("searchTree 有上限，不把 10 万条全倒出来", () => {
  const many = Array.from({ length: 500 }, (_, i) =>
    entry({ path: `data/f${i}.png`, hash: String(i).padStart(16, "0") }),
  );
  const tree = buildTree(many);
  assert.equal(searchTree(tree, "data", 50).length, 50);
});

test("collectHashes 收齐子树；countTree 报全量", () => {
  const tree = buildTree([
    entry({ path: "a/x.png", hash: "11" + "0".repeat(14) }),
    entry({ path: "a/b/y.png", hash: "22" + "0".repeat(14) }),
    entry({ path: "c/z.png", hash: "33" + "0".repeat(14) }),
  ]);
  const a = tree.dirs.get("a");
  assert.deepEqual(collectHashes(a), ["11" + "0".repeat(14), "22" + "0".repeat(14)]);
  const c = countTree(tree);
  assert.equal(c.files, 3);
  assert.equal(c.dirs, 3); // a、a/b、c——没有无名条目就没有未命名桶
});

test("countTree 对没有无名条目的树不算未命名桶", () => {
  const tree = buildTree([entry({ path: "a/x.png" })]);
  assert.deepEqual(countTree(tree), { files: 1, dirs: 1 });
});

test("fmtSize 人话档位", () => {
  assert.equal(fmtSize(512), "512 B");
  assert.equal(fmtSize(2048), "2.0 KB");
  assert.equal(fmtSize(5 * 1024 * 1024), "5.0 MB");
});

// ---- exportTargetOf：导出目标的三态裁决 ----
// 按钮文案和 doExport 必须吃同一份结论，这里钉死每种选中态导的是什么。

test("exportTargetOf：树还没打开就是没有目标", () => {
  assert.equal(exportTargetOf(null, null, null), null);
});

test("exportTargetOf：选中文件=只导这一个", () => {
  const tree = buildTree([entry({ path: "a/x.png", hash: "11" + "0".repeat(14) })]);
  const f = tree.dirs.get("a").files[0];
  assert.deepEqual(exportTargetOf(f, tree, tree), {
    kind: "file",
    hashes: ["11" + "0".repeat(14)],
    files: 1,
  });
});

test("exportTargetOf：选中文件夹=整个子树（含嵌套与未命名桶）", () => {
  const tree = buildTree([
    entry({ path: "a/x.png", hash: "11" + "0".repeat(14) }),
    entry({ path: "a/b/y.png", hash: "22" + "0".repeat(14) }),
    entry({ path: "c/z.png", hash: "33" + "0".repeat(14) }),
    entry({ hash: "44" + "0".repeat(14), kind: "texture" }),
  ]);
  const a = tree.dirs.get("a");
  const t = exportTargetOf(null, a, tree);
  assert.equal(t.kind, "dir");
  assert.deepEqual(t.hashes, ["11" + "0".repeat(14), "22" + "0".repeat(14)]);
  assert.equal(t.files, 2);
  // 未命名桶也是目录：点它导的是桶里全部文件
  const bucket = tree.dirs.get("(未命名) · 贴图");
  const tb = exportTargetOf(null, bucket, tree);
  assert.equal(tb.kind, "dir");
  assert.deepEqual(tb.hashes, ["44" + "0".repeat(14)]);
});

test("exportTargetOf：根节点本身不算「文件夹」，算整包（空 hash 表交给后端）", () => {
  const tree = buildTree([
    entry({ path: "a/x.png", hash: "11" + "0".repeat(14) }),
    entry({ path: "a/b/y.png", hash: "22" + "0".repeat(14) }),
  ]);
  const t = exportTargetOf(null, tree, tree);
  assert.deepEqual(t, { kind: "pak", hashes: [], files: 2 });
  // 什么都没点（初始态）也是整包
  assert.deepEqual(exportTargetOf(null, null, tree), t);
});

test("exportTargetOf：文件夹优先级低于文件——两个都挂着时导文件", () => {
  const tree = buildTree([entry({ path: "a/x.png", hash: "11" + "0".repeat(14) })]);
  const a = tree.dirs.get("a");
  const t = exportTargetOf(a.files[0], a, tree);
  assert.equal(t.kind, "file");
});

// ---- 极端数据 ----

test("路径带空格/中文/引号照原样摆，不被加工也不出错", () => {
  const tree = buildTree([
    entry({ path: 'data/我的 模型/"怪"名<1>.mesh', kind: "mesh", ext: "mesh" }),
  ]);
  const dir = tree.dirs.get("data").dirs.get("我的 模型");
  assert.equal(dir.files[0].name, '"怪"名<1>.mesh');
  assert.equal(dir.path, "data/我的 模型");
  // 搜索也按原文匹配
  assert.equal(searchTree(tree, '"怪"名').length, 1);
});

test("一个目录四万个文件：childrenOf 截到默认 400，余数报对", () => {
  const many = Array.from({ length: 40000 }, (_, i) =>
    entry({ path: `big/f${i}.png`, hash: String(i).padStart(16, "0") }),
  );
  const tree = buildTree(many);
  const big = tree.dirs.get("big");
  const { rows, hidden } = childrenOf(big);
  assert.equal(rows.length, 400);
  assert.equal(hidden, 39600);
});
