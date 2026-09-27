// 多实例绘制的纯数学契约测试。跑法：在 app/ 下 `node --test "tests/*.test.js"`。
//
// WebGL 在 node 里开不了，所以这里**不 mock 整个 GL 栈**——那只会在测试里重建
// 一个假浏览器，然后测出"我写的那份假实现和我的理解一致"这种废话。
// 真正会错、又只能靠数值验的部分被抽进了 web/lib/instanceMath.js 和
// mesh-viewer.js 里几个导出的纯函数，这个文件钉的就是它们：
//   1) 行主序 / 列主序的约定（错了屏幕上是镜像和错位，不会抛异常）
//   2) 合并顺序（先局部、后实例、最后相机——顺序错了物件会跟着相机跑）
//   3) 世界包围盒（相机卡在房子里的直接原因就是这里算错）
//   4) 法线矩阵（非等比缩放会歪，要能测出"它确实歪了"，而不是假装普适）
//   5) 点选反投影（解不出射线就等于点选恒不中，且不报错）
//
// 还有一条纪律：**导出面要小**。这里点名导出了哪些函数，就等于承诺了哪些是
// 稳定契约；随手把内部辅助函数 export 出去会让测试变成对实现细节的复读机。

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  identity, translate, rotateY, scaleMat, mul, transformPoint, transposeRotationBlock,
  normalMatrix3, shapeScaleError, expandInstances, boundsAccumulator,
  worldBounds, pixelRay, rayBox, nearestHit,
} from "../web/lib/instanceMath.js";

import { collapseMeshes, instancedBounds, instancedPickBounds } from "../web/mesh-viewer.js";

const near = (a, b, eps = 1e-5) => Math.abs(a - b) <= eps;
const nearVec = (a, b, eps = 1e-5) => a.length === b.length && a.every((v, i) => near(v, b[i], eps));

// --------------------------------------------------------------------------
// 约定 1：行主序。整个文件里最容易静默出错的一条。
// --------------------------------------------------------------------------

test("行主序下平移量落在 m[12..14]，而不是 m[3..5]", () => {
  const m = translate(7, -3, 2);
  assert.equal(m[12], 7);
  assert.equal(m[13], -3);
  assert.equal(m[14], 2);
  // 最后一列之外的 m[3]/m[7]/m[11] 必须是 0，否则就是列主序写进来的。
  assert.equal(m[3], 0);
  assert.equal(m[7], 0);
  assert.equal(m[11], 0);
  // 而列主序会把这些值放在 m[3],m[7],m[11]——这正是"转置错了不报错"的地方。
  assert.deepEqual([...m.slice(0, 3)], [1, 0, 0]);
});

test("变换一个点：p' = M * p，平移能生效", () => {
  const m = translate(1.5, -2, 0.25);
  assert.deepEqual(transformPoint(m, [10, 20, 30]), [11.5, 18, 30.25]);
});

test("绕 Y 转 90° 的转向是 +X → -Z（实测约定，别照教科书猜）", () => {
  // 关键判据：如果矩阵被当成列主序用，符号会反，变成 +Z。
  // 这条期望值是照着 mesh-viewer.js 里 mat4.rotateY 实测出来的，
  // 不是按"右手系逆时针"想出来的——转向反了不会报错，只会让地图整体转错向。
  const p = transformPoint(rotateY(Math.PI / 2), [1, 0, 0]);
  assert.ok(nearVec(p, [0, 0, -1]), `期望 [0,0,-1]，实际 [${p}]`);
  // 反着转 90° 就该回到 +Z，两个方向都得钉住，免得把"符号搞反"当成通过。
  assert.ok(nearVec(transformPoint(rotateY(-Math.PI / 2), [1, 0, 0]), [0, 0, 1]));
});

test("绕 Y 转 90° 不碰 Y 轴（它才是旋转轴）", () => {
  assert.ok(nearVec(transformPoint(rotateY(Math.PI / 2), [0, 1, 0]), [0, 1, 0]));
});

test("identity 乘任何矩阵都不改变它", () => {
  const m = mul(translate(3, 4, 5), rotateY(0.7));
  assert.ok(nearVec([...mul(identity(), m)], [...m]));
  assert.ok(nearVec([...mul(m, identity())], [...m]));
});

// ==========================================================================
// 跨层契约：`.scene` 记录里那 16 个 f32 直读进前端，到喂 GL 之前**排布不许变**。
//
// 这一组断言的锚点不是本文件的任何函数，而是**客户端字节布局这个外部事实**：
// 全库实测（三张图 7,406 条）平移落在 flat[12..14]、齐次位在 flat[3,7,11,15]，
// 且 floor(x/32) 与格子文件名下标 100% 吻合。所以"平移进、平移出"是可判定的。
// 曾经这里多做一次整阵转置，把平移搬到 [3,7,11]：地图首帧全部物件叠在原点，
// 而**不报任何错**——那时代码里没有一个测试能发现，因为旧夹具把转置写进了约定。
// ==========================================================================

/// 一条真实的 `.scene` 记录前 64 字节（单位旋转 + 平移 100,50,200）按 f32 直读的结果。
const SCENE_ROW = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 100, 50, 200, 1];

