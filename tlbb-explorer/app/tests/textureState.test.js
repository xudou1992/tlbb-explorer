// textureState 的口径测试：候选必须标「未确认」，覆盖表确认才给 🟢；
// 没跑过试贴时槽位只能是 ⬜ 名字清单——🟡 是候选专用，名字清单不许冒用。
import { test } from "node:test";
import assert from "node:assert/strict";
import { texBlock, texSlotsHtml, texCandidatesHtml, trialPick, uvMapHtml, confirmTarget } from "../web/lib/textureState.js";

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

// ---- v0.4.1：没有候选榜时，把「后台批量试贴」这件事说清楚并给一颗按钮 ----
const NO_GROUP = { texSlots: [SLOT_A], textureCandidates: [] };

test("榜里没有这只网格：说清还差多少只，并给「后台跑完它们」", () => {
  const b = texBlock(NO_GROUP, { pending: 1234, running: false });
  assert.ok(b.slotsHtml.includes("还差 <b>1234</b> 只"), b.slotsHtml);
  assert.ok(b.slotsHtml.includes('data-act="warm"'), "要有一颗真能点的按钮");
});

test("已经在跑就只说在跑，不许再摆一颗按钮让人重复发起", () => {
  const b = texBlock(NO_GROUP, { pending: 1234, running: true });
  assert.ok(b.slotsHtml.includes("已经在跑"), b.slotsHtml);
  assert.ok(!b.slotsHtml.includes('data-act="warm"'), b.slotsHtml);
});

test("数不出来（没有资源清单）：不许写成「都跑完了」", () => {
  for (const warm of [{ pending: null }, {}]) {
    const b = texBlock(NO_GROUP, warm);
    assert.ok(b.slotsHtml.includes("数不出来"), JSON.stringify(warm) + " → " + b.slotsHtml);
    assert.ok(!b.slotsHtml.includes("都已进"), b.slotsHtml);
  }
});

test("全库都进过榜、这只仍没候选：说的是榜里没有可用候选，不是「还没跑」", () => {
  const b = texBlock(NO_GROUP, { pending: 0, running: false });
  assert.ok(b.slotsHtml.includes("都已进批量试贴榜"), b.slotsHtml);
  assert.ok(!b.slotsHtml.includes('data-act="warm"'), "没得跑就别摆按钮");
});

test("有候选榜时不提批量试贴这件事（榜都出来了，那句话是噪音）", () => {
  const b = texBlock({ texSlots: [SLOT_A], textureCandidates: [GROUP] }, { pending: 500 });
  assert.ok(!b.slotsHtml.includes("批量试贴"), b.slotsHtml);
});

test("多只网格各出一份榜：每份都要摆出来，按钮回指自己那份", () => {
  const g2 = { ...GROUP_V2, mesh: "b.mesh", candidates: [CAND_V2(3, 1.4, F)] };
  const b = texBlock({ texSlots: [SLOT_A, SLOT_B], textureCandidates: [GROUP_V2, g2] });
  assert.equal((b.candHtml.match(/class="tex-group"/g) || []).length, 2, b.candHtml);
  assert.ok(b.candHtml.includes("第 2 / 2 份榜 · 网格 b.mesh"), b.candHtml);
  assert.ok(b.note.includes("这一组有 2 只网格"), b.note);
  assert.equal((b.candHtml.match(/tex-slot-pick/g) || []).length, 2, "每份榜各有一个确认下拉");
  assert.ok(b.candHtml.includes('id="texSlotPick"'), "第一份沿用旧 id，老链路不破");
  assert.equal((b.candHtml.match(/data-gi="1" data-idx/g) || []).length, 2, "第二份的两颗按钮要带 gi");
});

test("只有一份榜时话术不变：不提份数，网格名照旧写在说明里", () => {
  const b = texBlock({ texSlots: [SLOT_A], textureCandidates: [GROUP_V2] });
  assert.ok(!b.note.includes("份榜"), b.note);
  assert.ok(b.note.includes("按网格 a.mesh 的离线试贴排序"), b.note);
  assert.ok(!b.candHtml.includes("第 1 / 1"), b.candHtml);
});

test("岛外无对比要单独说：榜首无对比时提示别照着确认，卡片上标出来", () => {
  const nc = (i, ov) => ({ hash: `dd0000000000000${i}`, w: 512, h: 512, codec: "BC3", mips: 10,
    score: 2882.4, adjustedScore: 1.1, factors: F, outsideVar: ov, png: "" });
  const g = { mesh: "nc.mesh", pool: 1650, state: "candidates", source: "batch", ranked: true,
    candidates: [nc(1, 0), nc(2, 240)] };
  const html = texCandidatesHtml(g, []);
  assert.ok(html.includes("岛外像素方差是 0"), html);
  assert.equal((html.match(/岛外无对比/g) || []).length, 1, "只在那张无对比的卡上标");
  assert.ok(!texCandidatesHtml({ ...g, candidates: [nc(2, 240)] }, []).includes("岛外无对比"), "有对比就不提");
  assert.ok(!texCandidatesHtml({ ...g, candidates: [{ ...nc(1, 0), outsideVar: undefined }] }, [])
    .includes("岛外无对比"), "旧缓存没量过 ≠ 无对比");
});

