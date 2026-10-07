// 整组部件路径的显存闸门：setPartPose / setPose 的校验与整组并盒。
//
// WebGL 在 node 里开不了，但这两个方法的判断逻辑不依赖构造函数——用
// Object.create(MeshViewer.prototype) 配一个假 this（parts/buf/gl/draw）就能
// 走到真代码。校验不过必须静默回 false 且**不碰 bufferSubData**：蒙皮复合出
// NaN 或顶点数对不上时，画布停在上一帧的姿势，绝不能把坏数据灌进 GPU 画出鬼影。
// 「反向验红」的锚也在这里：把 setPartPose 的长度/坐标校验改松，这个文件先红。

import test from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { MeshViewer, partsUnionBounds } from "../web/mesh-viewer.js";

/// 配一个只够 setPartPose / setPose 用的假 this。gl 只记录调用，不模拟 GL 语义。
function bareViewer({ parts = null, mesh = null, inst = null } = {}) {
  const calls = { sub: 0, draw: 0 };
  const v = Object.create(MeshViewer.prototype);
  v.gl = {
    bindBuffer() {},
    bufferSubData() {
      calls.sub += 1;
    },
  };
  v.parts = parts;
  v.mesh = mesh;
  v.inst = inst;
  v.buf = { pos: {} };
  v.draw = () => {
    calls.draw += 1;
  };
  return { v, calls };
}

const pose = (n, x = 0) => Array.from({ length: n }, () => [x, x, x]);

test("setPartPose：合格顶点才进缓冲，且走 bufferSubData 不建新缓冲", () => {
  const { v, calls } = bareViewer({ parts: [{ vertexCount: 2, buf: { pos: {} } }] });
  assert.equal(v.setPartPose(0, [[1, 2, 3], [4, 5, 6]]), true, "合格顶点要摆上");
  assert.equal(calls.sub, 1, "一次 bufferSubData，内容替换而不是重建缓冲");
  assert.equal(calls.draw, 1, "摆完要重画");
});

test("setPartPose：顶点数对不上的一律拒绝（fresh 校验：换过缓冲的旧顶点进不来）", () => {
  const { v, calls } = bareViewer({ parts: [{ vertexCount: 3, buf: { pos: {} } }] });
  assert.equal(v.setPartPose(0, [[1, 2, 3]]), false, "少了顶点");
  assert.equal(v.setPartPose(0, [...pose(3), [1, 1, 1]]), false, "多了顶点");
  assert.equal(v.setPartPose(0, []), false, "空数组也不行");
  assert.equal(calls.sub, 0, "被拒的包一个字节都不能碰显存");
});

test("setPartPose：坐标不是有限数、形状不对、下标越界都拒绝", () => {
  const { v, calls } = bareViewer({ parts: [{ vertexCount: 2, buf: { pos: {} } }] });
  assert.equal(v.setPartPose(0, [[1, 2, Number.NaN], [4, 5, 6]]), false, "NaN 不进显存");
  assert.equal(v.setPartPose(0, [[1, 2, Infinity], [4, 5, 6]]), false, "Infinity 同罪");
  assert.equal(v.setPartPose(0, [[1, 2], [4, 5, 6]]), false, "不是三元组");
  assert.equal(v.setPartPose(0, "脏输入"), false, "不是数组");
  assert.equal(v.setPartPose(0, null), false);
  assert.equal(calls.sub, 0);
  assert.equal(v.setPartPose(1, pose(2)), false, "下标越界");
  assert.equal(v.setPartPose(-1, pose(2)), false, "负下标");
  assert.equal(v.setPartPose(0.5, pose(2)), false, "非整数下标");
  assert.equal(v.setPartPose("0", pose(2)), false, "字符串下标不是整数");
});

