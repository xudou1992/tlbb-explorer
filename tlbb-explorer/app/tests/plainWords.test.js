// 人话导语的措辞闸门：导语里出现术语就算失败。
//
// 用户 2026-10-05:「描述的东西密密麻麻的 我又看不懂」——从那以后每个详情
// 标签的第一句话必须是人话：有数字、有主语、说清「能干什么/还差什么」，
// 绑定位移/影响顶点表/驻留字符串/参数块这类词只能住在折叠区里。
// 跑法（在 app/ 下）：node --test tests/plainWords.test.js

import test from "node:test";
import assert from "node:assert/strict";
import { skeletonLead, animationLead, effectLead, materialLead } from "../web/lib/plain.js";

const 黑话 = ["绑定位移", "影响顶点表", "驻留字符串", "参数块", "关键帧轨道", "JBCF"];

test("骨架导语：数字齐全、说清还差什么，术语不许出现", () => {
  const s = skeletonLead({
    declared: 46,
    nodes: [
      { name: "origin", pos: [0, 0, 0], scale: 1 },
      { name: "bip01_pelvis", pos: [0.05, 0, -1.09], scale: 1 },
      { name: "bip01", pos: null, scale: null },
    ],
    skin_bones: 26,
    skin_pairs: 1163,
    animations: [{ file: "a_walk.ani" }],
  });
  assert.ok(s.includes("46 根骨头"), s);
  assert.ok(s.includes("2 根的位置已经读出来"), s);
  assert.ok(s.includes("44 根只登记了名字"), s);
  assert.ok(s.includes("26 根"), s);
  assert.ok(s.includes("1 条动作"), s);
  for (const w of 黑话) assert.ok(!s.includes(w), `导语里不许出现「${w}」：${s}`);
});

test("骨架导语：挂接读出来了才补一句，没有这个字段时一字不多", () => {
  const base = {
    declared: 2,
    nodes: [
      { name: "a", pos: [0, 0, 0] },
      { name: "b", pos: [1, 0, 0] },
    ],
  };
  const 无 = skeletonLead(base);
  assert.ok(!无.includes("谁挨着谁"), 无);
  const 有 = skeletonLead({ ...base, chain: true });
  assert.ok(有.startsWith(无), "没挂接时的句子必须原样留着");
  assert.ok(有.includes("骨头谁挨着谁也读出来了。"), 有);
  for (const w of 黑话) assert.ok(!有.includes(w), `导语里不许出现「${w}」：${有}`);
});

test("骨架导语：位置全读出来时不写差额，没读出来时直说", () => {
  const 全 = skeletonLead({
    declared: 12,
    nodes: Array.from({ length: 12 }, (_, i) => ({ name: `b${i}`, pos: [i, 0, 0], scale: 1 })),
  });
  assert.ok(全.includes("每根骨头的位置都读出来了"), 全);
  assert.ok(!全.includes("只登记了名字"), 全);

  const 无 = skeletonLead({ declared: 3, nodes: [{ name: "b", pos: null }] });
  assert.ok(无.includes("还没读出来"), 无);
});

test("动作导语：帧数、骨数、画布摆的是哪路顶点都要在", () => {
  const s = animationLead({
    file: "a_walk.ani",
    bones: 2,
    frames: 21,
    tick: 40,
    tracks: [{ bone: "bip01" }, { bone: "still" }],
  });
  assert.ok(s.includes("21 帧"), s);
  assert.ok(s.includes("2 根骨头"), s);
  assert.ok(s.includes("画布把顶点按这条动作摆出来"), s);
  assert.ok(s.includes("静止形状仍是网格的绑定姿态"), s);
  // 画布摆的是真算的顶点，但「和游戏画面一致」这种话不许写——口径没证。
  assert.ok(!s.includes("和游戏画面一致") && !s.includes("与游戏画面一致"), s);
  for (const w of 黑话) assert.ok(!s.includes(w), `导语里不许出现「${w}」：${s}`);
  assert.equal(animationLead({ tracks: [] }), "这条动作没读到关键帧数据。");
});

test("特效导语：说清是什么、参数没破译完，驻留字符串/参数块这类词不许出现", () => {
  const s = effectLead({ name: "a", group: "skill", string_total: 59, param_bytes: 6739 });
  assert.ok(s.includes("「a」"), s);
  assert.ok(s.includes("还没破译完"), s);
  for (const w of 黑话) assert.ok(!s.includes(w), `导语里不许出现「${w}」：${s}`);
  assert.ok(!effectLead({ name: "x" }).includes("「x」没有") , "没名字时别编句子");
});

test("材质导语：.mtl 报对上/没带，.mdl 说清是说明书", () => {
  const mtl = materialLead({ file: "grp.mtl", slots: [{}, {}, {}], unresolved: 1 });
  assert.ok(mtl.includes("一共 3 条"), mtl);
  assert.ok(mtl.includes("2 条对上了实际文件"), mtl);
  assert.ok(mtl.includes("1 条是客户端本来就没带的"), mtl);
  for (const w of 黑话) assert.ok(!mtl.includes(w), `导语里不许出现「${w}」：${mtl}`);

  const 全对上 = materialLead({ file: "g.mtl", slots: [{}, {}], unresolved: 0 });
  assert.ok(全对上.includes("2 条对上了实际文件。"), 全对上);
  assert.ok(!全对上.includes("没带"), 全对上);

  const mdl = materialLead({
    kind: "模型定义",
    skeletons: [{}],
    bodies: [{}, {}],
  });
  assert.ok(mdl.includes("说明书"), mdl);
  assert.ok(mdl.includes("一共 3 条"), mdl);
});
