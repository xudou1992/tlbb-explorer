// 骨头连线纯函数。跑法：在 app/ 下 `node --test tests/boneLines.test.js`。
// 树不在这里算。这里只保证喂给查看器的是成对、有限的顶点。

import test from "node:test";
import assert from "node:assert/strict";
import { boneLineVertices } from "../web/lib/boneLines.js";

const seg = (ax, ay, az, bx, by, bz) => [
  [ax, ay, az],
  [bx, by, bz],
];

test("空输入得到空顶点对", () => {
  assert.deepEqual(boneLineVertices(null), []);
  assert.deepEqual(boneLineVertices(undefined), []);
  assert.deepEqual(boneLineVertices([]), []);
  assert.deepEqual(boneLineVertices({}), []);
  assert.deepEqual(boneLineVertices({ lines: null }), []);
  assert.deepEqual(boneLineVertices({ lines: [] }), []);
  assert.deepEqual(boneLineVertices({ names: [["a", "b"]] }), []);
  assert.deepEqual(boneLineVertices("nope"), []);
  assert.deepEqual(boneLineVertices(0), []);
});

test("回包的线段原样留下，names 不参与顶点", () => {
  const lines = [seg(0, 1, 2, 3, 4, 5), seg(-1, 0, 0, 0, -2, 0)];
  assert.deepEqual(boneLineVertices({ lines, names: [["hip", "knee"], ["knee", "ankle"]] }), lines);
  assert.deepEqual(boneLineVertices(lines), lines);
});

test("非有限坐标整段丢掉，旁边的好段留下", () => {
  const good = seg(0, 0, 0, 1, 0, 0);
  const later = seg(0, 1, 0, 0, 2, 0);
  assert.deepEqual(
    boneLineVertices([good, seg(0, 0, NaN, 1, 1, 1), later]),
    [good, later],
  );
  assert.deepEqual(boneLineVertices([seg(0, Infinity, 0, 1, 0, 0)]), []);
  assert.deepEqual(boneLineVertices([seg(0, 0, 0, 1, -Infinity, 0)]), []);
  assert.deepEqual(boneLineVertices([seg(0, 0, 0, 1, "2", 0)]), []);
});

test("点列长度为奇数时丢掉落单的最后一个点", () => {
  assert.deepEqual(
    boneLineVertices([
      [0, 0, 0],
      [1, 0, 0],
      [2, 0, 0],
    ]),
    [seg(0, 0, 0, 1, 0, 0)],
  );
  assert.deepEqual(boneLineVertices([[9, 9, 9]]), []);
  assert.deepEqual(
    boneLineVertices([
      [0, 0, 0],
      [1, 0, 0],
      [2, 0, 0],
      [3, 0, 0],
      [4, 0, 0],
    ]),
    [seg(0, 0, 0, 1, 0, 0), seg(2, 0, 0, 3, 0, 0)],
  );
});

test("一段的端点数是奇数时整段丢掉", () => {
  const good = seg(0, 1, 2, 3, 4, 5);
  assert.deepEqual(
    boneLineVertices([[[1, 2, 3]], good, [[1, 2, 3], [4, 5, 6], [7, 8, 9]]]),
    [good],
  );
  assert.deepEqual(boneLineVertices([[[0, 0, 0]]]), []);
  assert.deepEqual(boneLineVertices([[[0, 0, 0], [1, 0, 0], [2, 0, 0]]]), []);
});

test("点的分量个数是奇数时这段不成立", () => {
  const good = seg(0, 0, 0, 1, 1, 1);
  assert.deepEqual(
    boneLineVertices([
      [[1], [0, 0, 0]],
      good,
      [[1, 2, 3, 4, 5], [0, 0, 0]],
      [[0, 1], [2, 3, 4]],
    ]),
    [good],
  );
  assert.deepEqual(boneLineVertices([[[1, 2, 3, 4, 5], [0, 0, 1]]]), []);
  assert.deepEqual(boneLineVertices([[[7], [8, 9, 0]]]), []);
});

test("扁平数字长度不是 6 的倍数时丢掉尾部", () => {
  assert.deepEqual(boneLineVertices([0, 0, 0, 1, 0, 0, 7]), [seg(0, 0, 0, 1, 0, 0)]);
  assert.deepEqual(boneLineVertices([1, 2, 3]), []);
  assert.deepEqual(boneLineVertices([0, 0, 0, 1, 0, 0, 9, 9, 9]), [seg(0, 0, 0, 1, 0, 0)]);
  assert.deepEqual(boneLineVertices([0, 0, 0, 1, 2, NaN, 0, 1, 0, 0, 2, 0]), [seg(0, 1, 0, 0, 2, 0)]);
});