test("契约：`.scene` 直读的平移必须原样待在 [12..14]，不许被搬到别处", () => {
  const out = expandInstances([{ meshIndex: 0, matrix: SCENE_ROW }], 1);
  assert.deepEqual([out.model[12], out.model[13], out.model[14]], [100, 50, 200]);
  assert.deepEqual([out.model[3], out.model[7], out.model[11], out.model[15]], [0, 0, 0, 1]);
});

test("契约：真实地图尺度下，实例的世界位置就是矩阵里的平移", () => {
  // 取 w1351_ll_dl_002 里那种量级：z 在负半边（floor 判据靠它）。
  const row = [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, -1234.5, 12.25, -987.5, 1];
  const out = expandInstances([{ meshIndex: 0, matrix: row }], 1);
  assert.deepEqual(
    transformPoint(out.model.subarray(0, 16), [0, 0, 0]),
    [-1234.5, 12.25, -987.5],
    "局部原点必须被摆到记录里那个世界坐标",
  );
});

test("契约：GL 布局下的 view 矩阵，pixelRay 取到的相机位置等于 -Rᵀ·t", () => {
  // 相机在 (0,0,+10) 看向 -Z：view = 沿 Z 平移 -10，平移按 GL 布局就在 [12..14]。
  const v = translate(0, 0, -10);
  assert.deepEqual([v[12], v[13], v[14]], [0, 0, -10], "先确认 translate 的排布本身");
  const ray = pixelRay(400, 300, RECT, v, FOV, ASPECT);
  assert.ok(nearVec(ray.origin, [0, 0, 10], 1e-6), `origin=[${ray.origin}]`);
});

test("朝向开关只翻旋转块，绝不动平移与齐次位", () => {
  const out = expandInstances([{ meshIndex: 0, matrix: SCENE_ROW }], 1, { transposeRotation: true });
  assert.deepEqual([out.model[12], out.model[13], out.model[14]], [100, 50, 200], "开关不许把平移带跑");
  assert.deepEqual([out.model[3], out.model[7], out.model[11], out.model[15]], [0, 0, 0, 1]);
  // 非对称探针：转置必须真的改变 [1],[4] 这一对。
  const skew = [1, 2, 3, 0, 4, 5, 6, 0, 7, 8, 9, 0, 100, 50, 200, 1];
  const t = transposeRotationBlock(skew);
  assert.deepEqual([t[1], t[4]], [4, 2]);
  assert.deepEqual([t[2], t[8]], [7, 3]);
  assert.deepEqual([t[6], t[9]], [8, 6]);
  assert.deepEqual([...t.slice(12)], [100, 50, 200, 1]);
  // 转两次回原样（对合），且单位阵测不出转置——所以探针必须用非对称的。
  assert.deepEqual([...transposeRotationBlock(t)], skew);
  assert.deepEqual([...transposeRotationBlock(identity())], [...identity()]);
});

// --------------------------------------------------------------------------
// 约定 2：合并顺序 = 先局部 → 再实例 → 最后相机（uModelView * instance * pos）
// --------------------------------------------------------------------------

test("纯平移时两种顺序的矩阵相同——所以顺序问题不能靠平移测", () => {
  const instance = translate(100, 0, 0);
  const modelView = translate(0, 0, -5); // 相机退后 5
  // 正确顺序：mv * instance * p
  const right = transformPoint(mul(modelView, instance), [1, 0, 0]);
  assert.deepEqual(right, [101, 0, -5]);
  // 纯平移矩阵之间可交换：两个矩阵**逐位相同**。所以"顺序写反"这件事
  // 在只有平移的场景里根本测不出来——这就是为什么下面那条必须用旋转。
  assert.deepEqual([...mul(modelView, instance)], [...mul(instance, modelView)]);
  assert.deepEqual(transformPoint(mul(instance, modelView), [1, 0, 0]), [101, 0, -5]);
});

test("顺序的正确判据是旋转：先转后挪 vs 先挪后转，结果不同", () => {
  // 物件先被旋转 90° 再挪到 x=10：(10,0,0) + R*(1,0,0)
  const instance = mul(translate(10, 0, 0), rotateY(-Math.PI / 2));
  // 相机带着 90° 旋转和一段平移。
  const modelView = mul(translate(0, 0, -20), rotateY(Math.PI / 2));
  const right = transformPoint(mul(modelView, instance), [1, 0, 0]);
  const wrong = transformPoint(mul(instance, modelView), [1, 0, 0]);
  // 差得不是一点点：这才是"顺序写反了"能被看出来的地方。
  assert.notDeepEqual(right, wrong);
  // 正确顺序下，实例矩阵先把点送到世界 (10,0,1)，再被相机矩阵收进去。
  const expect = transformPoint(modelView, [10, 0, 1]);
  assert.ok(nearVec(right, expect, 1e-5), `期望 [${expect}]，实际 [${right}]`);
});

test("纯平移的两个矩阵可交换 → 顺序问题必须用旋转才测得出来", () => {
  const instance = translate(1000, 0, 0);
  const modelView = translate(-7, 0, -5);
  const right = transformPoint(mul(modelView, instance), [0, 0, 0]);
  // 换一个顺序给出**完全相同**的结果：两张纯平移矩阵逐位相等。
  // 这条不是废话——它说明"我只测了平移"不足以证明乘法序写对了。
  const swapped = transformPoint(mul(instance, modelView), [0, 0, 0]);
  assert.deepEqual([...mul(modelView, instance)], [...mul(instance, modelView)]);
  assert.deepEqual(right, [993, 0, -5]);
  assert.deepEqual(swapped, right);
});

