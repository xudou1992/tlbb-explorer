// 数字口径的措辞测试。跑法：在 app/ 下 `node --test tests/`。
//
// 规矩：任何出现在屏幕上的比值，标签里必须带着它的分母是什么。
// 这个项目被"同一句话两个口径"坑过：卡片的 0/2 只数贴图引用，
// 库状态的 62% 数的是全部引用，摆在一起用户就谁也不信了。

import test from "node:test";
import assert from "node:assert/strict";
import { pctText, texPair, listCount, railCount, citedVerdict, rowMissChip, mapNoObjects, progressLine, titleHtml, emptyMessage } from "../web/lib/wording.js";

test("25/30,585 显示成「不足 1%」而不是 0%", () => {
  assert.equal(pctText(0, 25), "不足 1%");
  assert.equal(pctText(0, 0), "0%"); // 真的一条都没有，就照说 0%
  assert.equal(pctText(62, 61408), "62%");
});

test("贴图引用必须带着「贴图」两个字出现", () => {
  assert.equal(texPair(0, 2), "贴图引用 0/2 对上了文件");
  assert.match(texPair(25, 22630), /^贴图引用/);
});

test("左栏底部只报一条总数，不在筛选栏里堆口径不同的比值", () => {
  // 曾经这里列三行明细，含「贴图引用对上 25 / 22,630」——分母只数贴图引用，
  // 和旁边两行的分母不是一个东西，摆一起只会让人以为整页不可信。
  // 现在只留总数一行，比值统一去「报告」浮层里说。
  const rc = railCount({ totalGroups: 13080, imageCandidates: 25 });
  assert.equal(rc.total, "13,080");
  assert.equal(rc.withImage, "25");
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

// 下面这几组数字全部来自 `tlbb-shell --maps` 落盘的真回包，不是编的样本。
test("格子真的空着才说「一个都没摆东西」", () => {
  const s = { grids: 28, records: 0, emptyGrids: 28, unreadableGrids: 0 };
  assert.equal(
    mapNoObjects(s),
    "读到了，这张图 28 个格子一个都没摆东西。能转、能缩放，就是看不到物件。",
  );
});

test("格子文件不是物件清单时，不许说成「没摆东西」", () => {
  // w1351_fb_jiebai_001：唯一一个 .scene 是版权头容器，根本没交出记录
  const s = { grids: 1, records: 0, emptyGrids: 0, unreadableGrids: 1 };
  const t = mapNoObjects(s);
  assert.ok(t.includes("1 个不是物件清单那类东西"), t);
  assert.ok(t.includes("一条摆位记录都没交出来"), t);
  assert.ok(!t.includes("一个都没摆东西"), "没摆东西＝这格本来空，跟读不通是两件事");
});

test("读不通与空格子并存时两个数都要出现", () => {
  const t = mapNoObjects({ grids: 10, records: 0, emptyGrids: 7, unreadableGrids: 3 });
  assert.ok(t.includes("3 个不是物件清单") && t.includes("7 个本来就是空格子"), t);
});

test("记录摆的不是网格时不能说成「没对上模型文件」", () => {
  // mqts_empty_001：2 条记录都是 .pu 特效，文件在客户端里真实存在
  const s = {
    grids: 2, records: 2, missingMeshes: 0, unreadableMeshes: 0,
    notMesh: 2, oddNames: 0, emptyNamed: 0, otherExt: [{ ext: "pu", records: 2 }],
  };
  const t = mapNoObjects(s);
  assert.ok(t.includes("2 条摆的本来就不是网格（.pu 2 条，文件是存在的）"), t);
  assert.ok(!t.includes("没对上"), t);
  assert.ok(!t.includes("缺"), "这类不是缺，这一版只是不画");
});

test("真缺、非网格、认不出的名字分开各说各的", () => {
  // w1351_fb_sixiangxiuxishi_001 的形态（这里把 resolved 压成 0 来验文案分支）
  const s = {
    grids: 2, records: 124, missingMeshes: 24, unreadableMeshes: 0,
    notMesh: 1, oddNames: 1, emptyNamed: 0, otherExt: [{ ext: "pu", records: 1 }],
  };
  const t = mapNoObjects(s);
  assert.ok(t.includes("24 条记的是网格，可客户端里取不出这个文件"), t);
  assert.ok(t.includes("1 条摆的本来就不是网格"), t);
  assert.ok(t.includes("1 条名字既不像文件名也不像路径"), t);
  assert.ok(t.includes("读到了 124 条记录"), t);
});

// ---- 顶栏进度一行字（懒预热之后按视图分两套口径）----

test("assets 口径：没读完必须带分母，读完只报总数", () => {
  const l = progressLine("assets", false, 300, 13080);
  assert.equal(l.text, "正在读取 2% · 300/13,080");
  assert.ok(l.text.includes("/13,080"), l.text);
  assert.equal(progressLine("assets", true, 13080, 13080).text, "已读完 13,080 组");
});

test("browse 口径：必须说清这只影响「资产」标签", () => {
  const l = progressLine("browse", false, 300, 13080);
  assert.ok(l.text.startsWith("资产库后台读取"), l.text);
  assert.ok(l.text.includes("300/13,080"), l.text);
  assert.ok(l.tip.includes("资产") && l.tip.includes("浏览"), l.tip);
  assert.equal(progressLine("browse", true, 13080, 13080).text, "资产库已读完 · 13,080 组");
});

test("分母还没读到（0/0）时不摆假数字：不说「0/0」也不说「读取 0%」", () => {
  // 刚触发预热的第一瞬 stats 回全 0：「正在读取 0% · 0/0」既不是进度也不是失败。
  // 浏览视图下更不能挂着「读取 0%」——那是把「还没读到」说成「正在读」。
  const a = progressLine("assets", false, 0, 0);
  assert.ok(!a.text.includes("0/0"), a.text);
  assert.ok(!a.text.includes("0%"), a.text);
  const b = progressLine("browse", false, 0, 0);
  assert.ok(!b.text.includes("0/0"), b.text);
  assert.ok(!/读取 0%/.test(b.text), b.text);
  assert.ok(b.tip.includes("浏览"), "浏览口径的悬停说明要继续在场");
});

// ---- 详情大标题的断行 ----

test("长资产名在下划线后插断点，不再从中间硬折", () => {
  // 真名字，来自 gid=2046（ui/icon/wardrobe）。
  // 不处理的话浏览器会把「…shukuanganxiang_」和「001」拆成两行。
  const h = titleHtml("w1351_nan_s_shukuanganxiang_001");
  assert.ok(h.includes("_<wbr>"), h);
  assert.ok(h.includes("shukuanganxiang_<wbr>001"), h);
  // 纯文本内容不变（<wbr> 是零宽的，读出来还是原名）。
  assert.equal(h.replace(/<wbr>/g, ""), "w1351_nan_s_shukuanganxiang_001");
});

test("短名字不插断点：本来就不会折，插了只是噪音", () => {
  assert.equal(titleHtml("icon_mr"), "icon_mr");
  assert.equal(titleHtml("角色甲"), "角色甲");
  assert.ok(!titleHtml("a_b_c").includes("<wbr>"));
});

test("标题转义：名字里带尖括号也不能当标签跑掉", () => {
  assert.equal(titleHtml("<img src=x>"), "&lt;img src=x&gt;");
  assert.ok(!titleHtml("aaaaaaaaaaaaaaaaaaaaaaaaaaaa<b>").includes("<b>"));
});

/// 筛空列表的锅常常在「还开着的筛选条件」上：这些条件存在本地、重启也还在。
/// 只说「没有命中关键词」是把锅推给搜索词。
test("空列表文案点名还开着的筛选条件", () => {
  const 默认 = { kind: "全部", scenario: "全部", grade: "全部", onlyImage: false, named: true };
  const a = emptyMessage({ query: "xiyuqiezei", state: { ...默认, kind: "场景物件" }, ready: true });
  assert.ok(a.strong.includes("xiyuqiezei"), "搜索词要还在");
  assert.ok(a.span.includes("类型：场景物件"), `要点名开着的条件：${a.span}`);
  assert.ok(a.span.includes("重启也还在"), "要说清它会跨启动留着");

  const b = emptyMessage({ query: "", state: { ...默认, grade: "A" }, ready: true });
  assert.ok(b.strong.includes("筛空"), `没有搜索词时该说是条件筛空的：${b.strong}`);
  assert.ok(b.span.includes("完整程度：A"), b.span);

  const c = emptyMessage({ query: "", state: 默认, ready: true });
  assert.ok(c.span.includes("未命名"), "全默认还空着，该提示默认不列未命名资产");

  const d = emptyMessage({ query: "x", state: 默认, ready: false });
  assert.ok(d.strong.includes("后台还在准备"), `没读完不该说没命中：${d.strong}`);
});
