// 详情页状态机的不变式测试。跑法：在 app/ 下 `node --test tests/`。
//
// 核心不是"算得对不对"，而是**脏数据出不出现**：切换资产、加载失败之后，
// 屏幕上不允许残留上一条资产的任何一个字段。

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { empty, loading, failed, notReady, loaded, absencesOf, isNotReadyMsg } from "../web/lib/detailState.js";

// 两个真实形状的回包（从 --probe 落盘的 inspect_245 / detail_245 缩编而来）。
const CARD_A = {
  gid: 245,
  name: "w1351_monster_xiyuqiezei",
  kind: "NPC / 怪物",
  grade: "B",
  grade_word: "主体定位",
  gradeWord: "主体定位",
  gradeNote: "主体能打开，部分零件只有名字",
  named: true,
  memberTotal: 21,
  refTotal: 2,
  locatedTotal: 0,
};
const DETAIL_A = {
  card: CARD_A,
  gaps: ["贴图引用只有名称，未指向具体资源"],
  nameSource: "客户端文件名（原文展示，未翻译）",
  hubDecoded: true,
  tech: { id: "007cb62c6345c819", container: "data", offset: 1234, bytes: 5678, codec: "", rules: ["有网格成员"] },
};
const INSPECT_A = {
  found: true,
  what: "NPC / 怪物 w1351_monster_xiyuqiezei",
  names: [{ name: "w1351_x.tga", cls: "unique" }, { name: "西雨切泽", cls: "unique" }],
  dir: "data/source/npc/quest/w1351_monster_xiyuqiezei",
  parts: 21,
  counts: { mesh: 2, mtl: 2, ani: 15, ske: 1, tex: 2 },
  // 与真实 gid 245 同形状：21 个成员（1 模型定义 + 2 网格 + 2 材质 + 1 骨骼 + 15 动作），
  // 贴图一张都不在包里，只有材质引用的名字（悬空）。
  members: [
    { role: "model", roleZh: "模型", name: "w1351_monster_xiyuqiezei.mdl", path: "d/x.mdl", resolved: true },
    { role: "mesh", roleZh: "网格", name: "a.mesh", path: "d/a.mesh", resolved: true },
    { role: "mesh", roleZh: "网格", name: "b.mesh", path: "d/b.mesh", resolved: true },
    { role: "material", roleZh: "材质", name: "a.mtl", path: "d/a.mtl", resolved: true },
    { role: "material", roleZh: "材质", name: "b.mtl", path: "d/b.mtl", resolved: true },
    { role: "skeleton", roleZh: "骨骼", name: "a.ske", path: "d/a.ske", resolved: true },
    ...Array.from({ length: 15 }, (_, i) => ({
      role: "animation", roleZh: "动作", name: `act${i}.ani`, path: `d/act${i}.ani`, resolved: true,
    })),
  ],
  mdl: {
    name: "w1351_monster_xiyuqiezei",
    skeletons: [{ role: "骨骼", name: "a.ske", path: "d/a.ske", resolved: true }],
    bodies: [
      {
        label: "MainBodyMesh",
        mesh: { role: "网格", name: "a.mesh", path: "d/a.mesh", resolved: true, hash: "aaaa" },
        material: { role: "材质", name: "a.mtl", path: null, resolved: true },
        textureSlots: [{ role: "贴图", name: "a.tga", path: null, resolved: false }],
      },
    ],
    others: [],
  },
  missing: ["贴图 a.tga：客户端只保存名称，没有路径", "贴图 b.tga：客户端只保存名称，没有路径"],
  canDo: ["组成树", "立体预览（1 个网格）"],
  anims: ["w1351_monster_xiyuqiezei_idle01.ani", "w1351_monster_xiyuqiezei_run.ani"],
  previews: { items: [{ label: "a.tga", ok: true, dataUrl: "data:image/png;base64,AAA" }], total: 1, shown: 1 },
  elapsedMs: 120,
};

/// 把状态里"会被写脏"的字段全数出来——新增区块时这条测试自动覆盖它。
function dirtyFields(s) {
  return {
    title: s.title,
    cn: s.cn,
    grade: s.grade,
    gradeWord: s.gradeWord,
    gradeNote: s.gradeNote,
    sum: s.sum,
    treeHtml: s.tree.html,
    treeCount: s.tree.count,
    gaps: s.gaps.items.length,
    gapCount: s.gaps.count,
    absHtml: s.absences.html,
    absCount: s.absences.items.length,
    canDo: s.canDo.items.length,
    techHtml: s.tech.html,
    techRows: s.tech.rows.length,
    pvVisible: s.previews.visible,
    pvHtml: s.previews.html,
    meshVisible: s.mesh.visible,
    meshCount: s.mesh.meshes.length,
    meshMeta: s.mesh.meta,
  };
}

