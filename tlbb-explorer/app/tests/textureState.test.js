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

// ---- v0.4.2：因子证据行 + 按编号取图 ----
const F = { uvFit: 0.12, alphaFit: 1, sizeFit: 0.8, blackBias: true, whiteBias: false, meanColor: [48, 34, 19] };
const CAND_V2 = (i, adjusted, factors) => ({
  hash: `ee0000000000000${i}`, w: 512, h: 512, codec: "BC3", mips: 10,
  score: 70, adjustedScore: adjusted, factors, png: "",
});
const GROUP_V2 = { mesh: "a.mesh", pool: 1650, state: "candidates", source: "batch", ranked: true,
  candidates: [CAND_V2(1, 1.09, F), CAND_V2(2, 2.5, { ...F, meanColor: [200, 200, 200] })] };

test("有因子就摆证据行：三个百分比 + 平均色点，一个都不省", () => {
  const html = texCandidatesHtml(GROUP_V2, []);
  assert.ok(html.includes("UV 贴合 12%"), html);
  assert.ok(html.includes("透明边界 100%"), html);
  assert.ok(html.includes("尺寸先验 80%"), html);
  assert.ok(html.includes("整体偏黑"), html);
  assert.ok(!html.includes("整体偏白"), "whiteBias=false 不该冒出「偏白」");
  assert.ok(html.includes("rgb(48, 34, 19)"), html);
});

test("没有因子（旧离线缓存）：整行不摆，绝不拿 0% 冒充「量过」", () => {
  const html = texCandidatesHtml({ ...GROUP_V2, ranked: false,
    candidates: [{ hash: "ff00000000000001", w: 256, h: 256, codec: "RGBA32", mips: 8, score: 4.2, png: "data:x" }] }, []);
  assert.ok(!html.includes("UV 贴合"), html);
  assert.ok(!html.includes("0%"), `不该出现假 0%：${html}`);
  assert.ok(html.includes("系统评分 4.2"), "方差分仍要说清");
  assert.ok(!html.includes("综合分"), "没有综合分别摆这一项");
});

test("有综合分就写明它是排序分，与方差分并列（两个数说的是两件事）", () => {
  const html = texCandidatesHtml(GROUP_V2, []);
  assert.ok(html.includes("综合分 2.50"), html);
  assert.ok(html.includes("系统评分 70.0"), html);
  assert.ok(html.includes("未确认"), "分数再高也只是候选态");
});

test("批量缓存的占位图按编号取，不再按名次（榜单会被重排）", () => {
  const html = texCandidatesHtml(GROUP_V2, []);
  assert.ok(html.includes('data-hash="ee00000000000001"'), html);
  assert.ok(!/<img[^>]*data-idx/.test(html), "取图的 img 不该再带名次（按钮的 data-idx 是另一回事）");
  assert.ok(!html.includes("data-mesh"), "按编号就不需要再带网格名");
});

test("排序依据这句话跟着后端口径走：ranked 说综合分，否则说方差比", () => {
  const ranked = texBlock({ texSlots: [], textureCandidates: [GROUP_V2] });
  assert.ok(ranked.note.includes("综合分"), ranked.note);
  const legacy = texBlock({ texSlots: [], textureCandidates: [{ ...GROUP_V2, ranked: false }] });
  assert.ok(legacy.note.includes("UV 岛内外方差比"), legacy.note);
  assert.ok(!legacy.note.includes("综合分"), legacy.note);
});

test("平均色只有三段才景色点：残缺就不画，不猜一个颜色出来", () => {
  const html = texCandidatesHtml({ ...GROUP_V2, candidates: [
    CAND_V2(1, 1.0, { ...F, meanColor: [1, 2] }),
    CAND_V2(2, 1.0, { ...F, meanColor: null }),
  ] }, []);
  assert.equal((html.match(/tex-mean/g) || []).length, 0, html);
});