test("setPartPose / setPose 互斥：整组在架上时单网格的那条路必须关死", () => {
  const partsOn = bareViewer({ parts: [{ vertexCount: 2, buf: { pos: {} } }] });
  assert.equal(partsOn.v.setPose(pose(2)), false, "parts 在架上，setPose 不许动单网格缓冲");
  assert.equal(partsOn.calls.sub, 0);
  assert.equal(partsOn.v.setPartPose(0, pose(2)), true, "整组自己的路照常");

  const none = bareViewer({});
  assert.equal(none.v.setPartPose(0, pose(2)), false, "不在整组路径就没有部件可摆");
  assert.equal(none.v.setPose(pose(2)), false, "mesh 也没装：同样拒绝");

  const single = bareViewer({ mesh: { vertexCount: 2 }, inst: null, parts: null });
  assert.equal(single.v.setPose(pose(2)), true, "单网格老路不受影响");
  const inst = bareViewer({ mesh: { vertexCount: 2 }, inst: { count: 1 }, parts: null });
  assert.equal(inst.v.setPose(pose(2)), false, "多实例路径的几何在池里，不许被逐帧改写");
});

test("partsUnionBounds：整组并盒定取景框，单件的盒子会把其余件切出画面", () => {
  const a = { bboxMin: [0, 0, 0], bboxMax: [2, 2, 2] };
  const b = { bboxMin: [-4, 1, -1], bboxMax: [-1, 3, 1] };
  const u = partsUnionBounds([a, b]);
  assert.deepEqual(u.center, [-1, 1.5, 0.5], "中心是并盒中心，不是第一件的中心");
  assert.equal(u.size, 6, "尺寸取并盒最长边（x 跨 -4..2 = 6，不是第一件的 2）");
});

test("partsUnionBounds：脏件跳过、全脏兜底，绝不拿 NaN 凑盒子", () => {
  const good = { bboxMin: [0, 0, 0], bboxMax: [1, 1, 1] };
  const dirty = [
    null,
    {},
    { bboxMin: [0, 0], bboxMax: [1, 1, 1] },
    { bboxMin: [0, 0, 0], bboxMax: [1, 1, Number.NaN] },
    { bboxMin: ["x", 0, 0], bboxMax: [1, 1, 1] },
  ];
  const u = partsUnionBounds([good, ...dirty]);
  assert.deepEqual(u.center, [0.5, 0.5, 0.5], "脏件跳过，好件照算");
  assert.equal(u.size, 1);
  const fallback = partsUnionBounds(dirty);
  assert.deepEqual(fallback.center, [0, 0, 0], "一个能用的盒子都没有就回默认取景");
  assert.equal(fallback.size, 1);
  assert.deepEqual(partsUnionBounds(undefined).size, 1, "入参不是数组不抛");
  assert.deepEqual(partsUnionBounds("脏输入").center, [0, 0, 0]);
});

test("load() 的换仓段：索引数据必须进 ELEMENT 槽位（源码钉）", () => {
  // WebGL 在 node 里跑不了，但 e98f449 把 bufferData 的目标常量从 ELEMENT 改成
  // ARRAY_BUFFER 后灰模静默消失（索引字节灌进 UV 槽位、索引缓冲永远空、每帧
  // 1282），直到 2026-10-07 验收才有人肉眼撞见——GL 状态写错目标只能靠源码钉住。
  const src = readFileSync(new URL("../web/mesh-viewer.js", import.meta.url), "utf8");
  const seq = (body, bind, upload, tag) => {
    const at = body.indexOf(bind);
    assert.ok(at >= 0, tag + "：应有这一对调用：" + bind);
    const next = body.indexOf("gl.bufferData(", at);
    assert.ok(body.slice(next, next + 60).includes(upload), tag + "：紧跟的 bufferData 目标必须是 " + upload);
  };
  const load = src.slice(src.indexOf("load(data, bones)"), src.indexOf("unloadPool()", src.indexOf("load(data, bones)")));
  seq(load, "bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.buf.idx)", "gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, geo.indices", "load 换仓段");
  // 上传入口 uploadMesh 同理（两条路径共用）。
  const up = src.slice(src.indexOf("function uploadMesh"), src.indexOf("function viewOf"));
  seq(up, "bindBuffer(gl.ELEMENT_ARRAY_BUFFER, buf.idx)", "gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices", "uploadMesh");
});