test("加载成功后每个区块都被填上", () => {
  const s = loaded(245, DETAIL_A, INSPECT_A);
  assert.equal(s.phase, "ready");
  assert.equal(s.title, "w1351_monster_xiyuqiezei");
  assert.equal(s.mesh.visible, true);
  assert.equal(s.previews.visible, true);
  assert.ok(s.tree.html.includes("这个材质用到的"), "材质槽必须出现在树里");
  assert.ok(s.tree.html.includes("模型定义"), "树必须标明属于哪个 .mdl");
  assert.ok(s.sum.includes("贴图引用 0/2 对上了文件"), "贴图口径要写进摘要");
});

test("A 加载中 → 切到 B 且 B 失败：A 的数据一个字段都不许残留", () => {
  const a = loaded(245, DETAIL_A, INSPECT_A);
  const mid = loading(246); // 切到 B，正在读
  const b = failed(246, "自测台没有回放这条");

  const aFields = dirtyFields(a);
  const bFields = dirtyFields(b);
  // 不变式是"A 有内容的字段不再出现"，不是"必须为空"——B 失败时 title 写
  // 「读取失败」是它自己的文案，那是对的；A 本来就空的字段也无所谓残不残留。
  for (const [key, aVal] of Object.entries(aFields)) {
    if (aVal === "" || aVal === 0 || aVal === false) continue;
    assert.notEqual(bFields[key], aVal, `失败态残留 ${key}：${JSON.stringify(aVal)}`);
    assert.notEqual(mid[key], aVal, `加载态残留 ${key}：${JSON.stringify(aVal)}`);
  }
  assert.equal(b.cn, "");
  assert.equal(b.title, "读取失败");
  assert.equal(b.error, "自测台没有回放这条");
  assert.equal(b.gid, 246);
  // 失败态剩下的只有错误本身
  assert.equal(b.mesh.visible, false);
  assert.equal(b.previews.visible, false);
  assert.equal(b.canDo.visible, false);
  assert.equal(b.tech.rows.length, 0);
});

test("失败态的每个区块 visible 都是 false，界面上不会留下空壳", () => {
  const s = failed(1, "x");
  assert.equal(s.mesh.visible, false);
  assert.equal(s.previews.visible, false);
  assert.equal(s.canDo.visible, false);
  assert.equal(s.gaps.items.length, 0);
  assert.equal(s.tech.rows.length, 0);
});

test("还没读到 ≠ 读取失败：措辞不同但同样干净", () => {
  const s = notReady(7);
  assert.equal(s.phase, "loading");
  assert.equal(s.title, "这条记录还没读到");
  assert.equal(s.mesh.visible, false);
  assert.equal(s.tech.rows.length, 0);
});

test("空态是唯一的起点：empty() 里所有字段都是假值或空容器", () => {
  const s = empty();
  assert.equal(s.phase, "empty");
  assert.deepEqual(dirtyFields(s), {
    title: "", cn: "", grade: "", gradeWord: "", gradeNote: "", sum: "",
    treeHtml: "", treeCount: "", gaps: 0, gapCount: "", absHtml: "", absCount: 0, canDo: 0,
    techHtml: "", techRows: 0, pvVisible: false, pvHtml: "",
    meshVisible: false, meshCount: 0, meshMeta: "",
  });
});

test("定位到实体但没有路径：不能显示成「缺」", () => {
  const s = loaded(245, DETAIL_A, INSPECT_A);
  assert.ok(s.tree.html.includes("已定位，但客户端没给路径"), "材质行是 resolved 无 path 的合法态");
  assert.ok(s.tree.html.includes('class="hit"'));
});

test("贴图一张都没解出来时，图片区整块不出现（灰卡不摆）", () => {
  const insp = { ...INSPECT_A, previews: { items: [{ label: "a.tga", ok: false, reason: "没找到" }], total: 0, shown: 0 } };
  const s = loaded(245, DETAIL_A, insp);
  assert.equal(s.previews.visible, false);
  assert.equal(s.previews.html, "");
});

