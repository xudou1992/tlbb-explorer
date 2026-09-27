// 导出进度：吃后端 "exporting" 广播，在 exportReport 上方挂一行文字 + 细进度条。
// 整包导出可能十几万个文件、跑上几分钟，只留一行「正在导出…」看起来就像死了——
// 这行进度就是让用户看见后端还在一个个文件地啃，跑到哪儿了。
//
// 纪律：DOM 全部动态创建（index.html 不动）；样式走内联 style，颜色直接抄
// style.css :root 令牌的 hex 原值（#100e0b 墨底、#241f17 输入底、#e2aa5c 金、
// #b0a68e 灰、#f0e9d8 宣纸白），跟整套界面一个配色。
// 收尾事件（finished=true）到了先把自己收起、把最终统计写进 exportReport 兜底；
// 命令回包紧跟着也会写一份更全的（带 dest 和失败明细），那一份说了算。

import { el } from "./ui.js";

let installed = false;
let row = null; // 进度行：第一次收到事件才建，之后复用
let barText = null;
let barFill = null;

/// 在 app.js 初始化浏览视图时调用一次。没有桌面端（网页外壳）就没有事件
/// 总线，静默退出——进度是锦上添花，导出本身不该依赖它。
export function initExportProgress() {
  if (installed) return;
  const tauri = window.__TAURI__;
  if (!tauri || !tauri.event) return;
  installed = true;
  // 与 api.js 的 onReading 同款兜底：监听挂不上就当没有进度，别让错误冒出去。
  tauri.event.listen("exporting", (e) => {
    const p = e && e.payload ? e.payload : {};
    if (p.finished) finish(p);
    else tick(p);
  }).catch(() => {});
}

/// 第一次收到事件才把行插到 exportReport 上方；之后复用同一行。
function ensureRow() {
  if (row) return row;
  const report = el("exportReport");
  if (!report) return null;
  row = document.createElement("div");
  row.style.margin = "6px 0";
  barText = document.createElement("div");
  barText.style.cssText =
    "font-size:12px;color:#b0a68e;margin-bottom:4px;font-variant-numeric:tabular-nums;";
  const track = document.createElement("div");
  track.style.cssText = "height:3px;background:#241f17;border-radius:2px;overflow:hidden;";
  barFill = document.createElement("div");
  barFill.style.cssText =
    "height:100%;width:0;background:#e2aa5c;border-radius:2px;transition:width .15s linear;";
  track.appendChild(barFill);
  row.appendChild(barText);
  row.appendChild(track);
  report.parentNode.insertBefore(row, report);
  return row;
}

/// 进行中的一条广播：文字带分母口径（done / total），比例只画不念。
function tick(p) {
  const node = ensureRow();
  if (!node) return;
  node.hidden = false;
  const done = Number(p.done || 0);
  const total = Number(p.total || 0);
  const pct = total ? Math.round((done / total) * 100) : 0;
  barFill.style.width = pct + "%";
  barText.textContent =
    `正在导出 ${done.toLocaleString()} / ${total.toLocaleString()} · ` +
    `成功 ${Number(p.written || 0).toLocaleString()} · ` +
    `失败 ${Number(p.failed || 0).toLocaleString()}`;
}

/// 收尾包：收起进度行，最终统计写进 exportReport。
/// 正常时序是事件先到、命令回包后到——这里写的这份会被回包那份更全的盖掉；
/// 万一回包没来，用户至少能看到收尾数字，不会永远停在「正在导出…」。
function finish(p) {
  if (row) row.hidden = true;
  const report = el("exportReport");
  if (!report) return;
  const total = Number(p.total || 0);
  const written = Number(p.written || 0);
  const failed = Number(p.failed || 0);
  let text = `导出完成：${written.toLocaleString()} / ${total.toLocaleString()} 个文件成功`;
  if (failed) text += `，失败 ${failed.toLocaleString()} 个`;
  report.textContent = text;
}
