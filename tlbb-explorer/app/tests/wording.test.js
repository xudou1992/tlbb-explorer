// 数字口径的措辞测试。跑法：在 app/ 下 `node --test tests/`。
//
// 规矩：任何出现在屏幕上的比值，标签里必须带着它的分母是什么。
// 这个项目被"同一句话两个口径"坑过：卡片的 0/2 只数贴图引用，
// 库状态的 62% 数的是全部引用，摆在一起用户就谁也不信了。

import test from "node:test";
import assert from "node:assert/strict";
import { pctText, texPair, listCount, railStats, citedVerdict, rowMissChip } from "../web/lib/wording.js";

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
