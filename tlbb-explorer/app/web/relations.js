// 引用关系网（整屏浮层）：把一条资产的引用链铺成一张横向分层的图。
//
// 这一屏只回答一个问题：这条资产往两边伸出去的手，有多少真握上了。
// 所有节点和边都来自 asset_inspect（成员 + mdl 部件 + 材质槽），
// 一条边只在「客户端原文里真的写了这个名字」时才画——命名相似不算引用。
//
// 与「库状态」「地图」同一形状：整屏浮层，看完原路返回。

import { el, esc, num } from "./ui.js";
import { state } from "./state.js";

const ROLE_COLOR = {
  模型: "#0d8f79",
  网格: "#3b7fd4",
  材质: "#8a6bd1",
  贴图: "#c07a12",
  骨骼: "#5d6f6a",
  动画: "#d8483f",
  着色器: "#2f9e8f",
  父材质: "#8a6bd1",
};

function colorOf(role) {
  const key = Object.keys(ROLE_COLOR).find((k) => String(role).includes(k));
  return key ? ROLE_COLOR[key] : "#7d8c88";
}

/// 把回包整理成 { columns: [[node…]…] }，每列一个深度。
/// 中心是当前资产；左边放「谁定义了我」（模型定义），右边放「我引用了谁」。
function buildGraph(insp) {
  const center = { id: "self", label: insp.stem || insp.what || "当前资产", role: "资产", hit: true, center: true };
  const columns = [[], [center], []];
  if (insp.mdl) {
    columns[0].push({
      id: "mdl",
      label: insp.mdl.name || "模型定义",
      role: "模型",
      hit: true,
      sub: insp.mdl.baseDir || "",
    });
  }
  const push = (col, node) => columns[col].push(node);
  for (const m of insp.members || []) {
    const role = m.roleZh || m.role;
    if (role === "模型" && insp.mdl) continue; // 别把同一个模型定义画两遍
    push(2, {
      id: `m:${m.name}`,
      label: m.name,
      role,
      hit: Boolean(m.resolved || m.path),
      sub: m.path || "",
    });
  }
  for (const b of (insp.mdl && insp.mdl.bodies) || []) {
    for (const s of b.textureSlots || []) {
      const id = `t:${s.name}`;
      if (columns[2].some((n) => n.id === id)) continue;
      push(2, { id, label: s.name, role: s.role || "贴图", hit: Boolean(s.resolved), sub: s.path || "" });
    }
  }
  return columns;
}

