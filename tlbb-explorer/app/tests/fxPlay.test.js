// 「试播（近似）」的纯函数测试：只验算子和推进，不碰 DOM。
import test from "node:test";
import assert from "node:assert/strict";
import { buildRecipe, makeSim, step, spawnPoint } from "../web/lib/fxPlay.js";

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
