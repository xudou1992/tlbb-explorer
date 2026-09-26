// 地图白话口径测试（v0.3.1）：别名没证据就叫未命名，原 ID 永远在场，未解的直说。
import { test } from "node:test";
import assert from "node:assert/strict";
import { rowLabel, factsHeader, unresolvedHtml, UNNAMED_MAP } from "../web/lib/mapView.js";

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
