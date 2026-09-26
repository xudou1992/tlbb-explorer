// 俯视量测的纯数学契约测试。跑法：在 app/ 下 `node --test "tests/*.test.js"`。
//
// 这一文件钉的是「量测视图会不会说谎」：
//   1) 格子名 ↔ 坐标的对应（CELL=32 是实测事实，不是配置项）
//   2) 取景对准连片主体（孤悬格子不许把主体压成一个点）
//   3) 像素 ↔ 世界互为逆变换（读数错 = 每个数都系统性偏移，且不报错）
//   4) 2D 点选取最小面积（相邻物件的矩形互相压着时，报你指的那件）
//
// 夹具数字全部来自实测回包（.scratch/ui_check/map_footprint_w1351_fb_wanjiegu_002.json），
// 不是手编的"看起来合理"的数——阈值类断言（如聚簇、格子里程）都要能在真实数据上复算。

import test from "node:test";
import assert from "node:assert/strict";

import { rotateY, translate, identity } from "../web/lib/instanceMath.js";
import {
  CELL, parseGridName, cellOf, occupiedCells, clustersOf, mainClusterBounds,
  instanceRects, fitView, pixelOf, worldOfPixel, pickRect,
} from "../web/lib/topdownMath.js";

const near = (a, b, eps = 1e-5) => Math.abs(a - b) <= eps;
const nearVec = (a, b, eps = 1e-5) => a.length === b.length && a.every((v, i) => near(v, b[i], eps));

// wanjiagu_002 里那条"疑似野摆位"的真实记录：榕树 w1351_dl_darongshu_002.mesh，
// 格子文件 1_-1717_-2645.scene 第 1 条，世界 (-54921.9, 30.35, -84616.5)。
// 它就是「格子名与坐标 100% 吻合」这条实测事实的反例证人——实测它不例外。
const BANYAN_BBOX = { bboxMin: [-4.829071, -0.33012876, -6.443432], bboxMax: [4.823885, 20.8812, 6.443434] };
const BANYAN_INST = {
  meshIndex: 0,
  matrix: [-0.2193493, 0, -0.8186221, 0, 0, 0.8475, 0, 0, 0.8186221, 0, -0.2193493, 0, -54921.9, 30.3534, -84616.5, 1],
  gridIndex: 0,
  recordIndex: 0,
};
const BANYAN_GRIDS = ["1_-1717_-2645.scene"];

// --------------------------------------------------------------------------
// 约定 1：格子名 ↔ 坐标。CELL 是实测常数，错一个数整张图的格子线全错位。
// --------------------------------------------------------------------------

test("格子边长 = 32：实测 floor(坐标/32) 与格子名下标吻合的判据就靠它", () => {
  assert.equal(CELL, 32);
  // 用那条"最容易被当成野摆位"的真实记录复算：它在自己格子内。
  assert.equal(Math.floor(BANYAN_INST.matrix[12] / CELL), -1717);
  assert.equal(Math.floor(BANYAN_INST.matrix[14] / CELL), -2645);
  assert.deepEqual(parseGridName("1_-1717_-2645.scene"), [-1717, -2645]);
});

test("parseGridName：正负下标都认，认不出的名字返回 null 而不是猜", () => {
  assert.deepEqual(parseGridName("2_3_5.scene"), [3, 5]);
  assert.deepEqual(parseGridName("0_0_0.scene"), [0, 0]);
  // 真实数据里读不通的格子是各种格式（版权头容器、水面参数），名字不会长这样。
  assert.equal(parseGridName("water_param.bin"), null);
  assert.equal(parseGridName(""), null);
  assert.equal(parseGridName(null), null);
});

test("cellOf：文件名优先；名字认不出时退回 floor(坐标/32)；两样都不行返回 null", () => {
  // 名字优先：哪怕坐标对不上也信名字——名字是客户端亲笔写的。
  const named = { gridIndex: 0, matrix: [...translate(999, 0, 999)] };
  assert.deepEqual(cellOf(named, ["1_-1717_-2645.scene"]), [-1717, -2645]);
  // 名字不认得：退回坐标兜底。真实数据里两者 100% 一致，这只是防格式变体。
  const anon = { gridIndex: 0, matrix: [...translate(-54921.9, 30, -84616.5)] };
  assert.deepEqual(cellOf(anon, ["unknown.bin"]), [-1717, -2645]);
  // 坐标 NaN 且名字不认得：null，调用方跳过——不编 (0,0)。
  const junk = { gridIndex: 0, matrix: new Array(16).fill(NaN) };
  assert.equal(cellOf(junk, ["unknown.bin"]), null);
});