function nodeSvg(n, x, y, w, h) {
  const fill = n.center ? "#0d8f79" : n.hit ? "#ffffff" : "#fdeceb";
  const stroke = n.center ? "#0d8f79" : n.hit ? "#cfd8d5" : "#f2c0bb";
  const tx = n.center ? "#ffffff" : "#16211e";
  const dot = n.center ? "" : `<circle cx="${x + 10}" cy="${y + h / 2}" r="3.5" fill="${n.hit ? "#0d8f79" : "#d8483f"}"/>`;
  const label = String(n.label || "");
  const shown = label.length > 20 ? label.slice(0, 19) + "…" : label;
  return `<g>
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="${fill}" stroke="${stroke}" stroke-width="1.2"/>
    ${dot}
    <text x="${x + (n.center ? w / 2 : 20)}" y="${y + 17}" text-anchor="${n.center ? "middle" : "start"}"
      fill="${tx}" font-size="11.5" font-weight="600">${esc(shown)}</text>
    ${n.sub ? `<text x="${x + (n.center ? w / 2 : 20)}" y="${y + 31}" text-anchor="${n.center ? "middle" : "start"}" fill="${n.hit ? "#8c9c97" : "#c2726c"}" font-size="10">${esc(String(n.sub).slice(0, 34))}</text>` : ""}
    ${n.role && !n.center ? `<text x="${x + w - 8}" y="${y + 17}" text-anchor="end" fill="${colorOf(n.role)}" font-size="10">${esc(n.role)}</text>` : ""}
  </g>`;
}

function renderInto(host, insp) {
  const cols = buildGraph(insp);
  const NODE_W = 208;
  const NODE_H = 44;
  const GAP = 14;
  const COL_GAP = 96;
  const pad = 24;
  const maxRows = Math.max(...cols.map((c) => c.length), 1);
  const colH = maxRows * (NODE_H + GAP) - GAP;
  const height = colH + pad * 2 + 44;
  const width = pad * 2 + cols.length * NODE_W + (cols.length - 1) * COL_GAP;
  const pos = new Map();
  const parts = [];
  cols.forEach((nodes, ci) => {
    const x = pad + ci * (NODE_W + COL_GAP);
    const startY = pad + 44 + (colH - (nodes.length * (NODE_H + GAP) - GAP)) / 2;
    nodes.forEach((n, ri) => {
      const y = startY + ri * (NODE_H + GAP);
      pos.set(n.id, { x, y, w: NODE_W, h: NODE_H, n });
    });
  });
  // 边：中心列 → 右列、左列 → 中心列
  const edges = [];
  const selfPos = pos.get("self");
  if (selfPos) {
    for (const n of cols[2]) {
      const p = pos.get(n.id);
      if (!p) continue;
      edges.push(
        `<path d="M${selfPos.x + NODE_W} ${selfPos.y + NODE_H / 2} C ${selfPos.x + NODE_W + 44} ${selfPos.y + NODE_H / 2}, ${p.x - 44} ${p.y + NODE_H / 2}, ${p.x} ${p.y + NODE_H / 2}"
          fill="none" stroke="${n.hit ? "#b6ded6" : "#efb7b1"}" stroke-width="1.4"/>`,
      );
    }
    const m = pos.get("mdl");
    if (m) {
      edges.push(
        `<path d="M${m.x + NODE_W} ${m.y + NODE_H / 2} C ${m.x + NODE_W + 40} ${m.y + NODE_H / 2}, ${selfPos.x - 40} ${selfPos.y + NODE_H / 2}, ${selfPos.x} ${selfPos.y + NODE_H / 2}"
          fill="none" stroke="#b6ded6" stroke-width="1.4"/>`,
      );
    }
  }
  const header = `<text x="${pad}" y="${pad + 14}" fill="#5d6f6a" font-size="11">组成成员与材质槽 · 空心=能对上文件 实心红=客户端里没有</text>`;
  cols.forEach((nodes, i) => {
    const x = pad + i * (NODE_W + COL_GAP);
    parts.push(
      `<text x="${x}" y="${pad + 34}" fill="#8c9c97" font-size="10.5">${["定义它的", "这条资产", "它用到的"][i] || ""} · ${nodes.length}</text>`,
    );
  });
  for (const n of cols.flat()) {
    const p = pos.get(n.id);
    if (p) parts.push(nodeSvg(n, p.x, p.y, NODE_W, NODE_H));
  }
  host.innerHTML = `<svg viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" role="img" aria-label="引用关系网">${header}${edges.join("")}${parts.join("")}</svg>`;
}

// ---- 浮层开关 ----

function infoHtml(insp) {
  const missing = insp.missing || [];
  const rows = [
    ["资产名称", insp.stem || "—"],
    ["类型", insp.what || "—"],
    ["文件数", num(insp.parts)],
    ["缺失项", missing.length ? `${missing.length} 个` : "无"],
  ];
  return `<h3 class="side-h">这一屏在看什么</h3>
    <dl class="kv">${rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>
    <h3 class="side-h gap">缺失明细 <em>${missing.length ? num(missing.length) : ""}</em></h3>
    <ul class="lines">${
      missing.length
        ? missing.map((g) => `<li class="miss">${esc(g)}</li>`).join("")
        : `<li class="ok">没有发现明显缺失</li>`
    }</ul>`;
}

let lastInsp = null;

/// 用当前选中的资产铺满关系网。没有选中就问用户要一条。
export function renderRelations(insp) {
  const banner = el("relBanner");
  const host = el("relStage");
  const info = el("relInfo");
  if (!insp || !insp.found) {
    banner.innerHTML = `<b>关系网</b>先在上面的资产列表里选一条资产，这里就会铺开它的引用关系。`;
    host.innerHTML = `<p class="empty"><strong>还没有选中的资产</strong><span>左边列表点一条即可。</span></p>`;
    info.innerHTML = "";
    return;
  }
  lastInsp = insp;
  banner.innerHTML = `<b>关系网</b>${esc(insp.what || "")} · 节点数 ${num(
    (insp.members || []).length + ((insp.mdl && insp.mdl.bodies) || []).length,
  )} · 缺失 ${num((insp.missing || []).length)} 项`;
  renderInto(host, insp);
  info.innerHTML = infoHtml(insp);
}

export function openRelations() {
  el("relations").hidden = false;
  renderRelations(state.lastInspect || null);
}

export function closeRelations() {
  el("relations").hidden = true;
}

let wired = false;
export function initRelations() {
  if (wired) return;
  wired = true;
  el("closeRelations").addEventListener("click", closeRelations);
  el("openRelations").addEventListener("click", openRelations);
  el("btnRel").addEventListener("click", openRelations);
  el("profRelOpen").addEventListener("click", openRelations);
}
