// 地图白话口径测试（v0.3.1）：别名没证据就叫未命名，原 ID 永远在场，未解的直说。
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  rowLabel, factsHeader, unresolvedHtml, UNNAMED_MAP, clusterStats, clusterFrame,
} from "../web/lib/mapView.js";

test("有证据别名显示别名，没有就叫未命名地图", () => {
  assert.equal(rowLabel("大理城"), "大理城");
  assert.equal(rowLabel(null), UNNAMED_MAP);
  assert.equal(rowLabel(""), UNNAMED_MAP);
  assert.equal(rowLabel("   "), UNNAMED_MAP);
});

test("头部事实：名称+ID 同场，无法定位的分母是实测实例数", () => {
  const f = factsHeader({ id: "w1351_ll_dl_002", alias: "大理城", grids: 103, records: 6112, resolved: 6101 });
  const map = Object.fromEntries(f);
  assert.equal(map["名称"], "大理城（人工标注）");
  assert.ok(map["ID"].includes("w1351_ll_dl_002"));
  assert.ok(map["ID"].includes("永远保留"));
  assert.equal(map["实例"], "6112 条");
  assert.equal(map["成功定位"], "6101 条");
  assert.equal(map["无法定位"], "11 条（分母是上面的实测实例数）");
});

test("没证据的地图：名称写明没有证据别名，不编一个", () => {
  const map = Object.fromEntries(factsHeader({ id: "w1351_fb_xxx_001", alias: null, grids: 1, records: 0, resolved: 0 }));
  assert.ok(map["名称"].includes("没有证据别名"));
});

test("还没解的：地形/碰撞/寻路直说未解析，贴图说部分可恢复，朝向说未证", () => {
  const h = unresolvedHtml();
  assert.ok(h.includes("地形：未解析"));
  assert.ok(h.includes("碰撞：未解析"));
  assert.ok(h.includes("寻路：未解析"));
  assert.ok(h.includes("贴图：部分可恢复"));
  assert.ok(h.includes("朝向：R 还是 Rᵀ 未证"));
  assert.ok(!h.includes("贴图 ✘"));
});

// ---- 立体视图取景：一格孤悬不许把整张图压成邮票 ----
//
// 实测 w1351_ll_wls_001（2026-11-03）：2,240 件、94 格，其中 1 格孤悬在 1,466 单位外。
// 按全体包围盒定相机 → 画面里 320 单位的主体只有 22% 大、还偏在左上角，
// 看上去像「这张图什么都没画」。俯视与缩略图按主簇取景是钉过的同一口径。

const tr = (x, y, z) => [1,0,0,0, 0,1,0,0, 0,0,1,0, x,y,z,1];
const 一簇加一格 = {
  gridFiles: ["w_a_0_0.scene", "w_a_1_0.scene", "w_a_45_0.scene"],
  instances: [
    { gridIndex: 0, matrix: tr(4, 0, 4) },
    { gridIndex: 0, matrix: tr(20, 1, 10) },
    { gridIndex: 1, matrix: tr(36, 0, 8) },
    { gridIndex: 2, matrix: tr(1448, 0, 8) }, // 孤悬 45 格外
  ],
};

test("clusterStats 数出主簇与孤悬格", () => {
  const cs = clusterStats(一簇加一格.instances, 一簇加一格.gridFiles);
  assert.equal(cs.cells, 3);
  assert.equal(cs.clusters, 2);
  assert.equal(cs.mainCells, 2);
  assert.equal(cs.stray, 1);
});

test("clusterFrame 只罩主簇，孤悬格不进相机", () => {
  const f = clusterFrame(一簇加一格.instances, 一簇加一格.gridFiles);
  assert.ok(f, "有格子就该算得出取景盒");
  assert.equal(f.kept, 3, "三条属于主簇的进盒，孤悬那条不进");
  assert.ok(f.size < 100, `取景尺寸该是主簇的尺度，实测 ${f.size}（全体包围盒会到 1444）`);
  assert.ok(Math.abs(f.center[0] - 20) < 1e-9, "中心落在主簇上，不被孤悬格拽走");
});

test("算不出格子就不硬给取景盒：回 null 让调用方保持原样", () => {
  assert.equal(clusterFrame([], []), null);
  assert.equal(clusterFrame([{ gridIndex: 0, matrix: tr(NaN, 0, NaN) }], ["没有坐标后缀.scene"]), null);
  assert.equal(clusterStats([], []), null);
});
