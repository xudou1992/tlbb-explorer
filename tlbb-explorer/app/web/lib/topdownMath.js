// 俯视量测视图的纯数学：格子归属、格子聚簇、取景、坐标换算、2D 点选。
//
// 和 instanceMath.js 同一层——不碰 DOM、不碰 canvas，node --test 钉得住。
// 为什么单独开文件而不是塞进 instanceMath：那一篇钉的是**矩阵**约定（GL 布局、
// 平移在 [12..14]），这一篇钉的是**俯视图**的约定（格子边长、格子名与坐标的
// 对应、像素↔世界换算），混在一起会让"哪段代码守哪条契约"变模糊。
//
// 两条**这一篇自己的实测事实**，所有阈值都从它们来，不许拍脑袋改：
//
//   1) 格子边长 = 32 世界单位。判据：全库实测（4 张图 7,464 条摆位记录）
//      floor(x/32)、floor(z/32) 与格子文件名里那对下标 **100% 吻合**，
//      一条例外都没有。
//
//   2)「野摆位」不存在。此前怀疑 wanjiegu_002 那棵 (-54922, -84617) 的榕树是
//      客户端摆错，实测它正好落在自己格子文件 `1_-1717_-2645.scene` 的
//      32×32 范围内——坐标系自洽，是**孤悬远处的合法格子**。所以俯视图不做
//      任何"剔除野点"，只做**取景对准连片主体**（见 clustersOf），孤悬格子
//      如实画、如实计数，缩放出去就能看到。

import { transformPoint } from "./instanceMath.js";

/// 格子边长（世界单位）。来源见文件头实测事实 1。
export const CELL = 32;

/// 格子文件名 `<任意>_<gx>_<gz>.scene` → [gx, gz]。认不出返回 null。
///
/// 名字是客户端起的，不认就说 null——上层会退回 floor(坐标/32) 兜底，
/// 而不是把不认识的名字硬猜成 (0,0)。
export function parseGridName(name) {
  if (typeof name !== "string") return null;
  const m = name.match(/_(-?\d+)_(-?\d+)\.scene$/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2])];
}

/// 一条摆位记录属于哪个格子：先信格子文件名（客户端亲笔写的），名字认不出
/// 再退回 floor(坐标/32)（实测两者 100% 一致，兜底只是防名字格式变体）。
/// 两条路都走不通（坐标还是 NaN）返回 null，调用方跳过这一条。
export function cellOf(instance, gridFiles) {
  if (!instance) return null;
  const named = parseGridName(gridFiles && gridFiles[instance.gridIndex]);
  if (named) return named;
  const x = instance.matrix && instance.matrix[12];
  const z = instance.matrix && instance.matrix[14];
  if (!Number.isFinite(x) || !Number.isFinite(z)) return null;
  return [Math.floor(x / CELL), Math.floor(z / CELL)];
}

/// 占用格子表：[{ gx, gz, count }]，按首次出现顺序。count 是该格子的摆位条数。
/// 格子归属算不出来的实例不进表（它们的矩形照常能画，只是不参与聚簇）。
export function occupiedCells(instances, gridFiles) {
  const at = new Map();
  const out = [];
  for (const inst of instances || []) {
    const c = cellOf(inst, gridFiles);
    if (!c) continue;
    const key = c[0] + "," + c[1];
    let cell = at.get(key);
    if (!cell) {
      cell = { gx: c[0], gz: c[1], count: 0 };
      at.set(key, cell);
      out.push(cell);
    }
    cell.count++;
  }
  return out;
}

/// 把占用格子按 8 邻域连成片，返回簇的数组、按格子数降序。
///
/// 用途：取景对准**连片主体**。wanjiegu_002 的 64 个占用格子实测是
/// 「63 连片 + 1 个孤悬 5.5 万单位外」；如果按全体包围盒取景，主体会被
/// 压成屏幕上一个点。簇不是"对错"，是"哪片是主体"的判定——孤悬格子
/// 一张不少地画，只是不参与定取景。
///
/// 同尺寸并列时按 occupiedCells 的首现顺序取先者，结果确定。
export function clustersOf(cells) {
  const at = new Map();
  for (const c of cells) at.set(c.gx + "," + c.gz, c);
  const seen = new Set();
  const clusters = [];
  for (const c of cells) {
    const key = c.gx + "," + c.gz;
    if (seen.has(key)) continue;
    const stack = [c];
    seen.add(key);
    const cl = [];
    while (stack.length) {
      const cur = stack.pop();
      cl.push(cur);
      for (let dx = -1; dx <= 1; dx++) {
        for (let dz = -1; dz <= 1; dz++) {
          if (!dx && !dz) continue;
          const nk = (cur.gx + dx) + "," + (cur.gz + dz);
          if (at.has(nk) && !seen.has(nk)) {
            seen.add(nk);
            stack.push(at.get(nk));
          }
        }
      }
    }
    clusters.push(cl);
  }
  clusters.sort((a, b) => b.length - a.length);
  return clusters;
}

/// 连片主体（格子数最多的簇）的世界范围矩形；没有可算的格子返回 null。
///
/// 主俯视图（TopDownView）和地图列表的缩略图共用它定取景：两张图必须是
/// 同一个口径画出来的，否则列表里看到的形状和点进去看到的对不上，用户
/// 会以为点错了图。
export function mainClusterBounds(cells) {
  const clusters = clustersOf(cells || []);
  const main = clusters.length ? clusters[0] : [];
  if (!main.length) return null;
  let gx0 = Infinity, gx1 = -Infinity, gz0 = Infinity, gz1 = -Infinity;
  for (const c of main) {
    if (c.gx < gx0) gx0 = c.gx;
    if (c.gx > gx1) gx1 = c.gx;
    if (c.gz < gz0) gz0 = c.gz;
    if (c.gz > gz1) gz1 = c.gz;
  }
  return { x0: gx0 * CELL, z0: gz0 * CELL, x1: (gx1 + 1) * CELL, z1: (gz1 + 1) * CELL };
}

