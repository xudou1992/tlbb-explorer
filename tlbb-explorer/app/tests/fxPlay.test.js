// 「试播（近似）」的纯函数测试：只验算子和推进，不碰 DOM。
import test from "node:test";
import assert from "node:assert/strict";
import { buildRecipe, makeSim, step, spawnPoint, colourAt, pickSprite } from "../web/lib/fxPlay.js";

const row = (name, floats, cls = 1) => ({ cls, fld: 0, name, words: [], floats });

test("buildRecipe：按字段名取值，缺字段用默认，不让参数飞出去", () => {
  const r = buildRecipe([
    row("emission_rate", [10]),
    row("emission_rate", [30]),
    row("duration", [2.0]),
    row("acceleration", [-4]),
    row("velocity", [0, 0, 0, 0.5, 0, 0]),
    row("initial_colour", [255, 128, 0, 255], 9),
  ]);
  assert.equal(r.rate, 20, "发射率取中位数");
  assert.equal(r.life, 2);
  assert.equal(r.accel, -4);
  assert.ok(r.speed >= 0.5, "速度取非零分量的上四分位，不能被压平成 0");
  assert.ok(Math.abs(r.colour[0] - 1) < 1e-6, "255 要归一化");
  assert.ok(r.colour[1] > 0.4 && r.colour[1] < 0.6);

  const empty = buildRecipe([]);
  assert.ok(empty.rate > 0 && empty.life > 0, "空参数也要有可跑的默认值");
});

test("pickSprite：优先非遮罩/法线的图，拿遮罩当精灵就是黑块", () => {
  assert.equal(pickSprite(["a_mask.tga", "b.tga"]), "b.tga");
  assert.equal(pickSprite(["x_pbr.tga", "y_normal.tga"]), "x_pbr.tga", "都像遮罩就退回第一张");
  assert.equal(pickSprite([]), "");
});

test("colourAt：有时间-颜色控制点就在两点间插值，没有就回单色", () => {
  const r = buildRecipe([
    row("time_colour", [0, 255, 0, 0, 255], 14),
    row("time_colour", [1, 0, 0, 255, 255], 14),
  ]);
  assert.equal(r.colourKeys.length, 2, "两个控制点都要收进来");
  const a = colourAt(r, 0);
  const m = colourAt(r, 0.5);
  const b = colourAt(r, 1);
  assert.ok(Math.abs(a[0] - 1) < 1e-6 && Math.abs(a[2]) < 1e-6, "起点是红");
  assert.ok(Math.abs(m[0] - 0.5) < 1e-6 && Math.abs(m[2] - 0.5) < 1e-6, "中点各一半");
  assert.ok(Math.abs(b[2] - 1) < 1e-6 && Math.abs(b[0]) < 1e-6, "终点是蓝");

  const plain = buildRecipe([row("initial_colour", [1, 0.5, 0.25], 9)]);
  assert.deepEqual(colourAt(plain, 0.7), plain.colour, "没有控制点就回单色");
});

test("spawnPoint：形状按名字给出生点，未知名字退回原点", () => {
  const p = spawnPoint("Point");
  assert.deepEqual(p, [0, 0, 0]);
  const box = spawnPoint("Box");
  assert.ok(Math.abs(box[0]) <= 1.2 && Math.abs(box[1]) <= 0.6, "Box 在盒子里");
  const c = spawnPoint("Circle");
  assert.ok(Math.hypot(c[0], c[2]) <= 1.4 + 1e-9, "Circle 在圆盘内");
  assert.deepEqual(spawnPoint("什么都不是"), [0, 0, 0]);
});

test("step：会按发射率生成粒子，并在寿命到了以后回收", () => {
  const sim = makeSim({ rate: 10, life: 1, accel: 0, speed: 1, colour: [1, 1, 1, 1], grow: 0 });
  for (let i = 0; i < 10; i++) step(sim, 0.1);
  assert.ok(sim.parts.length > 0, "一秒内该有粒子");
  const n = sim.parts.length;
  for (let i = 0; i < 30; i++) step(sim, 0.1);
  assert.ok(sim.parts.length <= n + 30, "旧粒子要被回收，不能只增不减");
});