test("一组压根没提到贴图时，不说「贴图名对上 0/0」", () => {
  const card = { ...CARD_A, refTotal: 0, locatedTotal: 0 };
  const s = loaded(245, { ...DETAIL_A, card }, INSPECT_A);
  assert.ok(!/0\/0/.test(s.sum), s.sum);
});

test("未命名资产不把编号摆成标题", () => {
  const card = { ...CARD_A, named: false, name: "01a0916c4123ae46" };
  const s = loaded(245, { ...DETAIL_A, card }, { ...INSPECT_A, what: "其他资源" });
  assert.equal(s.title, "未命名资源");
  assert.ok(!s.title.includes("01a0916c"));
});

test("超大组每类封顶 40 行并说明还剩多少", () => {
  const members = Array.from({ length: 120 }, (_, i) => ({
    role: "mesh", roleZh: "网格", name: `m${i}.mesh`, path: `d/m${i}.mesh`, resolved: true,
  }));
  const s = loaded(245, DETAIL_A, { ...INSPECT_A, members, mdl: null });
  const rows = (s.tree.html.match(/<li class="hit"/g) || []).length;
  assert.equal(rows, 40, `只该渲染 40 行，实际 ${rows}`);
  assert.ok(s.tree.html.includes("另有 80 个网格未列出"));
});

// ---------------------------------------------------------------- 有什么 · 缺什么

const STATES = ["ok", "missing", "unknown"];

test("任何真实形状的回包，「有什么缺什么」都不许空白", () => {
  const shapes = [
    INSPECT_A,
    { ...INSPECT_A, mdl: null, counts: { mesh: 0, mtl: 0, ani: 0, ske: 0, tex: 0 }, anims: [], previews: null },
    { ...INSPECT_A, counts: { mesh: 2, mtl: 0, ani: 0, ske: 0, tex: 0 }, mdl: null, previews: null },
    { ...INSPECT_A, counts: { mesh: 0, mtl: 0, ani: 15, ske: 1, tex: 0 }, mdl: null, anims: ["a.ani"], previews: null },
  ];
  shapes.forEach((insp, i) => {
    const rows = absencesOf(insp, CARD_A);
    assert.ok(rows.length >= 5, `第 ${i} 种形状只有 ${rows.length} 行`);
    for (const r of rows) {
      assert.ok(STATES.includes(r.state), `非法状态 ${r.state}`);
      assert.ok(r.label && r.why, `${r.label} 没说清原因`);
    }
  });
});

test("状态分三类：拿到了 / 客户端没给 / 工具还没解出，不许混为一谈", () => {
  const rows = absencesOf(INSPECT_A, CARD_A);
  const by = Object.fromEntries(rows.map((r) => [r.label, r]));
  assert.equal(by["立体模型"].state, "ok");
  // 骨骼文件在，挂接和权重都读出来了 —— 仍是未知（动作语义未全解），不能说成"缺"或"好了"
  assert.equal(by["骨骼"].state, "unknown");
  assert.ok(by["骨骼"].why.includes("谁挂谁"), by["骨骼"].why);
  assert.ok(!by["骨骼"].why.includes("还不能摆姿势"), "过时的「还不能摆」不许再出现", by["骨骼"].why);
  // 动作读出来了，动作页画布已经能按帧摆（锚=动作第 0 帧）
  assert.equal(by["动画"].state, "unknown");
  assert.ok(by["动画"].why.includes("按帧摆出来"), by["动画"].why);
  assert.ok(by["动画"].why.includes("第 0 帧为基准锚定"), by["动画"].why);
});

test("静态物件没有骨骼动画时，说「客户端没记过」而不是失败", () => {
  const insp = {
    ...INSPECT_A,
    mdl: null,
    counts: { mesh: 1, mtl: 1, ani: 0, ske: 0, tex: 0 },
    anims: [],
    previews: null,
    members: [
      { role: "mesh", roleZh: "网格", name: "a.mesh", path: "d/a.mesh", resolved: true },
      { role: "material", roleZh: "材质", name: "a.mtl", path: "d/a.mtl", resolved: true },
    ],
  };
  const by = Object.fromEntries(absencesOf(insp, CARD_A).map((r) => [r.label, r]));
  assert.equal(by["骨骼"].state, "missing");
  assert.ok(by["骨骼"].why.includes("没给它记过骨骼"), by["骨骼"].why);
  assert.ok(by["动画"].why.includes("没有动作文件"), by["动画"].why);
});