test("occupiedCells：每个格子记条数，一格多件只出现一行", () => {
  const gridFiles = ["a_1_1.scene", "b_2_2.scene"];
  const cells = occupiedCells(
    [
      { gridIndex: 0, matrix: [...translate(33, 0, 33)] },
      { gridIndex: 0, matrix: [...translate(40, 0, 40)] },
      { gridIndex: 1, matrix: [...translate(65, 0, 65)] },
    ],
    gridFiles,
  );
  assert.equal(cells.length, 2);
  assert.deepEqual([cells[0].gx, cells[0].gz, cells[0].count], [1, 1, 2]);
  assert.deepEqual([cells[1].gx, cells[1].gz, cells[1].count], [2, 2, 1]);
});

// --------------------------------------------------------------------------
// 约定 2：聚簇取景。这是"wanjiegu 打开是地图还是一个点"的直接原因。
// --------------------------------------------------------------------------

test("clustersOf：连片是一簇，孤悬单格是另一簇，主体排最前", () => {
  // 缩小版 wanjiegu 实测形状：主簇 + 一个孤悬远格。
  const cells = occupiedCells(
    [
      { gridIndex: 0, matrix: [...translate(33, 0, 33)] },   // 格 (1,1)
      { gridIndex: 1, matrix: [...translate(65, 0, 33)] },   // 格 (2,1) 与上格相邻
      { gridIndex: 2, matrix: [...translate(33, 0, 65)] },   // 格 (1,2) 对角相连
      { gridIndex: 3, matrix: [...translate(-54921, 0, -84616)] }, // 格 (-1717,-2645)
    ],
    ["a_1_1.scene", "b_2_1.scene", "c_1_2.scene", "d_-1717_-2645.scene"],
  );
  const clusters = clustersOf(cells);
  assert.equal(clusters.length, 2, "对角也算相邻（8 邻域），前三格是一簇");
  assert.equal(clusters[0].length, 3, "连片主体必须排最前——取景就取它");
  assert.equal(clusters[1].length, 1);
  assert.deepEqual([clusters[1][0].gx, clusters[1][0].gz], [-1717, -2645]);
});

test("clustersOf：对角相邻也是一片（8 邻域不是 4 邻域）", () => {
  const cells = occupiedCells(
    [
      { gridIndex: 0, matrix: [...translate(33, 0, 33)] },  // (1,1)
      { gridIndex: 1, matrix: [...translate(65, 0, 65)] },  // (2,2) 只与上格对角相接
    ],
    ["a_1_1.scene", "b_2_2.scene"],
  );
  assert.equal(clustersOf(cells).length, 1, "只对角相接的两格是一簇，不是一个大一个小两簇");
});

test("clustersOf：同尺寸并列时取首现顺序，结果确定", () => {
  const cells = occupiedCells(
    [
      { gridIndex: 0, matrix: [...translate(33, 0, 33)] },
      { gridIndex: 1, matrix: [...translate(9999, 0, 9999)] },
    ],
    ["a_1_1.scene", "b_312_312.scene"],
  );
  const first = clustersOf(cells)[0];
  assert.deepEqual([first[0].gx, first[0].gz], [1, 1], "并列时先出现的算主体，两次调用结果一致");
});

test("mainClusterBounds：主体范围按格子边界取整，孤悬格不许撑大它", () => {
  // 同一个缩小版 wanjiegu 形状：主簇格 (1,1)(2,1)(1,2) + 孤悬 (-1717,-2645)。
  const cells = occupiedCells(
    [
      { gridIndex: 0, matrix: [...translate(33, 0, 33)] },
      { gridIndex: 1, matrix: [...translate(65, 0, 33)] },
      { gridIndex: 2, matrix: [...translate(33, 0, 65)] },
      { gridIndex: 3, matrix: [...translate(-54921, 0, -84616)] },
    ],
    ["a_1_1.scene", "b_2_1.scene", "c_1_2.scene", "d_-1717_-2645.scene"],
  );
  const b = mainClusterBounds(cells);
  // 主簇 x ∈ [1*32, 3*32)、z ∈ [1*32, 3*32)：两端都是格子边界。
  assert.deepEqual(
    [b.x0, b.z0, b.x1, b.z1],
    [1 * CELL, 1 * CELL, 3 * CELL, 3 * CELL],
  );
});

test("mainClusterBounds：没有可算的格子返回 null，不编 (0,0) 出来", () => {
  assert.equal(mainClusterBounds([]), null);
  assert.equal(mainClusterBounds(null), null);
});

