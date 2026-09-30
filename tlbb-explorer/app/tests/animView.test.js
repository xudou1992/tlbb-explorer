import test from "node:test";
import assert from "node:assert/strict";
import { clampFrame, frameRows, changedRows, animSummary } from "../web/lib/animView.js";

const tracks = [
  {
    bone: "bip01",
    rotations: [
      [1, 0, 0, 0],
      [0.9, 0.1, 0, 0],
    ],
    positions: [
      [0, 0, 0],
      [0, 1, 0],
    ],
    scales: [1, 1],
  },
  {
    bone: "",
    rotations: [
      [1, 0, 0, 0],
      [1, 0, 0, 0],
    ],
    positions: [
      [0, 0, 0],
      [0, 0, 0],
    ],
    scales: [1, 1],
  },
];

test("游标越界退回安全值，表格不许出现空洞帧", () => {
  assert.equal(clampFrame(-5, 21), 0);
  assert.equal(clampFrame(999, 21), 20);
  assert.equal(clampFrame("abc", 21), 0);
  assert.equal(clampFrame(3.7, 21), 3, "小数取整而不是四舍五入到范围外");
  assert.equal(clampFrame(1, 0), 0, "零帧的动作不能给出越界帧");
});

test("帧表：客户端没给名字的骨写「未命名骨」，不编一个名字", () => {
  const rows = frameRows(tracks, 1);
  assert.equal(rows[0].bone, "bip01");
  assert.equal(rows[1].bone, "未命名骨", "空名必须标成未命名，而不是留空或造名");
  assert.deepEqual(rows[0].quat, [0.9, 0.1, 0, 0]);
  assert.deepEqual(rows[0].pos, [0, 1, 0]);
});

test("「只列变了的骨」：第 0 帧一条都不该列，第 1 帧只列真变的", () => {
  assert.deepEqual(changedRows(tracks, 0), [], "第 0 帧相对自己没变化");
  const c = changedRows(tracks, 1);
  assert.equal(c.length, 1, "只有 bip01 动了");
  assert.equal(c[0].bone, "bip01");
});

test("摘要带着帧率刻度原话，不换算成秒", () => {
  const rep = { file: "a_walk.ani", bones: 46, frames: 21, tick: 40, moving: 12, tracks };
  const s = animSummary(rep, 5);
  assert.ok(s.includes("第 6 / 21 帧"), `游标该从 1 开始数：${s}`);
  assert.ok(s.includes("40"), "刻度值要出现");
  assert.ok(s.includes("未证"), "含义没证就必须说明");
  assert.ok(!/秒/.test(s.replace(/含义未证[^·]*/g, "")) || s.includes("不换算成秒"), "不许换算成秒");
  assert.equal(animSummary({ tracks: [] }, 0), "这条动作没读到关键帧数据。");
});