/// 每条摆位记录在**世界 XZ 平面**上的占用矩形。
///
/// 为什么用 8 角而不是只变换 min/max：实例矩阵可能带旋转，旋转后的盒子
/// 在 XZ 上的投影必须按 8 个角重新求（和 3D 世界包围盒同一条教训）。
/// 返回 { rects: [{ x0, z0, x1, z1, meshIndex, gridIndex, recordIndex }], skipped }：
/// 网格没有包围盒 / meshIndex 越界 / 坐标出 NaN 的条目进 skipped（计数，
/// 让界面说「N 条画不出」），绝不让一条脏数据把整个 min/max 拖成 NaN。
export function instanceRects(meshes, instances) {
  const rects = [];
  let skipped = 0;
  for (const inst of instances || []) {
    const mesh = inst && meshes[inst.meshIndex];
    const m = inst && inst.matrix;
    if (!mesh || !m || m.length !== 16 || !mesh.bboxMin || !mesh.bboxMax) {
      skipped++;
      continue;
    }
    let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
    let ok = true;
    for (let i = 0; i < 8 && ok; i++) {
      const p = [
        i & 1 ? mesh.bboxMax[0] : mesh.bboxMin[0],
        i & 2 ? mesh.bboxMax[1] : mesh.bboxMin[1],
        i & 4 ? mesh.bboxMax[2] : mesh.bboxMin[2],
      ];
      const w = transformPoint(m, p);
      if (!Number.isFinite(w[0]) || !Number.isFinite(w[2])) {
        ok = false;
        break;
      }
      if (w[0] < x0) x0 = w[0];
      if (w[0] > x1) x1 = w[0];
      if (w[2] < z0) z0 = w[2];
      if (w[2] > z1) z1 = w[2];
    }
    if (!ok) {
      skipped++;
      continue;
    }
    rects.push({
      x0, z0, x1, z1,
      meshIndex: inst.meshIndex,
      gridIndex: inst.gridIndex,
      recordIndex: inst.recordIndex,
    });
  }
  return { rects, skipped };
}

/// 取景：把一组矩形等比装进 w×h 的画布，四周留 padding 像素。
///
/// 返回 { cx, cz, scale }（scale = 每世界单位多少 CSS 像素），矩形为空返回
/// null——和 worldBounds 返回 null 同一条纪律：没有内容就没有取景，
/// 不编一个 (0,0,1) 出来，那会让空图看起来像"有东西在原点"。
export function fitView(rects, w, h, padding) {
  if (!rects || !rects.length) return null;
  const pad = Math.max(0, Math.min(padding, w / 3, h / 3));
  let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  for (const r of rects) {
    if (r.x0 < x0) x0 = r.x0;
    if (r.x1 > x1) x1 = r.x1;
    if (r.z0 < z0) z0 = r.z0;
    if (r.z1 > z1) z1 = r.z1;
  }
  const dx = x1 - x0;
  const dz = z1 - z0;
  const availW = w - 2 * pad;
  const availH = h - 2 * pad;
  if (availW <= 0 || availH <= 0) return null;
  // 等比：两个方向都装得下的最大 scale。
  let scale = Math.min(availW / Math.max(dx, 1e-6), availH / Math.max(dz, 1e-6));
  if (dx < 1e-6 && dz < 1e-6) {
    // 全部叠成一个点（dx=dz=0）时上面的式子会冲到 Infinity：初始取景退回
    // 「4 个格子铺满宽」。只在这一个退化分支设上限——正常内容（哪怕只有
    // 半个格子大）都按自己的包围盒铺满画布，量测小图才看得清。
    scale = availW / (4 * CELL);
  }
  if (!Number.isFinite(scale) || scale <= 0) return null;
  return { cx: (x0 + x1) / 2, cz: (z0 + z1) / 2, scale };
}

/// 世界 → 画布像素（CSS 像素；渲染器自己处理 devicePixelRatio）。
/// 约定：世界 x → 屏幕右，世界 z → 屏幕下。**哪边是北未证**（M1 待比对），
/// 界面文案不许说"上北下南"。
export function pixelOf(wx, wz, view, w, h) {
  return [(wx - view.cx) * view.scale + w / 2, (wz - view.cz) * view.scale + h / 2];
}

/// 画布像素 → 世界（fitView/pixelOf 的逆变换）。量测读数全靠它，错了读数
/// 就是系统性偏移——不报错，只会每个数都错。
export function worldOfPixel(px, py, view, w, h) {
  return [(px - w / 2) / view.scale + view.cx, (py - h / 2) / view.scale + view.cz];
}

/// 2D 点选：返回**包含该世界点**的矩形里面积最小那个的下标，没有返回 null。
///
/// 面积最小优先，因为相邻物件俯视矩形常互相压着（房子套着院子），小的那个
/// 更可能是用户指着的那件。这不是三角形级精确——点在两树之间的空地上仍会
/// 误中其一，误差量级 = 矩形比真实轮廓大多少，对"点一件、查它的来历"够用。
export function pickRect(rects, wx, wz) {
  let best = -1;
  let bestArea = Infinity;
  for (let i = 0; i < rects.length; i++) {
    const r = rects[i];
    if (wx < r.x0 || wx > r.x1 || wz < r.z0 || wz > r.z1) continue;
    const area = (r.x1 - r.x0) * (r.z1 - r.z0);
    if (area < bestArea) {
      bestArea = area;
      best = i;
    }
  }
  return best < 0 ? null : best;
}