// --------------------------------------------------------------------------
// 实例矩形：旋转必须按 8 角求，脏数据进 skipped 不进 rects。
// --------------------------------------------------------------------------

test("纯平移实例的俯视矩形 = 局部盒平移后的 XZ 投影", () => {
  const { rects, skipped } = instanceRects(
    [{ bboxMin: [-1, -1, -2], bboxMax: [1, 1, 2] }],
    [{ ...BANYAN_INST, matrix: [...translate(100, 50, 200)] }],
  );
  assert.equal(skipped, 0);
  const r = rects[0];
  assert.ok(nearVec([r.x0, r.z0, r.x1, r.z1], [99, 198, 101, 202]));
  assert.equal(r.meshIndex, 0);
  assert.equal(r.recordIndex, BANYAN_INST.recordIndex, "点选报「第几条」就靠这个字段原样透传");
});

test("绕 Y 转 45° 后矩形按 8 角扩张到 √2（只变换 min/max 会少一截）", () => {
  const { rects } = instanceRects(
    [{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }],
    [{ meshIndex: 0, matrix: [...rotateY(Math.PI / 4)], gridIndex: 0, recordIndex: 0 }],
  );
  const r = rects[0];
  assert.ok(near(r.x1, Math.SQRT2), `期望 √2，实际 ${r.x1}`);
  assert.ok(near(r.z1, Math.SQRT2));
  assert.ok(near(r.x0, -Math.SQRT2));
  // 边长 2 的方块转 45° 后外接盒边长 2√2、面积 8——「只变换 min/max 两个角」
  // 的写法会得到 2，一眼就能在这里分出来。
  assert.ok(near((r.x1 - r.x0) * (r.z1 - r.z0), 8, 1e-4));
});

test("真实榕树那条记录：矩形把落点包进去，且不出自己格子太多", () => {
  const { rects, skipped } = instanceRects([BANYAN_BBOX], [BANYAN_INST]);
  assert.equal(skipped, 0);
  const r = rects[0];
  // 落点必须被矩形包含——不然点着那棵树却选不中它。
  assert.ok(r.x0 <= BANYAN_INST.matrix[12] && BANYAN_INST.matrix[12] <= r.x1);
  assert.ok(r.z0 <= BANYAN_INST.matrix[14] && BANYAN_INST.matrix[14] <= r.z1);
  // 旋转 77° 后的盒子 XZ 投影宽 ~13（对角线方向），绝不该是 9.6（原始 x 宽）。
  const w = r.x1 - r.x0;
  assert.ok(w > 10 && w < 15, `旋转后的投影宽该在 10~15，实际 ${w}`);
});

test("脏数据进 skipped：没包围盒 / meshIndex 越界 / 矩阵有 NaN，各记一笔不出 NaN", () => {
  const meshes = [BANYAN_BBOX, {}]; // 第二个网格没有包围盒
  const bad = { gridIndex: 0, recordIndex: 0 };
  const { rects, skipped } = instanceRects(meshes, [
    { ...bad, meshIndex: 1, matrix: [...identity()] },   // 网格没盒子
    { ...bad, meshIndex: 9, matrix: [...identity()] },   // 网格不存在
    { ...bad, meshIndex: 0, matrix: [1, 2, 3] },         // 矩阵长度不对
    { ...bad, meshIndex: 0, matrix: new Array(16).fill(NaN) }, // 坐标 NaN
    { ...bad, meshIndex: 0, matrix: [...identity()] },   // 好的一条
  ]);
  assert.equal(skipped, 4, "四条算不了的各记一笔");
  assert.equal(rects.length, 1);
  assert.ok(rects.every((r) => [r.x0, r.x1, r.z0, r.z1].every(Number.isFinite)), "矩形里不许混进 NaN");
});

// --------------------------------------------------------------------------
// 取景：等比、留白、塌点上限。
// --------------------------------------------------------------------------

test("fitView 等比装进画布：窄长内容以高度为准，中心居中", () => {
  // 内容 10×100（一条南北向的路），画布 800×600，留 50 边。
  const v = fitView([{ x0: -5, z0: -50, x1: 5, z1: 50 }], 800, 600, 50);
  assert.ok(v, "装得下必须有取景");
  assert.ok(near(v.scale, 500 / 100), `scale 由窄边决定，期望 5，实际 ${v.scale}`);
  assert.ok(nearVec([v.cx, v.cz], [0, 0]));
});