test("一张图都没解出来时，贴图行必须指回「缺什么」并说明是客户端没给路径", () => {
  const insp = { ...INSPECT_A, previews: null };
  const by = Object.fromEntries(absencesOf(insp, CARD_A).map((r) => [r.label, r]));
  assert.equal(by["贴图"].state, "missing");
  assert.ok(by["贴图"].why.includes("材质引用了 2 张贴图"), by["贴图"].why);
  assert.ok(by["贴图"].why.includes("只存了名字"), by["贴图"].why);
  assert.ok(by["贴图"].why.includes("缺什么"), by["贴图"].why);
});

test("cfg 出了出处的贴图：汇总句按「登记过位置 / 连位置都没记」分流，不再全说成没路径", () => {
  const insp = {
    ...INSPECT_A,
    previews: null,
    missing: [
      "贴图 a.tga：ResourcePath.cfg 里登记过它放在 data/source/npc/quest/w1351_boss_hadaba/texture/a.tga，但解包出来的文件里没有这张图",
      "贴图 b.tga：客户端只保存名称，没有路径",
    ],
  };
  const by = Object.fromEntries(absencesOf(insp, CARD_A).map((r) => [r.label, r]));
  assert.equal(by["贴图"].state, "missing");
  assert.ok(by["贴图"].why.includes("材质引用了 2 张贴图"), by["贴图"].why);
  assert.ok(by["贴图"].why.includes("1 张在 ResourcePath.cfg 里登记过存放位置"), by["贴图"].why);
  assert.ok(by["贴图"].why.includes("其余 1 张连存放位置都没记"), by["贴图"].why);
});

test("有贴图文件但没被任何材质引用：说成不知道用在哪，不说成没有贴图", () => {
  const insp = {
    ...INSPECT_A,
    previews: null,
    missing: [],
    members: [...INSPECT_A.members, { role: "texture", roleZh: "贴图", name: "x.tga", path: "d/x.tga", resolved: true }],
  };
  const by = Object.fromEntries(absencesOf(insp, CARD_A).map((r) => [r.label, r]));
  assert.equal(by["贴图"].state, "unknown");
  assert.ok(by["贴图"].why.includes("没有材质引用"), by["贴图"].why);
});

test("有网格文件但没有模型定义串起来：说成暂时画不出，不说成没有网格", () => {
  const insp = { ...INSPECT_A, mdl: null, previews: null };
  const by = Object.fromEntries(absencesOf(insp, CARD_A).map((r) => [r.label, r]));
  assert.equal(by["立体模型"].state, "unknown");
  assert.ok(/2 个网格文件/.test(by["立体模型"].why), by["立体模型"].why);
});

test("网格文件记了但客户端没带：说成缺，不推给工具", () => {
  const insp = {
    ...INSPECT_A,
    mdl: null,
    previews: null,
    members: [{ role: "mesh", roleZh: "网格", name: "a.mesh", path: null, resolved: false }],
  };
  const by = Object.fromEntries(absencesOf(insp, CARD_A).map((r) => [r.label, r]));
  assert.equal(by["立体模型"].state, "missing");
  assert.ok(/客户端未含/.test(by["立体模型"].why), by["立体模型"].why);
});

test("网格记了但文件不在：不能说成工具失败", () => {
  const insp = {
    ...INSPECT_A,
    mdl: { ...INSPECT_A.mdl, bodies: [] },
    previews: null,
    members: [
      { role: "mesh", roleZh: "网格", name: "a.mesh", path: null, resolved: false },
      { role: "mesh", roleZh: "网格", name: "b.mesh", path: null, resolved: false },
      { role: "mesh", roleZh: "网格", name: "c.mesh", path: null, resolved: false },
    ],
  };
  const by = Object.fromEntries(absencesOf(insp, CARD_A).map((r) => [r.label, r]));
  assert.equal(by["立体模型"].state, "missing");
  assert.ok(/客户端未含/.test(by["立体模型"].why), by["立体模型"].why);
});

