// 动作页 3D 预览的纯逻辑闸门：在途闸门、注记去重、播放步进。
// DOM/WebGL 是薄壳（detail.js / mesh-viewer.js），这一层单独可测——
// 「迟到的回包」「连动的游标」「积压的排队」全是时序事故，钉在判断层最便宜。

import test from "node:test";
import assert from "node:assert/strict";
import {
  makePoseGate,
  poseNote,
  poseNotesLine,
  nextFrame,
  PLAY_STEP_MS,
  clampFrame,
  meshTail,
  checkedPartList,
  partLoadSummary,
  matchPartPoses,
  sameNameList,
} from "../web/lib/animPose.js";

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

// ---------------------------------------------------------------------------
// 整组部件一起摆（多件套）：勾选 → 请求参数 → 回包对号 → 逐件降级。
// 容错口径与上面同一族：脏数据丢掉、不抛、不编。
// ---------------------------------------------------------------------------

test("尾名对号：完整路径与文件名都能切出同一名（与后端 mesh 匹配规则同一条）", () => {
  assert.equal(meshTail("a/b/c/yifu_001.mesh"), "yifu_001.mesh");
  assert.equal(meshTail("yifu_001.mesh"), "yifu_001.mesh");
  assert.equal(meshTail("no-slash/"), "", "以 / 结尾的脏输入回空串，不抛");
  assert.equal(meshTail(42), "", "非字符串不抛");
  assert.equal(meshTail(null), "");
});

test("勾选 → 请求参数：开着的按原顺序带走，关掉的不进名单", () => {
  const names = ["yifu_001.mesh", "shoutao_001.mesh", "huxiu_001.mesh"];
  const checks = { "yifu_001.mesh": true, "shoutao_001.mesh": false, "huxiu_001.mesh": true };
  const isEnabled = (n) => checks[n];
  assert.deepEqual(
    checkedPartList(names, isEnabled),
    ["yifu_001.mesh", "huxiu_001.mesh"],
    "关掉的那件不进请求名单，顺序保持清单原序",
  );
  assert.deepEqual(checkedPartList(names, () => true), names, "默认全开就是全名单");
  assert.deepEqual(checkedPartList(names, () => false), [], "一件没开就是空表：调用方据此清画布不发请求");
  assert.deepEqual(checkedPartList([null, "", "yifu_001.mesh"], () => true), ["yifu_001.mesh"], "空名/非字符串不进名单");
  assert.deepEqual(checkedPartList("不是数组", () => true), []);
});

test("逐件取几何聚合：成功的按序留下，失败的点名进一句人话", () => {
  const names = ["a.mesh", "b.mesh", "c.mesh"];
  const ok = (v) => ({ status: "fulfilled", value: v });
  const all = partLoadSummary(names, [ok("A"), ok("B"), ok("C")]);
  assert.deepEqual(all.ok.map((o) => o.name), names, "全成时按请求顺序");
  assert.deepEqual(all.ok.map((o) => o.data), ["A", "B", "C"]);
  assert.equal(all.failed.length, 0);
  assert.equal(all.message, null, "没有失败就不写失败行");

  const some = partLoadSummary(names, [ok("A"), { status: "rejected", reason: "x" }, { status: "fulfilled", value: null }]);
  assert.deepEqual(some.ok.map((o) => o.name), ["a.mesh"], "失败与空回包都不算取到");
  assert.deepEqual(some.failed, ["b.mesh", "c.mesh"], "点名哪件，不能只说「失败了」");
  assert.equal(some.message, "这几件没取到几何，先摆其余的：b.mesh、c.mesh");

  const none = partLoadSummary(names, []);
  assert.equal(none.ok.length, 0, "结果缺失按失败算（调用方据此整组回退）");
  assert.equal(none.failed.length, 3);
  assert.ok(none.message.includes("a.mesh、b.mesh、c.mesh"));
  assert.deepEqual(partLoadSummary(names, "脏输入").ok, [], "结果不是数组不抛");
  assert.deepEqual(partLoadSummary("脏输入", []).ok, []);
});

test("回包对号：按尾名对到画布上的件下标，不按位置硬配，对不上的丢掉", () => {
  const loaded = ["yifu_001.mesh", "shoutao_001.mesh"];
  const pose = (mesh) => ({ mesh, positions: [[0, 0, 0]] });
  const out = matchPartPoses([pose("group/yifu_001.mesh"), pose("group/shoutao_001.mesh")], loaded);
  assert.deepEqual(
    out.map((m) => m.index),
    [0, 1],
    "完整路径按尾名对到装载下标",
  );
  assert.deepEqual(out.map((m) => m.name), loaded);
  assert.deepEqual(
    matchPartPoses([pose("group/shoutao_001.mesh"), pose("group/yifu_001.mesh")], loaded).map((m) => m.index),
    [1, 0],
    "顺序变过也对得上号——对号靠名字不靠位置",
  );
  assert.deepEqual(
    matchPartPoses([pose("group/没勾的.mesh"), pose(null), { mesh: "group/yifu_001.mesh" }], loaded),
    [],
    "画布上没有的件、没有顶点的件、残缺的条目都丢掉，不硬画",
  );
  assert.deepEqual(matchPartPoses("脏输入", loaded), []);
  assert.deepEqual(matchPartPoses([], "脏输入"), []);
});

test("整组注记整段上屏：「这件不变形」的部件实况跟着固定三条一起到，不刷屏", () => {
  const notes = ["锚定口径：…", "帧率未证：…", "shoutao_001.mesh 没有影响顶点表（顶点全绑在根骨上），这件不变形"];
  assert.equal(poseNotesLine(notes, ""), notes.join("；"), "整段 join，不能只取第一条把部件实况丢掉");
  assert.equal(poseNotesLine(notes, notes.join("；")), null, "同一整段不重写");
  assert.equal(poseNotesLine([], ""), null, "没有 notes 不动屏幕");
  assert.equal(poseNotesLine([42, null, notes[0]], ""), notes[0], "非字符串条目跳过");
  assert.equal(poseNotesLine(null, ""), null);
});

test("fresh 守卫的名单比对：逐位相等才算新鲜，勾选刚变过就算旧", () => {
  assert.equal(sameNameList(["a.mesh", "b.mesh"], ["a.mesh", "b.mesh"]), true);
  assert.equal(sameNameList(["a.mesh", "b.mesh"], ["b.mesh", "a.mesh"]), false, "顺序变了就是换过缓冲");
  assert.equal(sameNameList(["a.mesh"], ["a.mesh", "b.mesh"]), false, "多一件少一件都算旧");
  assert.equal(sameNameList([], []), true);
  assert.equal(sameNameList(null, []), false, "非数组不抛、一律判旧");
  assert.equal(sameNameList(["a.mesh"], "脏输入"), false);
});
