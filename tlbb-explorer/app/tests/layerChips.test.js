// 分层筹码的标签：段号是证据，不是装饰——人点「只看这一层」时要能对上「这层说的是第几段」。
// 纯函数放在 lib/layerChips.js，这里直接钉住，不需要 DOM。
import test from "node:test";
import assert from "node:assert/strict";
import { evidenceShort, layerChipLabels, layerSegmentLabel } from "../web/lib/layerChips.js";

const plan = {
  faceCounts: [100, 50, 30],
  layers: [
    { slot: "yifu.tga", blend: "opaque", faceStart: 0, faceCount: 100 },
    { slot: "c001.tga", blend: "add", faceStart: 100, faceCount: 50 },
    { slot: "c002.tga", blend: "add", faceStart: 150, faceCount: 30 },
  ],
};

test("每层报出它盖的第几段（按 faceCounts 的累计和算，不按层下标猜）", () => {
  assert.equal(layerSegmentLabel(plan, 0), "第 1 段");
  assert.equal(layerSegmentLabel(plan, 1), "第 2 段");
  assert.equal(layerSegmentLabel(plan, 2), "第 3 段");
});

test("基础层吞掉前几段时报跨度；叠在基础段上的额外层报同一段", () => {
  const spanned = {
    faceCounts: [100, 50, 30],
    layers: [{ slot: "base.tga", blend: "opaque", faceStart: 0, faceCount: 150 }],
  };
  assert.equal(layerSegmentLabel(spanned, 0), "第 1–2 段");
  const stacked = {
    faceCounts: [100, 50],
    layers: [
      { slot: "base.tga", blend: "opaque", faceStart: 0, faceCount: 100 },
      { slot: "extra.tga", blend: "add", faceStart: 0, faceCount: 100 },
    ],
  };
  assert.equal(layerSegmentLabel(stacked, 1), "第 1 段", "叠在同一段上的层说的也是这一段");
});

test("没有 faceCounts 或层窗口对不上时不编段号", () => {
  assert.equal(layerSegmentLabel({ layers: [{ faceStart: 0, faceCount: 10 }] }, 0), "");
  assert.equal(
    layerSegmentLabel({ faceCounts: [10], layers: [{ faceStart: 500, faceCount: 10 }] }, 0),
    "",
  );
});

test("名字只分三类：基础 / 特效 N / 材质 N，第 0 层永远是基础", () => {
  const labels = layerChipLabels(plan);
  assert.deepEqual(
    labels.map((l) => l.name),
    ["基础", "特效 1", "特效 2"],
  );
  const opaque = layerChipLabels({
    faceCounts: [10, 10],
    layers: [
      { slot: "a", blend: "opaque", faceStart: 0, faceCount: 10 },
      { slot: "b", blend: "opaque", faceStart: 10, faceCount: 10 },
    ],
  });
  assert.equal(opaque[1].name, "材质 1", "不透明第二材质不能叫特效");
  assert.equal(opaque[1].title, "b · 第 2 段", "title 里带槽名和段号，鼠标停上去能核");
});

test("没有层时回空数组：界面据此收起筹码行，不留空行", () => {
  assert.deepEqual(layerChipLabels(null), []);
  assert.deepEqual(layerChipLabels({ layers: [] }), []);
});

test("对齐证据短句分三形状：相等 / 颜色少（其余段按基础层铺）/ 颜色多（叠在基础段上）", () => {
  assert.equal(evidenceShort({ colorLayers: 5, submeshes: 5, aligned: true }), "颜色 5 张 = 子网格 5 段");
  assert.equal(
    evidenceShort({ colorLayers: 3, submeshes: 5, aligned: false }),
    "颜色 3 张 < 子网格 5 段（其余 2 段按基础层铺）",
    "少了要说清是材质表只给了几张、其余怎么画的",
  );
  assert.equal(
    evidenceShort({ colorLayers: 8, submeshes: 6, aligned: false }),
    "颜色 8 张 > 子网格 6 段（多出的 2 张叠在基础段上）",
  );
  assert.equal(evidenceShort(null), "", "没有证据就不写");
});