test("旋转 + 平移组合：实例矩阵按 (T * R) 作用，先转后挪", () => {
  const inst = mul(translate(10, 0, 0), rotateY(-Math.PI / 2));
  const p = transformPoint(inst, [1, 0, 0]);
  assert.ok(nearVec(p, [10, 0, 1]), `期望 [10,0,1]，实际 [${p}]`);
});

test("scaleMat 只缩放三个基向量，不动平移", () => {
  const m = scaleMat(translate(3, 4, 5), 2);
  assert.deepEqual([...m.slice(12, 15)], [3, 4, 5]);
  assert.ok(nearVec(transformPoint(m, [1, 1, 1]), [5, 6, 7]));
});

// --------------------------------------------------------------------------
// expandInstances：行主序进来，列主序 + 法线矩阵出去
// --------------------------------------------------------------------------

test("expandInstances 原样收进缓冲：GL 布局进、GL 布局出，中间不转置", () => {
  const out = expandInstances([{ meshIndex: 0, matrix: [...translate(5, 6, 7)] }], 1);
  assert.equal(out.count, 1);
  assert.equal(out.model[12], 5, "平移必须还在 [12..14]——它一旦被搬走，全图叠原点");
  assert.equal(out.model[13], 6);
  assert.equal(out.model[14], 7);
  assert.deepEqual([out.model[3], out.model[7], out.model[11]], [0, 0, 0]);
  // 只留一份缓冲：喂 GL 用的和存的就是同一套字节。
  assert.equal(out.model.length, 16);
  assert.ok(!("modelColumnMajor" in out), "不该再有第二份转置好的缓冲");
});

test("引用不到的网格编号：抛错，不画一个洞", () => {
  assert.throws(() => expandInstances([{ meshIndex: 3, matrix: [...identity()] }], 1), /不存在的网格编号 3/);
  assert.throws(() => expandInstances([{ meshIndex: -1, matrix: [...identity()] }], 1), /不存在的网格编号/);
});

test("矩阵不是 16 个数：说清是第几个实例、实际给了几个", () => {
  assert.throws(
    () => expandInstances([{ meshIndex: 0, matrix: [1, 2, 3] }], 1),
    /第 0 个实例的变换矩阵不是 16 个数（实际 3）/,
  );
});

test("多个实例各归各位：meshIndex 和矩阵不串行", () => {
  const out = expandInstances(
    [
      { meshIndex: 0, matrix: [...translate(1, 0, 0)] },
      { meshIndex: 1, matrix: [...translate(0, 2, 0)] },
      { meshIndex: 0, matrix: [...translate(0, 0, 3)] },
    ],
    2,
  );
  assert.deepEqual([...out.meshIndex], [0, 1, 0]);
  assert.equal(out.model[12], 1);
  assert.equal(out.model[16 + 13], 2);
  assert.equal(out.model[32 + 14], 3);
});

// --------------------------------------------------------------------------
// 法线矩阵：假设是"旋转 + 均匀缩放"，非等比缩放会坏——这条必须被钉住
// --------------------------------------------------------------------------

test("纯旋转下法线矩阵就是那个旋转本身", () => {
  // 按语义验：把 +X 法线转过去，方向必须和 transformPoint 给出的一致；
  // "和另一个函数算的一样"不算证据，这里两边用的是各自的实现。
  const r = rotateY(Math.PI / 2);
  const n = normalMatrix3(r);
  assert.ok(nearVec(transformPoint3(n, [1, 0, 0]), [0, 0, -1], 1e-6), `[${transformPoint3(n, [1, 0, 0])}]`);
  assert.ok(nearVec(transformPoint3(n, [0, 1, 0]), [0, 1, 0], 1e-6));
  // 与变换点的结果逐步对齐（旋转下法线和点走同一套）。
  const viaPoint = transformPoint(r, [0, 1, 0]);
  assert.ok(nearVec(transformPoint3(n, [0, 1, 0]), viaPoint, 1e-6));
});

test("法线矩阵不含平移：含平移的实例和纯旋转版本的 9 个数逐位相同", () => {
  const a = normalMatrix3(rotateY(0.9));
  const b = normalMatrix3(mul(translate(120, -8, 40), rotateY(0.9)));
  for (let i = 0; i < 9; i++) assert.ok(near(a[i], b[i], 1e-6), `第 ${i} 项 ${a[i]} vs ${b[i]}`);
});

test("法线矩阵已经是 GL 布局：三个基向量在前，喂 uniformMatrix3fv 前不再转置", () => {
  // 这里曾经"最贵"：两个 3x3 都是 9 个 float，多转一次**不报错**，只是光照整体偏，
  // 看起来像美术参数没调好。normalMatrix3 输出的就是 GL 要的那份，转置反而是错。
  const r = rotateY(Math.PI / 2);
  const n = normalMatrix3(r);
  // GL 布局下第 0 列 = X 基向量的像。rotateY(+90°) 把 +X 送到 -Z（文件头实测那条）。
  assert.ok(nearVec([...n.slice(0, 3)], [0, 0, -1], 1e-6), `第 0 列=[${n.slice(0, 3)}]`);
  assert.ok(nearVec([...n.slice(3, 6)], [0, 1, 0], 1e-6));
  assert.ok(nearVec([...n.slice(6, 9)], [1, 0, 0], 1e-6));
  // 9 个数与旋转块的前三列一一对应，没有第二份排布。
  assert.ok(nearVec([...n], [r[0], r[1], r[2], r[4], r[5], r[6], r[8], r[9], r[10]], 1e-6));
  const out = expandInstances([{ meshIndex: 0, matrix: [...r] }], 1);
  for (let i = 0; i < 9; i++) assert.ok(near(out.normal[i], n[i], 1e-6), `第 ${i} 项与 normalMatrix3 不一致`);
});

