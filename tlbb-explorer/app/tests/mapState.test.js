// 地图灰模状态机的不变式测试。跑法：在 app/ 下 `node --test tests/mapState.test.js`。
//
// 核心不是"算得对不对"，而是三件事：
//   1. 脏数据出不出现——换图、失败之后不许残留上一张图的字段；
//   2. 数字不许编——统计对不上就抛错，不能凑一个百分比；
//   3. "读到 0 个"和"还不知道"不许混——前者是 noObjects，后者是 empty。

import test from "node:test";
import assert from "node:assert/strict";
import { empty, loading, failed, ready, noObjects } from "../web/lib/mapState.js";

const MAP_A = "wudao_scene_a"; // 客户端原文 ID，未翻译

// 真实形状的回包（map_scene）。三个实例：两个有 matrix，一个只有名字。
const PAY_A = {
  mapId: MAP_A,
  instances: [
    { meshIndex: 0, matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 12, 0, 34, 1], name: "obj_denglong_01", label: "灯笼" },
    { meshIndex: 3, matrix: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 2, 8, 1], name: "obj_shitou_02", label: "" },
    { meshIndex: 7, matrix: null, name: "obj_men_03", label: "大门" },
  ],
  scenes: [
    { name: "cell_00_00", instances: 2, missing: 0, ok: true },
    { name: "cell_00_01", instances: 1, missing: 1, ok: false },
  ],
  missing: [{ name: "obj_men_03", reason: "客户端只给了名字，没有摆放矩阵" }],
  absent: [{ name: "地表格子贴图", reason: "客户端这把没有附带地面贴图" }],
  canDo: ["旋转 / 缩放", "点击查看实例"],
  tech: { base: "0x1a2b", stride: 68, unreadBytes: 24, elapsedMs: 31 },
};

/// 把状态里"会被写脏"的字段全数出来——新增区块时这条测试自动覆盖它。
function dirtyFields(s) {
  return {
    mapId: s.mapId,
    title: s.title,
    sum: s.sum,
    instances: s.instances.length,
    sceneHtml: s.scenes.html,
    sceneCount: s.scenes.count,
    sceneItems: s.scenes.items.length,
    countsResolved: s.counts ? s.counts.resolved : null,
    missingItems: s.missing.items.length,
    missingCount: s.missing.count,
    missingHtml: s.missing.html,
    absentHtml: s.absent.html,
    absentItems: s.absent.items.length,
    canDo: s.canDo.items.length,
    canDoHtml: s.canDo.html,
    techRows: s.tech.rows.length,
    techHtml: s.tech.html,
    error: s.error,
  };
}

test("加载成功后每个区块都被填上", () => {
  const s = ready(MAP_A, PAY_A);
  assert.equal(s.phase, "ready");
  assert.equal(s.mapId, MAP_A);
  assert.equal(s.title, MAP_A);
  assert.equal(s.missing.items.length, 1);
  assert.equal(s.missing.items[0].reason, "客户端只给了名字，没有摆放矩阵");
  assert.equal(s.instances.length, 3);
  assert.ok(s.instances[0].matrix.length === 16, "实例要带摆矩阵给渲染用");
  assert.equal(s.scenes.items.length, 2);
  assert.ok(s.scenes.html.length > 0, "格子清单要渲染出来");
  assert.ok(s.tech.html.includes("没读懂的字节"), "技术信息要写明没读懂的字节");
  assert.ok(s.sum.includes("3 个实例"), s.sum);
});

test("stats 不编数：counts.instances = 实例数，resolved + missing = 参与统计的总数", () => {
  const s = ready(MAP_A, PAY_A);
  assert.equal(s.counts.instances, s.instances.length);
  assert.equal(s.counts.resolved + s.counts.missing, s.instances.length);
  // 只有 matrix 的实例算已解析
  assert.equal(s.counts.resolved, 2);
  assert.equal(s.counts.missing, 1);
  // 空场景也自洽
  const e = ready(MAP_A, { mapId: MAP_A, instances: [] });
  assert.equal(e.counts.instances, 0);
  assert.equal(e.counts.resolved + e.counts.missing, 0);
});

test("统计对不上宁可抛错，也不显示一个凑出来的数", () => {
  // 后端报的 unresolved 数和实例数对不上——直接炸，不许圆过去
  assert.throws(() => ready(MAP_A, { mapId: MAP_A, instances: [{ meshIndex: 0, matrix: null }], unresolved: 5 }), /对不上/);
});