test("批量候选卡必须有看得见的占位：一行说明 + 按编号可寻；带内嵌图的卡不摆占位", () => {
  const g = { mesh: "p.mesh", pool: 1650, state: "candidates", source: "batch", ranked: true,
    candidates: [CAND_V2(1, 2.0, F), { ...CAND_V2(2, 1.5, F), png: "data:image/png;base64,AA" }] };
  const html = texCandidatesHtml(g, []);
  assert.equal((html.match(/class="tex-ph"/g) || []).length, 1, "只有还没图的那张摆占位");
  assert.ok(html.includes('data-ph-for="ee00000000000001"'), html);
  assert.ok(html.includes("缩略图要现解"), html);
});

test("区分度那一行：榜首出现次数写上卡面，只有通吃型（≥50）才追加劝退", () => {
  const withCount = (n) => texCandidatesHtml({ mesh: "q.mesh", pool: 1650, state: "candidates",
    source: "batch", ranked: true,
    candidates: [{ ...CAND_V2(1, 9.9, F), alsoFirstFor: n }] }, []);
  assert.ok(withCount(260).includes("260 只模型的榜首出现过"), "要报数");
  assert.ok(withCount(260).includes("说明得很少"), "通吃型要劝退");
  assert.ok(withCount(3).includes("3 只模型的榜首出现过"));
  assert.ok(!withCount(3).includes("说明得很少"), "少量重复是正常现象，不许说成可疑");
  assert.ok(!texCandidatesHtml({ mesh: "q.mesh", pool: 1, state: "candidates", ranked: false,
    candidates: [CAND_V2(1, 2, F)] }, []).includes("榜首出现过"), "取不到就不提");
});

test("trialPick：三种不该自动试贴的情况各说各的原因，能套才回候选", () => {
  const g = (cands) => ({ mesh: "t.mesh", pool: 1650, state: "candidates", source: "batch", ranked: true, candidates: cands });
  const c = (ov, adj) => ({ ...CAND_V2(1, adj, F), outsideVar: ov });
  assert.equal(trialPick(null).skip, "这只网格没有候选榜");
  assert.equal(trialPick(g([])).skip, "这只网格没有候选榜");
  assert.ok(trialPick(g([c(0, 9.9)])).skip.includes("岛外没有可比像素"), "无对比不套");
  assert.ok(trialPick(g([c(240, 1.02)])).skip.includes("1.02"), "退化带要说出具体的分");
  assert.equal(trialPick(g([c(240, 9.9)])).candidate.hash, CAND_V2(1, 9.9, F).hash, "有对比且分够高才套");
});

test("有榜就摆「退回灰模」那颗按钮，并说清立体预览上可能是试贴", () => {
  const b = texBlock({ texSlots: [SLOT_A], textureCandidates: [GROUP_V2] });
  assert.ok(b.candHtml.includes('data-act="clearTrial"'), b.candHtml);
  assert.ok(b.candHtml.includes("不是客户端认定的那张"), b.candHtml);
});

test("UV 岛分布图：覆盖率≈1 要说清「岛外没有像素可比」，没图就不摆格", () => {
  const ok = uvMapHtml({ png: "data:image/png;base64,AA", coverage: 1.0, faces: 80 });
  assert.ok(ok.includes("整张都铺了 UV，岛外没有像素可比"), ok);
  assert.ok(ok.includes("80 面"), ok);
  assert.ok(uvMapHtml({ png: "data:image/png;base64,AA", coverage: 0.678, faces: 666 }).includes("暗处是岛外"), "有岛外要说对比来源");
  assert.equal(uvMapHtml(null), "");
  assert.equal(uvMapHtml({ coverage: 0.5 }), "", "没有 png 就不摆空图框");
});

// 2026-10-11 真窗口撞到的：下拉里塞了个不在清单上的值，旧写法 `|| slots.find(s=>!s.overrideHash)`
// 把标注静默写到了**另一条槽位**上（我选的槽没写进去，第一条未确认的反倒变 🟢）。
// 覆盖表是贴图线唯一的标准答案来源，标错一条比少标一条贵得多。
test("确认不许改标到别的槽位，选不中就什么都不写", () => {
  assert.equal(confirmTarget([SLOT_A, SLOT_B], SLOT_B.name).slot, SLOT_B, "选中谁就写谁");
  const miss = confirmTarget([SLOT_A, SLOT_B], "不在这儿的野值.tga");
  assert.equal(miss.slot, undefined, "对不上不该返回任何槽位");
  assert.ok(miss.reason.includes("什么都没写"), miss.reason);
  assert.equal(confirmTarget([SLOT_A, SLOT_B], null).slot, undefined, "没选槽位也不该乱写");
  const done = confirmTarget([{ ...SLOT_A, overrideHash: "aa" }, { ...SLOT_B, overrideHash: "bb" }], SLOT_A.name);
  assert.equal(done.slot, undefined, "全确认了要说明为什么点不动");
  assert.ok(done.reason.includes("撤销"), done.reason);
  assert.ok(confirmTarget([], SLOT_A.name).reason, "空清单也要给原因，不是静默 return");
});