test("均匀缩放：法线矩阵把它归一化掉，方向不受影响", () => {
  const m = scaleMat(rotateY(0.4), 7.5);
  const n = normalMatrix3(m);
  const plain = normalMatrix3(rotateY(0.4));
  // 归一化后两者必须逐元素一致——否则光照会随物件大小变亮变暗。
  for (let i = 0; i < 9; i++) assert.ok(near(n[i], plain[i], 1e-6), `第 ${i} 项 ${n[i]} vs ${plain[i]}`);
});

test("**假设不成立**：非等比缩放会让法线歪，shapeScaleError 必须报得出来", () => {
  // scale(3,1,1) 这种非等比缩放，是"抽 3x3 各列归一化"这个近似的失效条件。
  const m = scaleMat(identity(), 1);
  m[0] = 3; m[5] = 1; m[10] = 1; // 手工制造非等比缩放
  assert.ok(shapeScaleError(m) > 0.6, `非等比缩放该被检出，实际 ${shapeScaleError(m)}`);

  // 斜法线 (1,1,0)/√2 在非等比缩放下的**正确**像：法线该乘 (M^-1)^T，
  // 即 (1/3, 1, 0)，归一化后明显偏向 +Y。
  const n = normalMatrix3(m);
  // 我们的近似：各列归一化 → 第一列 (1,0,0)、第二列 (0,1,0)，斜法线的方向原样保持 45°。
  const approx = transformPoint3(n, [Math.SQRT1_2, Math.SQRT1_2, 0]);
  const correct = norm([1 / 3, 1, 0]);
  const dot = approx[0] * correct[0] + approx[1] * correct[1] + approx[2] * correct[2];
  assert.ok(dot < 0.95, `近似法与正确法线该有可见夹角，实际 cos=${dot}`);
  // 同时确认"轴对齐"的法线在这种矩阵下仍旧是对的——偏差只出现在斜法线上，
  // 所以地图里正对轴向的墙面看不出问题，斜屋顶会。这句话要能测出来才算数。
  assert.ok(nearVec(transformPoint3(n, [1, 0, 0]), [1, 0, 0], 1e-6));
});

test("等比缩放的 shapeScaleError 是 0（浮点噪声要归一掉）", () => {
  assert.equal(shapeScaleError(scaleMat(rotateY(2), 4)), 0);
  assert.equal(shapeScaleError(identity()), 0);
  assert.equal(shapeScaleError(scaleMat(rotateY(1.3), 0.03)), 0);
});

test("某轴被压成 0：退回单位方向，不给 NaN", () => {
  const m = new Float32Array(16);
  m[0] = 1; m[5] = 1; m[10] = 0; m[15] = 1; // 第三列全零
  const n = normalMatrix3(m);
  assert.ok([...n].every((v) => Number.isFinite(v)), `不该出现 NaN：[${n}]`);
  assert.ok(nearVec([...n.slice(6, 9)], [0, 0, 1], 1e-6));
});

// --------------------------------------------------------------------------
// 世界包围盒：相机卡在房子里的直接原因
// --------------------------------------------------------------------------

test("单个实例的世界盒 = 局部盒按矩阵变换后的 8 角包围盒", () => {
  const b = worldBounds([{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }], [{ meshIndex: 0, matrix: [...translate(10, 0, 0)] }]);
  assert.deepEqual(b.min, [9, -1, -1]);
  assert.deepEqual(b.max, [11, 1, 1]);
  assert.deepEqual(b.center, [10, 0, 0]);
  assert.equal(b.size, 2);
});

test("多实例：世界盒把**所有**落点都包进去，不是只看第一个", () => {
  // 这是"地图一打开相机站在某栋房子里"的回归测试。
  const meshes = [{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }];
  const instances = [
    { meshIndex: 0, matrix: [...translate(0, 0, 0)] },
    { meshIndex: 0, matrix: [...translate(400, 0, 0)] },
    { meshIndex: 0, matrix: [...translate(0, 0, -900)] },
  ];
  const b = worldBounds(meshes, instances);
  assert.equal(b.min[0], -1);
  assert.equal(b.max[0], 401);
  assert.equal(b.min[2], -901);
  assert.equal(b.max[2], 1);
  // 局部盒的 size 只有 2，世界盒必须是 902——差 450 倍。用局部盒当相机的家，
  // 相机就会停在原点那个盒子里，而地图其实铺到 900 开外。
  assert.equal(b.size, 902);
  assert.ok(b.size > 2 * 100, "相机必须按世界尺度安置");
});