test("A 加载中 → 切到 B 且 B 失败：A 的数据一个字段都不许残留", () => {
  const a = ready(MAP_A, PAY_A);
  const mid = loading("map_b"); // 切到 B，正在读
  const b = failed("map_b", "自测台没有回放这张图");

  const aFields = dirtyFields(a);
  const midFields = dirtyFields(mid);
  const bFields = dirtyFields(b);
  // 不变式是"A 有内容的字段不再出现"，不是"必须为空"——B 失败时 error 写
  // 自己的原因是对的；A 本来就空的字段也无所谓残不残留。
  for (const [key, aVal] of Object.entries(aFields)) {
    if (aVal === "" || aVal === 0 || aVal === null || aVal === false) continue;
    assert.notEqual(bFields[key], aVal, `失败态残留 ${key}：${JSON.stringify(aVal)}`);
    assert.notEqual(midFields[key], aVal, `加载态残留 ${key}：${JSON.stringify(aVal)}`);
  }
  assert.equal(b.mapId, "map_b");
  assert.equal(b.title, "读取失败");
  assert.equal(b.error, "自测台没有回放这张图");
  // 残留检查的第二道保险：逐键比对 empty() 的键集
  assert.deepEqual(Object.keys(b).sort(), Object.keys(empty()).sort());
  assert.deepEqual(Object.keys(mid).sort(), Object.keys(empty()).sort());
  // 失败态剩下的只有错误本身
  assert.equal(b.instances.length, 0);
  assert.equal(b.counts, null);
  assert.equal(b.canDo.visible, false);
  assert.equal(b.tech.rows.length, 0);
});

test("失败态的每个区块都是空的，界面上不会留下空壳", () => {
  const s = failed(1, "x");
  assert.equal(s.phase, "error");
  assert.equal(s.scenes.items.length, 0);
  assert.equal(s.missing.items.length, 0);
  assert.equal(s.absent.items.length, 0);
  assert.equal(s.canDo.visible, false);
  assert.equal(s.tech.rows.length, 0);
  assert.equal(s.scenes.html, "");
  assert.equal(s.missing.html, "");
});

test("空态是唯一的起点：empty() 里所有字段都是假值或空容器", () => {
  const s = empty();
  assert.equal(s.phase, "empty");
  assert.deepEqual(dirtyFields(s), {
    mapId: "", title: "", sum: "",
    instances: 0, sceneHtml: "", sceneCount: "", sceneItems: 0,
    countsResolved: null, missingItems: 0, missingCount: "", missingHtml: "",
    absentHtml: "", absentItems: 0, canDo: 0, canDoHtml: "", techRows: 0, techHtml: "", error: "",
  });
  // 内容层面也必须是彻底空的
  assert.deepEqual(s.instances, []);
  assert.deepEqual(s.missing.items, []);
  assert.deepEqual(s.absent.items, []);
  assert.deepEqual(s.canDo.items, []);
  assert.deepEqual(s.tech.rows, []);
});

test("没数据时 counts 是 null（还不知道），不是 {0,0,0}（读到 0 个）", () => {
  assert.equal(empty().counts, null);
  assert.equal(loading("x").counts, null);
  assert.equal(failed("x", "e").counts, null);
  // 读到了确实是 0 个，才允许写 0
  const n = noObjects(MAP_A, { mapId: MAP_A, instances: [] });
  assert.deepEqual(n.counts, { instances: 0, resolved: 0, missing: 0 });
});

test("每个缺失项都要有客户端原文名字和非空原因，没原因就写「原因未定」", () => {
  const s = ready(MAP_A, PAY_A);
  for (const m of s.missing.items) {
    assert.ok(m.name && m.name.length > 0, "缺失项必须有名字");
    assert.ok(m.reason && m.reason.length > 0, `缺失项 ${m.name} 没有原因`);
    assert.notEqual(m.reason, "undefined");
    assert.notEqual(m.reason, "null");
  }
  // 明明是对象却没有 reason 字段：不许变成 undefined，也不许被丢掉
  const bare = ready(MAP_A, {
    mapId: MAP_A,
    instances: [{ meshIndex: 0, matrix: null, name: "a" }],
    missing: [{ name: "a" }, "b"],
  });
  assert.equal(bare.missing.items.length, 2, "缺原因也不能把条目丢掉");
  for (const m of bare.missing.items) {
    assert.ok(m.reason.length > 0, `${m.name} 的原因落成了空`);
  }
  assert.ok(
    bare.missing.items.every((m) => m.reason === "原因未定"),
    "没原因就必须明确写「原因未定」",
  );
  assert.ok(!/undefined|NaN/.test(bare.missing.html), "渲染出了空值字面量");
});

