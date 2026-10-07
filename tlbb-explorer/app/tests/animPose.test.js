// 动作页 3D 预览的纯逻辑闸门：在途闸门、注记去重、播放步进。
// DOM/WebGL 是薄壳（detail.js / mesh-viewer.js），这一层单独可测——
// 「迟到的回包」「连动的游标」「积压的排队」全是时序事故，钉在判断层最便宜。

import test from "node:test";
import assert from "node:assert/strict";
import { makePoseGate, poseNote, nextFrame, PLAY_STEP_MS, clampFrame } from "../web/lib/animPose.js";

test("在途闸门：第一个请求放行，在途期间只记最新帧", () => {
  const gate = makePoseGate();
  assert.equal(gate.request(3), 3, "第一个请求直接放行");
  assert.equal(gate.request(5), null, "在途时不放行");
  assert.equal(gate.request(7), null, "在途时不放行");
  assert.equal(gate.settled(), 7, "落地时给出的是攒下的**最新**帧，中间的丢掉");
  assert.equal(gate.settled(), null, "放完就没有了，不重复补发");
});

test("在途闸门：reset 把在途与攒帧一起作废（换资产/换动作/换网格时调用）", () => {
  const gate = makePoseGate();
  gate.request(1);
  gate.request(2);
  gate.reset();
  assert.equal(gate.settled(), null, "reset 后没有可补发的帧");
  assert.equal(gate.request(9), 9, "reset 后新请求直接放行，不被死请求卡住");
});

test("注记去重：取第一条可用的话，同一句不重写，没有可用的就不动屏幕", () => {
  const notes = ["锚定口径：…", "帧率未证：…"];
  assert.equal(poseNote(notes, ""), notes[0], "第一次取第一条");
  assert.equal(poseNote(notes, notes[0]), null, "同一句回 null——屏幕上的不用动");
  assert.equal(poseNote(notes, "别的话"), notes[0], "屏幕上是别的话就换成第一条");
  assert.equal(poseNote([], ""), null, "没有 notes 不擦已有的注记");
  assert.equal(poseNote(["", 42, notes[0]], ""), notes[0], "空串与非字符串跳过，不编一句空的");
  assert.equal(poseNote(null, ""), null, "回包没带 notes 也不抛");
});

test("播放步进：到尾回卷；帧数非法时原地不动", () => {
  assert.equal(nextFrame(0, 3), 1);
  assert.equal(nextFrame(2, 3), 0, "最后一帧的下一步回到 0");
  assert.equal(nextFrame(5, 3), 0, "越界的帧先夹回范围再步进");
  assert.equal(nextFrame(0, 0), 0, "零帧动作不许算出 NaN");
  assert.equal(nextFrame(0, -2), 0);
});

test("参考速度不是真帧率：它只是步进间隔，且有下限得像个人话常量", () => {
  // 25 步/秒的参考节奏。帧率刻度（.ani 的 tick）含义未证——这个常量
  // 存在的意义就是让文案永远不必把「25fps」写成真值。
  assert.equal(PLAY_STEP_MS, 40);
  assert.ok(PLAY_STEP_MS > 0 && PLAY_STEP_MS < 1000, "一秒内至少走一步");
});

test("帧夹取与动作页表格同一把尺子（animView.clampFrame）", () => {
  assert.equal(clampFrame(999, 3), 2);
  assert.equal(clampFrame("x", 3), 0);
  assert.equal(clampFrame(-1, 3), 0);
});