test("绕 Y 转 45° 后仍用 8 角求盒（不能只变换 min/max 两个角）", () => {
  const b = worldBounds(
    [{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }],
    [{ meshIndex: 0, matrix: [...rotateY(Math.PI / 4)] }],
  );
  // 转 45° 后，原来 (±1,±1) 那个角在 XZ 上铺到 √2。只变换 min/max 两个角
  // 会算成 1，少掉 0.414 一圈——地形边缘就会被相机裁掉。
  assert.ok(near(b.max[0], Math.SQRT2, 1e-5), `期望 ${Math.SQRT2}，实际 ${b.max[0]}`);
  assert.ok(near(b.max[2], Math.SQRT2, 1e-5), `期望 ${Math.SQRT2}，实际 ${b.max[2]}`);
  assert.ok(near(b.min[0], -Math.SQRT2, 1e-5));
  assert.ok(near(b.min[2], -Math.SQRT2, 1e-5));
  // 直接变换 min/max 两个角只会得到 1，这条把那种写法钉死。
  assert.ok(b.max[0] > 1.3, "8 角法求出来必须明显大于 1");
  // Y 不受绕 Y 旋转影响。
  assert.equal(b.max[1], 1);
  assert.equal(b.min[1], -1);
});

test("两个不同网格混排：各自的局部盒都按自己的矩阵进盒", () => {
  const meshes = [
    { bboxMin: [0, 0, 0], bboxMax: [1, 1, 1] },   // 小盒子，挪到 x=-100
    { bboxMin: [0, 0, 0], bboxMax: [50, 50, 50] }, // 大盒子，留在原地
  ];
  const b = worldBounds(meshes, [
    { meshIndex: 0, matrix: [...translate(-100, 0, 0)] },
    { meshIndex: 1, matrix: [...identity()] },
  ]);
  // 两个盒子在 X 上并不重叠（-100..-99 和 0..50），所以整体盒必须横跨到 50。
  // 如果实现把"第一个网格的盒子"当成全体（那种写法在地图里非常常见），
  // 这里会只得到 -100..-99 —— 表现就是相机贴在那个小人身上、看不到大建筑。
  assert.equal(b.min[0], -100);
  assert.equal(b.max[0], 50);
  assert.equal(b.size, 150);
  // 两个网格的高度不同，Y 上取并集。
  assert.equal(b.min[1], 0);
  assert.equal(b.max[1], 50);
});

test("一个实例都没有：返回 null，不编一个 {0,0,0} 出来", () => {
  assert.equal(boundsAccumulator().result(), null);
  assert.equal(worldBounds([{ bboxMin: [0, 0, 0], bboxMax: [1, 1, 1] }], []), null);
});

test("全部塌在一个点：size 有下限，不会算出 0 距离把相机贴死", () => {
  const b = worldBounds([{ bboxMin: [5, 5, 5], bboxMax: [5, 5, 5] }], [{ meshIndex: 0, matrix: [...identity()] }]);
  assert.equal(b.size, 1e-3);
  assert.deepEqual(b.center, [5, 5, 5]);
});

test("引用不到网格或没有包围盒的实例被跳过，剩下的照常算", () => {
  // 这两种都是"这条实例算不了"，不是"整张图算不了"：跳过它、把能算的算出来，
  // 而不是让整个包围盒变 null —— 那样相机就没家了。
  // 注意这里的 worldBounds 用的是 mesh-viewer 的导出（吃原始实例表），
  // 它和 instancedBounds 共用同一个 addBox 守卫。
  const meshes = [{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }, {}];
  const b = worldBounds(meshes, [
    { meshIndex: 1, matrix: [...translate(999, 0, 0)] }, // 第二个网格没包围盒
    { meshIndex: 7, matrix: [...translate(999, 0, 0)] }, // 网格根本不存在的下标
    { meshIndex: 0, matrix: [...identity()] },
  ]);
  assert.notEqual(b, null, "有一半实例算不了，也不能整体变 null");
  assert.deepEqual(b.min, [-1, -1, -1]);
  assert.deepEqual(b.max, [1, 1, 1]);
});

test("包围盒里混进 NaN：跳过那一个，不让 NaN 静默吞掉整个盒子", () => {
  // NaN 进了 min/max 比较会永远不更新，结果是"看着正常、其实漏了东西"的盒子。
  const b = worldBounds(
    [{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }, { bboxMin: [NaN, 0, 0], bboxMax: [NaN, 1, 1] }],
    [{ meshIndex: 0, matrix: [...identity()] }, { meshIndex: 1, matrix: [...translate(50, 0, 0)] }],
  );
  assert.deepEqual(b.min, [-1, -1, -1]);
  assert.deepEqual(b.max, [1, 1, 1]);
});

// --------------------------------------------------------------------------
// 点选：屏幕像素 → 世界射线 → 最近命中
// --------------------------------------------------------------------------

const RECT = { left: 0, top: 0, width: 800, height: 600 };
const ASPECT = 800 / 600;
const FOV = Math.PI / 4.5;

/// 造一个"相机在 (0,0,+d)、看向 -Z"的 view 矩阵，用于反投影测试。
/// GL 布局下 view = translate(0,0,-d) 直接就是它，**不需要也不允许再转置**。
const lookFromZ = (d) => translate(0, 0, -d);

