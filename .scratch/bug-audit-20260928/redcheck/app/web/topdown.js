// 俯视量测视图：正对世界 XZ 平面的 2D 画布，量的是「地面坐标」。
//
// 和 mesh-viewer.js 的分工：那边是 WebGL 灰模（立体、有明暗、能转），这边是
// 正交俯视（无透视、坐标可读、单击回查「哪个格子文件的第几条」）。两个视图
// 共用同一份 map_scene 回包——俯视不需要任何新 IPC，meshes 的包围盒 +
// instances 的矩阵就是全部输入。
//
// 格子归属、聚簇、取景、像素↔世界换算、2D 点选这些纯数学在 lib/topdownMath.js，
// 有 node --test 盯着；这里只管交互（拖动平移、滚轮缩放、单击点选、双击复位）
// 和把矩形画出来。
//
// 界面必须诚实交代的三件事：
//   * 格线间距 32 是实测常数，不是配置（topdownMath 文件头实测事实 1）；
//   * 哪边是北未证——画布角上只标「+x → +z ↓」，不说上北下南；
//   * 点选是矩形近似（pickRect 的说明），报的是「指到哪件」，不是像素级命中。

import * as tm from "./lib/topdownMath.js";

/// 取景四周留白（CSS 像素）。
const PAD = 36;

export class TopDownView {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    if (!this.ctx) throw new Error("这台机器开不了 2D 画布，看不到俯视图");

