// 没有业务知识的小工具：找元素、转义、格式化、摆筹码。
// 任何「资产 / 引用 / 证据」的语义都不该出现在这里。

export const el = (id) => document.getElementById(id);

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const num = (n) => Number(n ?? 0).toLocaleString("zh-CN");

export const pct = (part, whole) => (whole ? Math.round((part / whole) * 100) : 0);

// Tauri 把 Rust 侧的 Err(String) 包成 Error，"Error: " 前缀是噪音。
export const errText = (e) => String(e && e.message ? e.message : e).replace(/^Error:\s*/, "");

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/// 一排可点选的筹码。`count` 有值就带上数字。
/// data-value 是给 markChips 用的：选中态要能单独改，不必重建 DOM。
///
/// 默认最多摆 `cap` 颗：巨无霸组（实测一份组名下登记 838 份定义、1,642 份特效）
/// 全摆出来会把要看的表挤出屏幕——那是把「看不见」换了个地方，不是解决问题。
/// 当前选中的那颗一定摆进来，哪怕它排在 cap 之后。
export function chips(node, options, current, pick, cap = 24) {
  node.innerHTML = "";
  let shown = options.slice(0, cap);
  if (options.length > cap && current != null && !shown.some((o) => String(o.value) === String(current))) {
    const cur = options.find((o) => String(o.value) === String(current));
    if (cur) shown = shown.concat([cur]);
  }
  for (const opt of shown) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip";
    b.dataset.value = String(opt.value);
    b.innerHTML = `<span>${esc(opt.label)}</span>` + (opt.count === undefined ? "" : `<em>${num(opt.count)}</em>`);
    b.onclick = () => pick(opt.value);
    node.appendChild(b);
  }
  if (options.length > shown.length) {
    const more = document.createElement("span");
    more.className = "chip-more";
    more.textContent = `还有 ${options.length - shown.length} 项没列出（在「组成成员」里能看全）`;
    node.appendChild(more);
  }
  markChips(node, current);
}

/// 只把「哪一颗是选中的」同步到 DOM，一个节点都不重建。
/// 筹码区整块重建会把手指正下方那颗 chip 抽走——点了却像没反应。
export function markChips(node, current) {
  for (const b of node.children) b.classList.toggle("on", b.dataset.value === String(current));
}

/// 一行「标签 → 值」。值已经排好版，标签给排查的人看。
export const line = (k, v) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`;