test("屏幕正中 → 射线沿 -Z 直直打出去", () => {
  const ray = pixelRay(400, 300, RECT, lookFromZ(10), FOV, ASPECT);
  assert.ok(nearVec(ray.origin, [0, 0, 10], 1e-6), `origin=[${ray.origin}]`);
  assert.ok(near(ray.dir[0], 0, 1e-6) && near(ray.dir[1], 0, 1e-6));
  assert.ok(near(ray.dir[2], -1, 1e-6), `dir=[${ray.dir}]`);
});

test("屏幕右侧 → 射线往 +X 偏；上方 → 往 +Y 偏（Y 翻转不能忘）", () => {
  const right = pixelRay(800, 300, RECT, lookFromZ(10), FOV, ASPECT);
  assert.ok(right.dir[0] > 0.1, `点右半边该往 +X，实际 ${right.dir[0]}`);
  assert.ok(near(right.dir[1], 0, 1e-6));
  // 屏幕 y 向下增大，NDC 向上为正：点靠上的像素（y=0）射线该往 +Y。
  const top = pixelRay(400, 0, RECT, lookFromZ(10), FOV, ASPECT);
  assert.ok(top.dir[1] > 0.1, `点上半边该往 +Y，实际 ${top.dir[1]}`);
  const bottom = pixelRay(400, 600, RECT, lookFromZ(10), FOV, ASPECT);
  assert.ok(bottom.dir[1] < -0.1, `点下半边该往 -Y，实际 ${bottom.dir[1]}`);
});

test("画布不在屏幕原点时，像素要相对 rect 换算", () => {
  const shifted = { left: 200, top: 100, width: 800, height: 600 };
  // 同一个物理点：rect 里的正中 = 页面上的 (600, 400)。
  const a = pixelRay(400, 300, RECT, lookFromZ(10), FOV, ASPECT);
  const b = pixelRay(600, 400, shifted, lookFromZ(10), FOV, ASPECT);
  assert.ok(nearVec(a.dir, b.dir, 1e-6), `${a.dir} vs ${b.dir}`);
});

test("相机被挪到别处时，反投影里的起点和方向都跟着走", () => {
  const ray = pixelRay(400, 300, RECT, lookFromZ(10), FOV, ASPECT);
  assert.ok(nearVec(ray.origin, [0, 0, 10], 1e-6));
  assert.ok(nearVec(ray.dir, [0, 0, -1], 1e-6));

  // 相机带 90° 旋转时，屏幕正中那条射线必须跟着拐，不能再直着打 -Z。
  // 期望值是从几何反推的，不是拿实现对自身：V = T(0,0,-10)·Ry(90°)（和 draw() 的
  // 拼法同序），世界点 p 映到 Ry·p + (0,0,-10)。
  //   · 原点映到 (0,0,-10) = 相机前方 10 ⇒ 相机在离原点 10 处；
  //   · 解 Ry·eye = (0,0,10)：Ry(90°) 的三个基向量是 col0=(0,0,-1)、col1=(0,1,0)、
  //     col2=(1,0,0)，于是 (eye) 满足 (z, y, -x) = (0,0,10) ⇒ **eye = (-10, 0, 0)**；
  //   · 前方 = Ry⁻¹·(0,0,-1) = 各列与 (0,0,-1) 点乘 ⇒ **+X**，从 (-10,0,0) 指回原点。
  // 这一条同时是"起点按列取还是按行取"的判据：取错不报错，只表现为点选恒不中。
  const turned = mul(translate(0, 0, -10), rotateY(Math.PI / 2));
  const r3 = pixelRay(400, 300, RECT, turned, FOV, ASPECT);
  assert.ok(nearVec(r3.origin, [-10, 0, 0], 1e-6), `origin=[${r3.origin}]`);
  assert.ok(nearVec(r3.dir, [1, 0, 0], 1e-6), `dir=[${r3.dir}]`);
  // 上面两个数是手算的，这条不是：相机是按"盯着世界原点"摆的，所以原点必须落在
  // 屏幕正中央那条射线上。判据 = |(-eye) × dir| 为 0。它不依赖本文件任何函数，
  // 起点按行取还是按列取在这里立刻见分晓——转置错的那版这条是 10，直接红。
  const toOrigin = r3.origin.map((v) => -v);
  const cross = [
    r3.dir[1] * toOrigin[2] - r3.dir[2] * toOrigin[1],
    r3.dir[2] * toOrigin[0] - r3.dir[0] * toOrigin[2],
    r3.dir[0] * toOrigin[1] - r3.dir[1] * toOrigin[0],
  ];
  assert.ok(near(Math.hypot(...cross), 0, 1e-9), `屏幕中心的射线没穿过世界原点：|×|=${Math.hypot(...cross)}`);
});

test("rayBox：正对着打中，t 是进入面的距离", () => {
  const t = rayBox([0, 0, 10], [0, 0, -1], [-1, -1, -1], [1, 1, 1]);
  assert.ok(near(t, 9), `期望 9，实际 ${t}`);
});

test("rayBox：擦过去没打中返回 null", () => {
  assert.equal(rayBox([5, 0, 10], [0, 0, -1], [-1, -1, -1], [1, 1, 1]), null);
  // 背后（盒子在射线的反方向）也不算命中。
  assert.equal(rayBox([0, 0, 10], [0, 0, 1], [-1, -1, -1], [1, 1, 1]), null);
});

test("rayBox：起点在盒内 → t=0，不当成穿透", () => {
  assert.equal(rayBox([0, 0, 0], [0, 0, -1], [-1, -1, -1], [1, 1, 1]), 0);
});