    this.rects = [];
    this.meshes = [];
    this.gridFiles = [];
    /// "gx,gz" → 格子文件名。悬停读数用它回答「这块地是哪个文件管的」。
    this.gridAt = new Map();
    this.view = null;
    this.home = null;
    this.cursor = null;
    this.picked = -1;
    this.drag = null;
    this.clusterInfo = null;
    this.skipped = 0;
    /// 回调：onhover({wx,wz,gx,gz,gridName}|null)、onpick({wx,wz,meshPath,gridName,recordNo}|null)。
    this.onhover = null;
    this.onpick = null;
    this.bindEvents();
  }

  /// payload 就是 map_scene 回包（meshes / instances / gridFiles）。
  /// 调用前画布必须已经显示：隐藏的 canvas 量不到尺寸，取景会按 1px 画布算。
  load(payload) {
    const meshes = (payload && payload.meshes) || [];
    const instances = (payload && payload.instances) || [];
    const gridFiles = (payload && payload.gridFiles) || [];
    this.meshes = meshes;
    this.gridFiles = gridFiles;
    this.gridAt = new Map();
    for (const g of gridFiles) {
      const c = tm.parseGridName(g);
      if (c) this.gridAt.set(c[0] + "," + c[1], g);
    }
    const { rects, skipped } = tm.instanceRects(meshes, instances);
    this.rects = rects;
    this.skipped = skipped;
    this.picked = -1;
    this.hover = null;
    this.syncViewport();

    // 取景对准连片主体（8 邻域格子数最多的簇）：孤悬 5 万单位外的合法格子
    // 不参与定取景——按全体包围盒取景会把主体压成屏幕上的一个点。主簇的
    // 格子范围就是取景范围；物件实测都躺在自己格子的 32×32 里，所以格子
    // 范围罩得住全簇物件（topdownMath 文件头实测事实 1、2）。
    const cells = tm.occupiedCells(instances, gridFiles);
    const clusters = tm.clustersOf(cells);
    this.clusterInfo = {
      cells: cells.length,
      clusters: clusters.length,
      mainCells: clusters.length ? clusters[0].length : 0,
    };
    // 取景口径在 topdownMath.mainClusterBounds：地图列表缩略图用同一个，
    // 两边的图必须长得一样（用户拿缩略图认图，点进去形状变了就是 bug）。
    const mainB = tm.mainClusterBounds(cells);
    const fitOn = mainB ? [mainB] : rects;
    this.home = tm.fitView(fitOn, this.size.w, this.size.h, PAD);
    this.view = this.home ? { ...this.home } : null;
    if (this.home) {
      // 缩放上下限：远到能看全图 16 倍的视野，近到一格铺满半个画布。
      this.minScale = this.home.scale / 16;
      this.maxScale = Math.max(this.home.scale * 1024, this.size.w / (2 * tm.CELL));
    }
    this.draw();
  }

  bindEvents() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (e) => {
      try {
        c.setPointerCapture(e.pointerId);
      } catch {
        // 捕获拿不到（指针已离开/合成事件）：平移少一个保险，点选不受影响。
      }
      this.drag = { x: e.clientX, y: e.clientY, moved: false };
    });
    c.addEventListener("pointermove", (e) => {
      if (!this.view) return;
      if (this.drag) {
        const dx = e.clientX - this.drag.x;
        const dy = e.clientY - this.drag.y;
        this.view.cx -= dx / this.view.scale;
        this.view.cz -= dy / this.view.scale;
        this.drag = { x: e.clientX, y: e.clientY, moved: this.drag.moved || Math.hypot(dx, dy) > 3 };
        this.draw();
      }
      this.trackHover(e);
    });
    c.addEventListener("pointerup", (e) => {
      if (!this.drag) return;
      const clicked = !this.drag.moved;
      this.drag = null;
      if (clicked) this.pick(e);
    });
    c.addEventListener("pointercancel", () => {
      this.drag = null;
    });
    c.addEventListener("pointerleave", () => {
      this.cursor = null;
      if (this.onhover) this.onhover(null);
      this.draw();
    });
    c.addEventListener(
      "wheel",
      (e) => {
        if (!this.view || !this.home) return;
        e.preventDefault();
        this.zoom(e, e.deltaY > 0 ? 1 / 1.25 : 1.25);
      },
      { passive: false },
    );
    c.addEventListener("dblclick", () => {
      if (!this.home) return;
      this.view = { ...this.home };
      this.draw();
    });
    window.addEventListener("resize", () => {
      // 隐藏的画布量不到尺寸，此时画会把位图缩成 1×1——切回来就是一块空白，
      // 而且没有任何报错（map.js 在切回时补画一帧，这里从源头别糟蹋位图）。
      if (this.canvas.hidden || !this.canvas.isConnected) return;
      if (this.view) this.draw();
    });
  }

  /// 指针下的世界坐标读数。缩放/平移后指针下的世界点变了，也走这里刷新。
  /// 拖动中调用方刚画过一帧，这里不再重画——一帧两画是白烧的全量重绘。
  trackHover(e) {
    if (!this.view) return;
    const r = this.canvas.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    this.cursor = { px, py };
    const [wx, wz] = tm.worldOfPixel(px, py, this.view, this.size.w, this.size.h);
    const gx = Math.floor(wx / tm.CELL);
    const gz = Math.floor(wz / tm.CELL);
    if (!this.drag) this.draw();
    if (this.onhover) {
      this.onhover({ wx, wz, gx, gz, gridName: this.gridAt.get(gx + "," + gz) || null });
    }
  }

  /// 缩放：保持指针下的那个世界点不跟着跑（否则缩放永远围着取景中心转，
  /// 想看的地方一下就滑出去了）。
  zoom(e, k) {
    const v = this.view;
    const ns = Math.min(this.maxScale || Infinity, Math.max(this.minScale || 0, v.scale * k));
    if (!(ns > 0) || ns === v.scale) return;
    const r = this.canvas.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    const [wx, wz] = tm.worldOfPixel(px, py, v, this.size.w, this.size.h);
    v.scale = ns;
    v.cx = wx - (px - this.size.w / 2) / ns;
    v.cz = wz - (py - this.size.h / 2) / ns;
    this.trackHover(e);
  }

  /// 单击点选：命中报「哪个格子文件的第几条 + 模型路径」，点空地报 null。
  /// 命中判定是 pickRect 的矩形近似——指到两件压着的矩形上会报小的那件。
  pick(e) {
    if (!this.view) return;
    const r = this.canvas.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    const [wx, wz] = tm.worldOfPixel(px, py, this.view, this.size.w, this.size.h);
    const hit = tm.pickRect(this.rects, wx, wz);
    this.picked = hit === null ? -1 : hit;
    this.draw();
    if (!this.onpick) return;
    if (hit === null) {
      this.onpick(null);
      return;
    }
    const rect = this.rects[hit];
    const mesh = this.meshes[rect.meshIndex];
    this.onpick({
      wx,
      wz,
      meshPath: (mesh && mesh.path) || "",
      gridName: this.gridFiles[rect.gridIndex] || "",
      recordNo: rect.recordIndex + 1,
    });
  }

  syncViewport() {
    const dpr = window.devicePixelRatio || 1;
    const r = this.canvas.getBoundingClientRect();
    this.size = { w: Math.max(1, Math.round(r.width)), h: Math.max(1, Math.round(r.height)) };
    const pw = Math.max(1, Math.round(this.size.w * dpr));
    const ph = Math.max(1, Math.round(this.size.h * dpr));
    if (this.canvas.width !== pw || this.canvas.height !== ph) {
      this.canvas.width = pw;
      this.canvas.height = ph;
    }
    this.dpr = dpr;
  }

  draw() {
    const ctx = this.ctx;
    this.syncViewport();
    const { w, h } = this.size;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    // 与 style.css 的 --stage 同源：canvas 吃不到 CSS 变量，两处一起改。
    ctx.fillStyle = "#14100b";
    ctx.fillRect(0, 0, w, h);
    if (!this.view) return;
    const v = this.view;
    const px = (wx) => (wx - v.cx) * v.scale + w / 2;
    const py = (wz) => (wz - v.cz) * v.scale + h / 2;
    const [wx0, wz0] = tm.worldOfPixel(0, 0, v, w, h);
    const [wx1, wz1] = tm.worldOfPixel(w, h, v, w, h);

    // 格线：间距 32 起步、按缩放成倍放稀，永远保持 14px 以上一条——
    // 一张图几千格时 32 一条会糊成纯色，量测也没法读。
    let step = tm.CELL;
    while (step * v.scale < 14) step *= 2;
    ctx.strokeStyle = "rgba(226, 235, 229, 0.06)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let x = Math.ceil(wx0 / step) * step; x <= wx1; x += step) {
      const sx = Math.round(px(x)) + 0.5;
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, h);
    }
    for (let z = Math.ceil(wz0 / step) * step; z <= wz1; z += step) {
      const sy = Math.round(py(z)) + 0.5;
      ctx.moveTo(0, sy);
      ctx.lineTo(w, sy);
    }
    ctx.stroke();

    // 坐标刻度：间距够宽才标（56px 一条），标的是世界坐标整数。
    if (step * v.scale >= 56) {
      ctx.fillStyle = "rgba(130, 145, 138, 0.85)";
      ctx.font = '10px "Cascadia Code", Consolas, monospace';
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      for (let x = Math.ceil(wx0 / step) * step; x <= wx1; x += step) {
        ctx.fillText(String(Math.round(x)), px(x) + 3, 3);
      }
      for (let z = Math.ceil(wz0 / step) * step; z <= wz1; z += step) {
        ctx.fillText(String(Math.round(z)), 3, py(z) + 3);
      }
    }

    // 世界原点准星：M1 坐标闭环要拿它和游戏里的位置对，必须一眼能找到，
    // 不能让它混在格线里。
    if (wx0 <= 0 && 0 <= wx1 && wz0 <= 0 && 0 <= wz1) {
      const ox = px(0);
      const oy = py(0);
      ctx.strokeStyle = "rgba(232, 170, 90, 0.65)";
      ctx.beginPath();
      ctx.moveTo(ox - 10, oy);
      ctx.lineTo(ox + 10, oy);
      ctx.moveTo(ox, oy - 10);
      ctx.lineTo(ox, oy + 10);
      ctx.stroke();
      ctx.fillStyle = "rgba(232, 170, 90, 0.85)";
      ctx.font = '10px "Cascadia Code", Consolas, monospace';
      ctx.textAlign = "left";
      ctx.textBaseline = "bottom";
      ctx.fillText("0,0", ox + 4, oy - 4);
    }

    // 摆位矩形：一件一矩形。缩得很远时宽度不足 2px 的画成 2px 点——
    // 物件不能凭空消失，否则「这格有没有摆东西」看不出来。
    for (let i = 0; i < this.rects.length; i++) {
      const r = this.rects[i];
      const x0 = px(r.x0), x1 = px(r.x1), y0 = py(r.z0), y1 = py(r.z1);
      if (x1 < 0 || x0 > w || y1 < 0 || y0 > h) continue;
      const on = i === this.picked;
      const rx = Math.min(x0, x1);
      const ry = Math.min(y0, y1);
      const rw = Math.max(Math.abs(x1 - x0), 2);
      const rh = Math.max(Math.abs(y1 - y0), 2);
      ctx.fillStyle = on ? "rgba(232, 170, 90, 0.2)" : "rgba(113, 207, 173, 0.12)";
      ctx.fillRect(rx, ry, rw, rh);
      if (rw >= 3 && rh >= 3) {
        ctx.strokeStyle = on ? "rgba(232, 170, 90, 0.95)" : "rgba(113, 207, 173, 0.5)";
        ctx.lineWidth = on ? 1.5 : 1;
        ctx.strokeRect(rx + 0.5, ry + 0.5, rw - 1, rh - 1);
      }
    }

    // 悬停十字线：量测视图的灵魂就是「这条线交在哪」。
    if (this.cursor) {
      ctx.strokeStyle = "rgba(237, 243, 238, 0.22)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(this.cursor.px + 0.5, 0);
      ctx.lineTo(this.cursor.px + 0.5, h);
      ctx.moveTo(0, this.cursor.py + 0.5);
      ctx.lineTo(w, this.cursor.py + 0.5);
      ctx.stroke();
    }

    // 角标：只说方向约定，不说南北（哪边是北未证）。
    ctx.fillStyle = "rgba(130, 145, 138, 0.9)";
    ctx.font = '10px "Cascadia Code", Consolas, monospace';
    ctx.textAlign = "right";
    ctx.textBaseline = "top";
    ctx.fillText("+x →   +z ↓", w - 8, 6);
  }
}