test("「有什么缺什么」里不许出现编号、英文键或格式术语", () => {
  const s = loaded(245, DETAIL_A, INSPECT_A);
  // 查给人看的文字，不查 class（a-missing 里的英文是内部状态名）
  const text = s.absences.items.map((r) => `${r.label}${r.why}`).join(" ");
  assert.ok(!/[0-9a-f]{16}/.test(text), "出现了编号");
  assert.ok(!/\b(mesh|mtl|tex|ske|ani|JBCF|JMT1|codec|gid|hash)\b/.test(text), "出现了英文键");
  assert.ok(!/undefined|NaN|null/.test(s.absences.html), "渲染出了空值字面量");
  assert.ok(s.absences.items.every((r) => STATES.includes(r.state)));
});

test("非 ready 状态不渲染这个区块（也不留空壳）", () => {
  assert.equal(empty().absences.html, "");
  assert.equal(loading(1).absences.html, "");
  assert.equal(failed(1, "x").absences.html, "");
});

// ---- 立体面板不许静默消失（实测命中 84.4% 的资产组：没有可画网格的组）----
// 关键不是"有没有原因"，而是**两处必须是同一句**：立体区自己编一套说法的话，
// 和下面「缺什么」迟早分家，那时用户看到两个互相矛盾的解释。
test("画不出立体时面板还在，且理由是「缺什么」里那一句", () => {
  const cases = [
    ["没有模型定义", { ...INSPECT_A, mdl: null }],
    ["定义了部件但一个网格都没定位到", { ...INSPECT_A, mdl: { bodies: [{ mesh: { name: "a.mesh", hash: null }, material: { name: "a.mtl" } }] } }],
    ["一组里根本没有网格文件", { ...INSPECT_A, mdl: null, members: [] }],
  ];
  for (const [名, insp] of cases) {
    const s = loaded(245, DETAIL_A, insp);
    assert.equal(s.mesh.visible, true, `${名}：面板必须常驻，空白会让人以为工具坏了`);
    assert.equal(s.mesh.hasView, false, `${名}：但没网格可画时不许假装能画`);
    const row = s.absences.items.find((r) => r.label === "立体模型");
    assert.ok(row && row.why.length > 0, `${名}：必须给出一句原因`);
    assert.equal(s.mesh.why, row.why, `${名}：立体区与「缺什么」必须是同一句判断`);
    assert.ok(!/[0-9a-f]{16}/.test(s.mesh.why), `${名}：原因里不许出现编号`);
  }
});

// ---- 钉子：前端判定与后端原话逐字对齐（只读源码防呆，不改后端）----
// isNotReadyMsg 靠两个短语认「还没读到」；后端原话在 src-tauri/src/lib.rs
// （card_detail）和 src-tauri/src/inspector.rs（asset_inspect）。曾经的 bug：
// 前端拿「还在读取」当钉子，两句原话里都没有这四个连字，判定从未生效过，
// 预热中途点详情看到的是红线「读取失败」——把没读到说成了失败。
const here = dirname(fileURLToPath(import.meta.url));
const detailJs = readFileSync(join(here, "..", "web", "detail.js"), "utf8");
const libRs = readFileSync(join(here, "..", "src-tauri", "src", "lib.rs"), "utf8");
const inspectorRs = readFileSync(join(here, "..", "src-tauri", "src", "inspector.rs"), "utf8");

test("isNotReadyMsg 的两个钉子都还在后端原话里（card_detail / asset_inspect）", () => {
  assert.ok(libRs.includes("预热还在跑"), "lib.rs 的「还没读到」措辞被改了，前端判定会失明");
  assert.ok(inspectorRs.includes("还在后台读取"), "inspector.rs 的「还没读到」措辞被改了，前端判定会失明");
  assert.equal(isNotReadyMsg("这条资产现在读不出来（预热还在跑或数据本身有问题），稍后再试一次"), true);
  assert.equal(isNotReadyMsg("没有找到 id=245 的资源组（它还在后台读取中，或编号不存在）"), true);
  assert.equal(isNotReadyMsg("自测台没有回放这条"), false);
});

test("detail.js：「还没读到」要自动重试且设上限，判定走同一把钉子", () => {
  assert.match(detailJs, /isNotReadyMsg\(msg\)/, "不许另立一套字符串判定");
  assert.match(detailJs, /retried < 3/, "重试要设上限：无限轮询是后台一直在小声敲门");
  assert.match(detailJs, /2500/, "重试间隔 2.5 秒");
  assert.match(detailJs, /paint\(notReady\(gid\)\)/, "措辞必须是 notReady，不是 failed");
});