test("rayBox：射线与某组面平行时，靠另两组面照样能判", () => {
  // 沿 +X 打，同时 y 正好卡在盒子的上边界上——平行且贴着，算命中。
  const t = rayBox([-10, 1, 0], [1, 0, 0], [-1, -1, -1], [1, 1, 1]);
  assert.ok(near(t, 9), `期望 9，实际 ${t}`);
  // 平行且在外面——永远打不中。
  assert.equal(rayBox([-10, 5, 0], [1, 0, 0], [-1, -1, -1], [1, 1, 1]), null);
});

test("nearestHit：多个候选时取 t 最小（离相机最近），不是数组里第一个", () => {
  const entries = [
    { bound: { min: [-1, -1, 9], max: [1, 1, 11] } },  // t = 9
    { bound: { min: [-1, -1, 1], max: [1, 1, 3] } },   // t = 19…等等，先看下面
  ];
  // 相机在 z=20 往 -Z 看：先碰到 z=11 那个盒子。
  const hit = nearestHit([0, 0, 20], [0, 0, -1], entries);
  assert.equal(hit.index, 0);
  assert.ok(near(hit.t, 9));
  assert.equal(hit.approximate, true, "必须自报是近似，不能假装精确");
});

test("nearestHit：越近的越优先，与列表顺序无关", () => {
  const far = { bound: { min: [-1, -1, 0], max: [1, 1, 2] } };
  const close = { bound: { min: [-1, -1, 8], max: [1, 1, 10] } };
  const hit = nearestHit([0, 0, 20], [0, 0, -1], [far, close]);
  assert.equal(hit.index, 1);
});

test("nearestHit：都没打中返回 null，不返回一个随便的下标", () => {
  const entries = [{ bound: { min: [50, 50, 50], max: [51, 51, 51] } }];
  assert.equal(nearestHit([0, 0, 0], [0, 0, -1], entries), null);
  assert.equal(nearestHit([0, 0, 0], [0, 0, -1], []), null);
  // 缺 bound 的条目被跳过，不影响别人。
  const mixed = [{ bound: null }, { bound: { min: [-1, -1, -2], max: [1, 1, 0] } }];
  assert.equal(nearestHit([0, 0, 10], [0, 0, -1], mixed).index, 1);
});

test("点选的端到端一致性：反投影出来的射线确实打中视线正前方的实例", () => {
  // 相机在 (0,0,10)，一个盒子摆在 (0,0,0)。点屏幕正中必须选中它。
  const view = lookFromZ(10);
  const box = { bound: { min: [-1, -1, -1], max: [1, 1, 1] } };
  const ray = pixelRay(400, 300, RECT, view, FOV, ASPECT);
  const hit = nearestHit(ray.origin, ray.dir, [box]);
  assert.equal(hit.index, 0);
  // 相机在 z=10、盒子近面在 z=1，所以命中距离是 9。
  assert.ok(near(hit.t, 9), `期望 9，实际 ${hit.t}`);

  // 把相机再退远，t 必须跟着变大（相机在 z=20 → 距离 19）。
  const farRay = pixelRay(400, 300, RECT, lookFromZ(20), FOV, ASPECT);
  assert.ok(near(nearestHit(farRay.origin, farRay.dir, [box]).t, 19), "近面在 z=1，相机在 z=20");
});

test("点选：视线外的地方必须返回 null，不是「总有一个最近的」", () => {
  const view = lookFromZ(10);
  const box = { bound: { min: [-1, -1, -1], max: [1, 1, 1] } };
  // 相机在 z=10 看 -Z，盒子在原点：屏幕右上角（800,0）的射线会从盒子旁擦过去。
  const corner = pixelRay(800, 0, RECT, view, FOV, ASPECT);
  // 这条射线斜得足够远，在 z=0 平面上早就跑到 x/y 很大处了。
  const t0 = -corner.origin[2] / corner.dir[2];
  const p0 = corner.dir.map((d, i) => corner.origin[i] + d * t0);
  assert.ok(Math.abs(p0[0]) > 1 || Math.abs(p0[1]) > 1, `z=0 处应为 [${p0}]，落在盒外`);
  assert.equal(nearestHit(corner.origin, corner.dir, [box]), null);
});

// --------------------------------------------------------------------------
// 几何池合并 & 点选盒
// --------------------------------------------------------------------------

const meshDef = (path, vc, ic) => ({
  path, vertexCount: vc, indexCount: ic, hasNormals: true, hasUvs: false,
  bboxMin: [0, 0, 0], bboxMax: [1, 1, 1], buffer: "",
});

test("独立壳：同一个网格路径出现两次只留一份几何，两份实例都指过去", () => {
  const { unique, toUnique } = collapseMeshes([meshDef("a.mesh", 10, 30), meshDef("b.mesh", 20, 60), meshDef("a.mesh", 10, 30)]);
  assert.equal(unique.length, 2);
  assert.deepEqual([...toUnique], [0, 1, 0]);
  assert.equal(unique[0].path, "a.mesh");
});

