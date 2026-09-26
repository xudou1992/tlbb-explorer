// 数字口径的措辞测试。跑法：在 app/ 下 `node --test tests/`。
//
// 规矩：任何出现在屏幕上的比值，标签里必须带着它的分母是什么。
// 这个项目被"同一句话两个口径"坑过：卡片的 0/2 只数贴图引用，
// 库状态的 62% 数的是全部引用，摆在一起用户就谁也不信了。

import test from "node:test";
import assert from "node:assert/strict";
import { pctText, texPair, listCount, railStats, citedVerdict, rowMissChip, mapNoObjects } from "../web/lib/wording.js";

test("25/30,585 显示成「不足 1%」而不是 0%", () => {
  assert.equal(pctText(0, 25), "不足 1%");
  assert.equal(pctText(0, 0), "0%"); // 真的一条都没有，就照说 0%
  assert.equal(pctText(62, 61408), "62%");
});

test("贴图引用必须带着「贴图」两个字出现", () => {
  assert.equal(texPair(0, 2), "贴图名对上 0/2");
  assert.match(texPair(25, 22630), /^贴图名对上/);
});

test("左栏每一行的标签都写清分母", () => {
  const rows = railStats({
    totalGroups: 13080, decoded: 13080, imageCandidates: 25, locatedRefs: 25, totalRefs: 22630,
  });
  const text = rows.map(([k, v]) => `${k}=${v}`).join(" | ");
  assert.equal(rows.length, 3);
  assert.ok(text.includes("贴图名能对上文件的组=25"), text);
  assert.ok(text.includes("贴图引用对上=25 / 22,630"), text);
  // 「主体能打开的 13,080」恒等于顶栏的「已读完 13,080 组」，同一件事不说两遍
  assert.ok(!text.includes("主体能打开"), text);
});

test("没读完时条数要标注是中途值", () => {
  assert.equal(listCount(12159, 300, true), "12,159 条（先列 300 条）");
  assert.equal(listCount(9000, 300, false), "9,000 条（先列 300 条） · 还在读取");
  assert.equal(listCount(3, 3, true), "3 条");
});

test("反查说的是「文件提到了它」，不是「共享」", () => {
  assert.equal(citedVerdict(60), "60 个文件提到了它");
  assert.equal(citedVerdict(0), "没有文件提到它");
  assert.ok(!citedVerdict(3).includes("共享"));
});

test("列表行里的缺项计数保持中性（红色只留给详情页）", () => {
  assert.equal(rowMissChip(0), "");
  assert.equal(rowMissChip(2), "贴图缺 2");
  assert.ok(!rowMissChip(5).includes("class"));
});

// 下面这几组数字全部来自 `tlbb-shell --maps` 落盘的真回包，不是编的样本。
test("格子真的空着才说「一个都没摆东西」", () => {
  const s = { grids: 28, records: 0, emptyGrids: 28, unreadableGrids: 0 };
  assert.equal(
    mapNoObjects(s),
    "读到了，这张图 28 个格子一个都没摆东西。能转、能缩放，就是看不到物件。",
  );
});

test("格子文件不是物件清单时，不许说成「没摆东西」", () => {
  // w1351_fb_jiebai_001：唯一一个 .scene 是版权头容器，根本没交出记录
  const s = { grids: 1, records: 0, emptyGrids: 0, unreadableGrids: 1 };
  const t = mapNoObjects(s);
  assert.ok(t.includes("1 个不是物件清单那类东西"), t);
  assert.ok(t.includes("一条摆位记录都没交出来"), t);
  assert.ok(!t.includes("一个都没摆东西"), "没摆东西＝这格本来空，跟读不通是两件事");
});

test("读不通与空格子并存时两个数都要出现", () => {
  const t = mapNoObjects({ grids: 10, records: 0, emptyGrids: 7, unreadableGrids: 3 });
  assert.ok(t.includes("3 个不是物件清单") && t.includes("7 个本来就是空格子"), t);
});

test("记录摆的不是网格时不能说成「没对上模型文件」", () => {
  // mqts_empty_001：2 条记录都是 .pu 特效，文件在客户端里真实存在
  const s = {
    grids: 2, records: 2, missingMeshes: 0, unreadableMeshes: 0,
    notMesh: 2, oddNames: 0, emptyNamed: 0, otherExt: [{ ext: "pu", records: 2 }],
  };
  const t = mapNoObjects(s);
  assert.ok(t.includes("2 条摆的本来就不是网格（.pu 2 条，文件是存在的）"), t);
  assert.ok(!t.includes("没对上"), t);
  assert.ok(!t.includes("缺"), "这类不是缺，这一版只是不画");
});

test("真缺、非网格、认不出的名字分开各说各的", () => {
  // w1351_fb_sixiangxiuxishi_001 的形态（这里把 resolved 压成 0 来验文案分支）
  const s = {
    grids: 2, records: 124, missingMeshes: 24, unreadableMeshes: 0,
    notMesh: 1, oddNames: 1, emptyNamed: 0, otherExt: [{ ext: "pu", records: 1 }],
  };
  const t = mapNoObjects(s);
  assert.ok(t.includes("24 条记的是网格，可客户端里取不出这个文件"), t);
  assert.ok(t.includes("1 条摆的本来就不是网格"), t);
  assert.ok(t.includes("1 条名字既不像文件名也不像路径"), t);
  assert.ok(t.includes("读到了 124 条记录"), t);
});
