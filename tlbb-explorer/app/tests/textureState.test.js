// textureState 的口径测试：候选必须标「未确认」，覆盖表确认才给 🟢；
// 没跑过试贴时槽位只能是 ⬜ 名字清单——🟡 是候选专用，名字清单不许冒用。
import { test } from "node:test";
import assert from "node:assert/strict";
import { texBlock, texSlotsHtml, texCandidatesHtml } from "../web/lib/textureState.js";

const SLOT_A = { name: "a_yifu_001.tga", cfgPath: "data/source/npc/x/texture/a_yifu_001.tga", overrideHash: null };
const SLOT_B = { name: "a_shoutao_001.tga", cfgPath: "data/source/npc/x/texture/a_shoutao_001.tga", overrideHash: null };
const CAND = (i) => ({ hash: `hash${i}aaaaaaaaaaaa`, w: 512, h: 512, codec: "BC3", mips: 10, score: 4.2, png: "data:image/png;base64,AAA" });
const GROUP = { mesh: "a_yifu_001.mesh", pool: 1646, state: "candidates", candidates: [CAND(1), CAND(2)] };

test("没有候选也没有槽位：区块整个不出现，不编造", () => {
  assert.equal(texBlock({}), null);
  assert.equal(texBlock({ texSlots: [], textureCandidates: [] }), null);
});

test("有候选缓存：出卡、两颗按钮齐全，分数必须带「未确认」", () => {
  const b = texBlock({ texSlots: [SLOT_A, SLOT_B], textureCandidates: [GROUP] });
  assert.ok(b);
  assert.ok(b.candHtml.includes("套上看看"));
  assert.ok(b.candHtml.includes("确认这张"));
  assert.ok(b.candHtml.includes("未确认"));
  assert.ok(b.note.includes("1646"));
  assert.equal((b.candHtml.match(/<figure/g) || []).length, 2);
});

test("确认过的槽位标 🟢 并给撤销按钮；跑过试贴的未确认槽位是 🟡", () => {
  const html = texSlotsHtml([{ ...SLOT_A, overrideHash: "abcd1234ef567890" }, SLOT_B], true);
  assert.ok(html.includes("已人工确认"));
  assert.ok(html.includes("撤销"));
  assert.ok(html.includes("🟢"));
  assert.ok(html.includes("🟡"));
});

test("没跑过试贴的槽位不是候选：标 ⬜ 并说清是名字清单，不许冒用 🟡", () => {
  const html = texSlotsHtml([SLOT_A], false);
  assert.ok(!html.includes("🟡"));
  assert.ok(html.includes("⬜"));
  assert.ok(html.includes("引用未确认"));
  assert.ok(html.includes("离线试贴还没跑"));
  assert.ok(html.includes(SLOT_A.cfgPath));
});

test("确认下拉只列未确认的槽位；全确认了就提示可撤销重选", () => {
  const open = texCandidatesHtml(GROUP, [SLOT_A, SLOT_B]);
  assert.ok(open.includes('id="texSlotPick"'));
  assert.equal((open.match(/<option/g) || []).length, 2);
  const all = texCandidatesHtml(GROUP, [{ ...SLOT_A, overrideHash: "h1" }, { ...SLOT_B, overrideHash: "h2" }]);
  assert.ok(all.includes("撤销后可重选"));
  assert.ok(!all.includes('id="texSlotPick"'));
});

test("候选区转义：名字里的尖括号不能变成标签", () => {
  const html = texSlotsHtml([{ name: '<script>alert(1)</script>.tga', cfgPath: null, overrideHash: null }]);
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
});