test("独立壳：路径相同但顶点数对不上 → 各自留一份，不错并", () => {
  // 同名不同内容如果被并成一份，表现是"某些实例画成另一个网格的形状"——
  // 屏幕上只是形状怪，不报错，所以这里钉住"key 里必须含布局字段"。
  const { unique, toUnique } = collapseMeshes([meshDef("a.mesh", 10, 30), meshDef("a.mesh", 11, 30), meshDef("a.mesh", 10, 33)]);
  assert.equal(unique.length, 3, "顶点数/索引数不同就不能共用缓冲");
  assert.deepEqual([...toUnique], [0, 1, 2]);
});

test("独立壳：路径相同、布局也相同才算同一份", () => {
  const { unique, toUnique } = collapseMeshes([meshDef("a.mesh", 10, 30), meshDef("a.mesh", 10, 30)]);
  assert.equal(unique.length, 1);
  assert.deepEqual([...toUnique], [0, 0]);
});

test("独立壳：都没路径时按顶点数认，不把两个空路径全并成一个", () => {
  const { unique } = collapseMeshes([meshDef("", 10, 30), meshDef("", 20, 60)]);
  assert.equal(unique.length, 2);
});

test("独立壳：全不相同就一个都别合", () => {
  const { unique, toUnique } = collapseMeshes([meshDef("a", 1, 3), meshDef("b", 1, 3), meshDef("c", 1, 3)]);
  assert.equal(unique.length, 3);
  assert.deepEqual([...toUnique], [0, 1, 2]);
});

/// 造一份 expandInstances 风格的实例表（测试里不经过 WebGL，所以手工拼）。
function fakeInst(list) {
  const inst = expandInstances(list.map((x) => ({ meshIndex: x.meshIndex, matrix: x.matrix })), 4);
  return inst;
}

test("独立壳：instancedBounds 拿池里的盒子 × 实例矩阵算出世界盒", () => {
  const pool = [{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }];
  const bounds = instancedBounds(pool, fakeInst([
    { meshIndex: 0, matrix: [...translate(0, 0, 0)] },
    { meshIndex: 0, matrix: [...translate(100, 0, 0)] },
  ]));
  assert.equal(bounds.min[0], -1);
  assert.equal(bounds.max[0], 101);
  assert.equal(bounds.size, 102);
});

test("独立壳：点选盒是覆盖该实例的外接立方体，中心对得上", () => {
  // 一个 2×2×2 的盒子挪到 (10,0,0)：外接立方体半棱长也是 1，正好贴合。
  const pool = [{ bboxMin: [-1, -1, -1], bboxMax: [1, 1, 1] }];
  const boxes = instancedPickBounds(pool, fakeInst([{ meshIndex: 0, matrix: [...translate(10, 0, 0)] }]));
  assert.equal(boxes.length, 1);
  assert.deepEqual(boxes[0].bound.min, [9, -1, -1]);
  assert.deepEqual(boxes[0].bound.max, [11, 1, 1]);
  // 并且它确实能被一条射线打中——点选盒不是算出来摆好看的。
  assert.ok(near(rayBox([10, 0, 50], [0, 0, -1], boxes[0].bound.min, boxes[0].bound.max), 49));
});

test("独立壳：被压扁的物件的外接盒不塌成 0（半棱长有下限）", () => {
  // 面片：局部盒 2×0×2。外接立方体取最长边 2，半棱长 1。
  const pool = [{ bboxMin: [-1, 0, -1], bboxMax: [1, 0, 1] }];
  const boxes = instancedPickBounds(pool, fakeInst([{ meshIndex: 0, matrix: [...identity()] }]));
  assert.equal(boxes[0].bound.max[1] - boxes[0].bound.min[1], 2);
});

// --------------------------------------------------------------------------
// 契约 6：着色器源码自身的一致性。WebGL 在 node 里开不了，编译期错误没有任何
// 运行时信号——2026-09-26 vUv 在顶点着色器里定义了两次、片元着色器用了却没声明，
// 所有 3D 预览当场全炸，错误文案还把锅甩给了「这台机器」。按文本钉死声明契约。
// --------------------------------------------------------------------------

test("着色器声明契约：varying/uniform 不许重复定义、不许未声明先用", () => {
  const src = readFileSync(new URL("../web/mesh-viewer.js", import.meta.url), "utf8");
  const grab = (name) => {
    const m = src.match(new RegExp(`const ${name} = \`([\\s\\S]*?)\`;`));
    assert.ok(m, `找不到着色器 ${name}`);
    return m[1];
  };
  const vs = grab("VS");
  const fsSrc = grab("FS");
  const count = (hay, needle) => hay.split(needle).length - 1;

  assert.equal(count(vs, "varying vec2 vUv;"), 1, "vUv 在顶点着色器里只许声明一次");
  for (const decl of ["varying vec2 vUv;", "uniform sampler2D uTex;", "uniform float uUseTex;"]) {
    assert.ok(fsSrc.includes(decl), `片元着色器缺声明：${decl}`);
  }
});

// --------------------------------------------------------------------------
// 小工具
// --------------------------------------------------------------------------

function norm(v) {
  const l = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / l, v[1] / l, v[2] / l];
}

/// 按行主序 3x3 变换一个向量（法线方向用，不含平移）。
function transformPoint3(n, v) {
  return [
    n[0] * v[0] + n[3] * v[1] + n[6] * v[2],
    n[1] * v[0] + n[4] * v[1] + n[7] * v[2],
    n[2] * v[0] + n[5] * v[1] + n[8] * v[2],
  ];
}
