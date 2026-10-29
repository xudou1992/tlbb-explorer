// 地图列表行的小俯视脚印：一张 map_footprint 回包 → 一个小画布。
//
// 口径必须和主俯视图（TopDownView）完全一致——矩形同样来自 instanceRects 的
// 8 角投影、取景同样对准连片主体（topdownMath.mainClusterBounds）。列表是
// 用户"认图"的地方：缩略图里看到的形状和点进去看到的对不上，用户会以为
// 点错了图。所以这里不做任何自己的取景或简化，只把主视图的画法缩到 64×44：
// 不画格线、刻度、十字线和角标——那个尺寸下它们只剩噪声。
//
// 数据走 map_footprint（不是 map_scene）：同一套装配、回包逐字段一致、只是
// 网格不带顶点流，300 张图的列表逐张拉 map_scene 会把整个窗口冻住。

import * as tm from "./topdownMath.js";

/// 四周留白（CSS 像素）。主视图是 36，缩略图只要不贴边就行。
const PAD = 3;

/// 把一张 map_footprint 回包画进 canvas，返回 true=画出了脚印。
/// 返回 false = 这张图一条可画的摆位都没有（没物件 / 全是脏数据），
/// 调用方必须如实写「没物件」，不许留一块深色空画布假装在渲染。
export function drawThumb(canvas, payload) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  const dpr = window.devicePixelRatio || 1;
  const r = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.round(r.width));
  const h = Math.max(1, Math.round(r.height));
  const pw = Math.max(1, Math.round(w * dpr));
  const ph = Math.max(1, Math.round(h * dpr));
  if (canvas.width !== pw || canvas.height !== ph) {
    canvas.width = pw;
    canvas.height = ph;
  }

  const instances = (payload && payload.instances) || [];
  const { rects } = tm.instanceRects((payload && payload.meshes) || [], instances);
  if (!rects.length) return false;
  const cells = tm.occupiedCells(instances, (payload && payload.gridFiles) || []);
  const mainB = tm.mainClusterBounds(cells);
  const view = tm.fitView(mainB ? [mainB] : rects, w, h, PAD);
  if (!view) return false;

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.fillStyle = "#0e1417";
  ctx.fillRect(0, 0, w, h);
  const px = (wx) => (wx - view.cx) * view.scale + w / 2;
  const py = (wz) => (wz - view.cz) * view.scale + h / 2;
  // 缩略图上物件大多不足 1px：最小画 1px 点，物件不能凭空消失。
  for (const rc of rects) {
    const x0 = px(rc.x0), z0 = py(rc.z0);
    const x1 = px(rc.x1), z1 = py(rc.z1);
    const x = Math.min(x0, x1);
    const y = Math.min(z0, z1);
    const rw = Math.max(Math.abs(x1 - x0), 1);
    const rh = Math.max(Math.abs(z1 - z0), 1);
    if (x + rw < 0 || x > w || y + rh < 0 || y > h) continue;
    ctx.fillStyle = "rgba(113, 207, 173, 0.55)";
    ctx.fillRect(x, y, rw, rh);
  }
  return true;
}