test("地图名就是客户端原文 ID：不许翻译、不许编中文名", () => {
  const raw = "wudao_scene_a";
  for (const s of [loading(raw), failed(raw, "x"), ready(raw, PAY_A), noObjects(raw, { mapId: raw, instances: [] })]) {
    assert.equal(s.mapId, raw);
    assert.ok(!/[一-鿿]/.test(s.mapId), `mapId 被加工出了中文：${s.mapId}`);
  }
  // 回包说的 ID 优先，且同样是原文
  assert.equal(ready("ignored", PAY_A).mapId, MAP_A);
  // 带中文的 ID 也原样透传，不许"顺手美化"
  const cn = "地图_east_01";
  assert.equal(ready(cn, { mapId: cn, instances: [] }).mapId, cn);
});

test("noObjects 和 failed 是两个状态：一个是读到了空的，一个是没读到", () => {
  const n = noObjects(MAP_A, { mapId: MAP_A, instances: [], scenes: [] });
  const f = failed(MAP_A, "文件读不出来");
  assert.equal(n.phase, "noObjects");
  assert.equal(f.phase, "error");
  assert.notEqual(n.phase, f.phase);
  // 措辞不同：空场景不是失败，得说清"读到了，里面是空的"
  assert.notEqual(n.title, f.title);
  assert.ok(n.sum.includes("读到了"), n.sum);
  assert.equal(f.error, "文件读不出来");
  assert.equal(n.error, "");
  // 空场景是成功态：counts 是真的 0，不是 null
  assert.ok(n.counts, "noObjects 必须带真实计数");
  assert.equal(n.counts.instances, 0);
  assert.ok(n.instances.length === 0);
  assert.ok(n.canDo.visible, "空场景也要说清还能做什么");
});

test("场景存在却一个实例都数不出来：格子照实标成实例数未读到", () => {
  const s = ready(MAP_A, { mapId: MAP_A, instances: [], scenes: [{ name: "cell_01" }] });
  assert.equal(s.scenes.items[0].instances, null, "没数到不许写 0");
  assert.ok(s.scenes.html.includes("实例数未读到"), s.scenes.html);
});

test("格子多到列不完时说还剩多少，不把几百行全塞进 DOM", () => {
  const scenes = Array.from({ length: 120 }, (_, i) => ({ name: `cell_${i}`, instances: 1 }));
  const s = ready(MAP_A, { mapId: MAP_A, instances: [], scenes });
  assert.equal((s.scenes.html.match(/<li class="hit"/g) || []).length, 40);
  assert.ok(s.scenes.html.includes("另有 80 个格子未列出"));
});

test("读不到的东西照实说，不圆场也不留空", () => {
  const s = ready(MAP_A, PAY_A);
  assert.ok(s.absent.html.includes("地表格子贴图"));
  assert.ok(s.absent.html.includes("这把没有附带"));
  const none = ready(MAP_A, { mapId: MAP_A, instances: [] });
  assert.equal(none.absent.html, "");
  // 条目在但没说原因：也要给一句话，不能渲染成空白
  const bare = ready(MAP_A, { mapId: MAP_A, instances: [], absent: [{ name: "光照" }, "阴影"] });
  assert.equal(bare.absent.items.length, 2);
  assert.ok(bare.absent.items.every((a) => a.reason === "原因未定"));
});

test("技术信息给排查的人看：缺值也占一行写「未读到」，不留空行", () => {
  const s = ready(MAP_A, { mapId: MAP_A, instances: [] });
  assert.ok(s.tech.rows.length >= 5);
  for (const [k, v] of s.tech.rows) {
    assert.ok(k && String(v).length > 0, `${k} 的值是空的`);
    assert.ok(!/undefined|NaN/.test(String(v)), `${k} 渲染出了空值字面量`);
  }
  assert.ok(s.tech.html.includes("未读到"));
});

test("非 ready 状态不渲染这些区块（也不留空壳）", () => {
  assert.equal(empty().missing.html, "");
  assert.equal(empty().absent.html, "");
  assert.equal(empty().canDo.html, "");
  assert.equal(empty().scenes.html, "");
  assert.equal(empty().tech.html, "");
  assert.equal(loading(1).missing.html, "");
  assert.equal(loading(1).tech.html, "");
  assert.equal(failed(1, "x").canDo.html, "");
  assert.equal(failed(1, "x").scenes.html, "");
});