test("fitView 尊重 padding：宽度受限时内容边正好贴着留白", () => {
  // 内容 100×50（扁宽），画布 800×600：宽度先顶到头，scale 由它决定。
  const v = fitView([{ x0: 0, z0: 0, x1: 100, z1: 50 }], 800, 600, 40);
  const [x0px] = pixelOf(0, 0, v, 800, 600);
  const [x1px] = pixelOf(100, 0, v, 800, 600);
  assert.ok(near(x0px, 40, 1e-6), `左边界该正好贴着 padding：${x0px}`);
  assert.ok(near(x1px, 760, 1e-6), `右边界同理：${x1px}`);
  // 高度方向只保证「不小于 padding」，不保证贴边（等比缩放的必然结果）。
  const [, z0px] = pixelOf(0, 0, v, 800, 600);
  assert.ok(z0px >= 40, `上边界至少留出 padding：${z0px}`);
});

test("fitView：没有矩形返回 null，不编一个原点取景", () => {
  assert.equal(fitView([], 800, 600, 10), null);
  assert.equal(fitView(null, 800, 600, 10), null);
});

test("所有矩形叠成一个点：放大有上限，不会冲到 Infinity", () => {
  const v = fitView([{ x0: 5, z0: -7, x1: 5, z1: -7 }], 800, 600, 20);
  assert.ok(v, "单个点也要有取景");
  assert.ok(nearVec([v.cx, v.cz], [5, -7]), "中心就是那个点");
  assert.ok(v.scale <= 760 / (4 * CELL) + 1e-9, `上限是 4 格铺满宽，实际 ${v.scale}`);
  assert.ok(Number.isFinite(v.scale));
});

// --------------------------------------------------------------------------
// 像素 ↔ 世界：互逆 + 朝向约定。读数错 = 每个数都错，且不报错。
// --------------------------------------------------------------------------

const VIEW = { cx: 100, cz: -200, scale: 0.5 };

test("worldOfPixel 是 pixelOf 的逆：世界→像素→世界原样回来", () => {
  const w = [123.4, -567.8];
  const p = pixelOf(w[0], w[1], VIEW, 800, 600);
  const back = worldOfPixel(p[0], p[1], VIEW, 800, 600);
  assert.ok(nearVec(back, w, 1e-6));
});

test("朝向约定：世界 x → 屏幕右，世界 z → 屏幕下", () => {
  const [px, py] = pixelOf(VIEW.cx, VIEW.cz, VIEW, 800, 600);
  assert.ok(nearVec([px, py], [400, 300], 1e-9), "中心映到画布中心");
  const [rx] = pixelOf(VIEW.cx + 10, VIEW.cz, VIEW, 800, 600);
  assert.ok(rx > px, "+x 该往右");
  const [, dy] = pixelOf(VIEW.cx, VIEW.cz + 10, VIEW, 800, 600);
  assert.ok(dy > py, "+z 该往下（哪边是北未证，界面不许说上北下南）");
});

test("worldOfPixel 的中心 = 取景中心（缩放不改变中心）", () => {
  const c = worldOfPixel(400, 300, VIEW, 800, 600);
  assert.ok(nearVec(c, [VIEW.cx, VIEW.cz], 1e-9));
});

// --------------------------------------------------------------------------
// 2D 点选：报你指的那件。
// --------------------------------------------------------------------------

const RECTS = [
  { x0: 0, z0: 0, x1: 10, z1: 10 },     // 大院子
  { x0: 2, z0: 2, x1: 5, z1: 5 },       // 院里的房子（嵌套）
  { x0: 20, z0: 20, x1: 30, z1: 30 },   // 隔壁
];

test("点在矩形里：命中；点在空地：null（量的是地面坐标，不是硬凑一件）", () => {
  assert.equal(pickRect(RECTS, 25, 25), 2);
  assert.equal(pickRect(RECTS, 100, 100), null, "点空地必须返回 null——硬凑最近物件等于说谎");
});

test("嵌套时取面积最小：点在房子上就报房子，不报包着它的院子", () => {
  assert.equal(pickRect(RECTS, 3, 3), 1, "房子 9，院子 100，取小的");
});

test("边界命中算命中（读数贴边时点选行为要确定）", () => {
  assert.equal(pickRect(RECTS, 0, 0), 0);
  assert.equal(pickRect(RECTS, 10, 10), 0);
});

test("点选结果与实例下标一致：renderer 拿它去查 mesh 路径和格子名", () => {
  const { rects } = instanceRects([BANYAN_BBOX], [BANYAN_INST]);
  const i = pickRect(rects, BANYAN_INST.matrix[12], BANYAN_INST.matrix[14]);
  assert.equal(i, 0);
  assert.equal(rects[i].gridIndex, 0, "gridIndex 透传，能指回 gridFiles");
});
