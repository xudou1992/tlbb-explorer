// 特效「试播」——按 .pu 里读到的参数做一个**近似**粒子模拟。
//
// 诚实边界（界面上同屏要写）：
//   * 参数值的单位/曲线含义没解出来，这里的换算全是按读数的中位数取的默认量；
//   * 发射器只做「点发射」，更新器只做颜色/尺寸随年龄变化；
//   * 这是看参数的示意，**不是客户端效果**，不能当验收依据。
//
// 另外这层是纯函数 + 一个画布，测试环境（node）不碰 DOM。

/// 从 rep.params 里按字段名取值（同名字段取中位数），拿不到就回默认。
export function buildRecipe(params, emitter) {
  const byName = new Map();
  for (const p of params || []) {
    if (!p.name) continue;
    if (!byName.has(p.name)) byName.set(p.name, []);
    byName.get(p.name).push(p);
  }
  const nums = (k) => {
    const rows = byName.get(k) || [];
    const out = [];
    for (const r of rows) for (const f of r.floats || []) if (Number.isFinite(f)) out.push(f);
    return out;
  };
  const med = (arr, dflt) => {
    if (!arr.length) return dflt;
    const s = [...arr].sort((a, b) => a - b);
    const mid = s.length >> 1;
    return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
  };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  const rate = clamp(med(nums("emission_rate"), 12), 1, 80);
  const life = clamp(med(nums("duration"), 1.2), 0.2, 8);
  const accel = clamp(med(nums("acceleration"), -2), -40, 40);
  // velocity 多半是三分量向量，压平后取绝对值众数的上四分位，避免被 0 拖平
  const velRaw = nums("velocity").map(Math.abs).filter((x) => x > 1e-6);
  const speed = clamp(velRaw.length ? velRaw.sort((a, b) => a - b)[Math.floor(velRaw.length * 0.75)] : 6, 0.5, 60);

  // 颜色：优先 initial_colour；三个数就补 alpha=1，四个数直接用
  const col = nums("initial_colour");
  let colour = [0.9, 0.75, 0.45, 1];
  if (col.length >= 3) {
    const k = Math.max(...col.slice(0, 4)) > 1.5 ? 255 : 1;
    colour = [col[0] / k, col[1] / k, col[2] / k, (col[3] ?? k) / k];
  }
  // 尺寸增量（若有）：按像素近似
  const inc = nums("min_increment").concat(nums("max_increment"));
  const grow = inc.length ? clamp(med(inc, 0) / 100, -0.5, 2) : 0;

  // 发射器形状：只按名字近似。形状的尺寸参数没读到（各字段单位未定），
  // 这里用固定量级——界面上必须标明「形状是近似」。
  const shape = ["Point", "Box", "Circle", "Cylinder", "Jet", "Polar", "ring", "Line"]
    .find((x) => String(emitter || "").toLowerCase() === x.toLowerCase()) || "Point";
  return { rate, life, accel, speed, colour, grow, shape };
}

/// 发射器的近似出生点（形状按名字，尺寸固定量级——真尺寸参数没解出来）。
export function spawnPoint(shape) {
  const rnd = (a, b) => a + Math.random() * (b - a);
  switch (shape) {
    case "Box":
      return [rnd(-1.2, 1.2), rnd(-0.6, 0.6), rnd(-1.2, 1.2)];
    case "Circle": {
      const t = Math.random() * Math.PI * 2;
      const r = Math.sqrt(Math.random()) * 1.4;
      return [Math.cos(t) * r, 0, Math.sin(t) * r];
    }
    case "Cylinder": {
      const t = Math.random() * Math.PI * 2;
      return [Math.cos(t) * 1.2, rnd(-1, 1), Math.sin(t) * 1.2];
    }
    case "Jet":
      return [rnd(-0.25, 0.25), 0, rnd(-0.25, 0.25)];
    case "Polar": {
      const t = Math.random() * Math.PI * 2;
      return [Math.cos(t) * 1.2, rnd(-0.3, 0.3), Math.sin(t) * 1.2];
    }
    case "ring": {
      const t = Math.random() * Math.PI * 2;
      return [Math.cos(t) * 1.3, rnd(-0.1, 0.1), Math.sin(t) * 1.3];
    }
    case "Line":
      return [rnd(-1.4, 1.4), 0, 0];
    default:
      return [0, 0, 0];
  }
}

/// 推进一帧：spawn 直到配额，积分速度/重力，回收过期粒子。
export function step(sim, dt) {
  const { recipe } = sim;
  sim.acc += dt * recipe.rate;
  while (sim.acc >= 1 && sim.parts.length < 240) {
    sim.acc -= 1;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const sp = recipe.speed * (0.6 + Math.random() * 0.8);
    const [ox, oy, oz] = spawnPoint(recipe.shape);
    sim.parts.push({
      x: ox, y: oy, z: oz,
      vx: Math.sin(phi) * Math.cos(theta) * sp,
      vy: Math.cos(phi) * sp,
      vz: Math.sin(phi) * Math.sin(theta) * sp,
      age: 0,
      life: recipe.life * (0.7 + Math.random() * 0.6),
      seed: Math.random(),
    });
  }
  for (const p of sim.parts) {
    p.age += dt;
    p.vy += recipe.accel * dt;
    p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
  }
  sim.parts = sim.parts.filter((p) => p.age < p.life);
  return sim;
}

export function makeSim(recipe) {
  return { recipe, parts: [], acc: 0, t: 0 };
}

/// 把粒子画到 2D 画布：简单透视投影 + 叠加混合（lighter），不是客户端渲染。
export function draw(ctx, sim, w, h, texture) {
  // 深色底：粒子用叠加混合，白底上什么都看不见。
  ctx.globalCompositeOperation = "source-over";
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#0b0d10";
  ctx.fillRect(0, 0, w, h);
  ctx.globalCompositeOperation = "lighter";
  const { recipe } = sim;
  const f = w * 1.8;
  for (const p of sim.parts) {
    const z = p.z + 3.5;
    if (z <= 0.2) continue;
    const sx = w / 2 + (p.x * f) / z;
    const sy = h / 2 - (p.y * f) / z;
    const k = p.age / p.life;
    const a = Math.max(0, 1 - k);
    const size = Math.max(3, (26 * (1 + recipe.grow * k)) / z);
    ctx.globalAlpha = a * 0.9;
    if (texture && texture.width > 0) {
      ctx.drawImage(texture, sx - size / 2, sy - size / 2, size, size);
    } else {
      ctx.fillStyle = `rgba(${Math.round(recipe.colour[0] * 255)},${Math.round(recipe.colour[1] * 255)},${Math.round(recipe.colour[2] * 255)},1)`;
      ctx.beginPath();
      ctx.arc(sx, sy, size / 2, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = "source-over";
}
