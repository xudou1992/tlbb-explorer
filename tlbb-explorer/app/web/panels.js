// 右栏「资源概况 / 引用关系」+ 详情标签页 + 关系图谱 + 底部修复建议条。
//
// 这一层只做呈现：所有事实都来自 asset_inspect 回包，一个数字都不在这里算出来。
// 纪律与全库一致：没有的东西不画、不猜，用「缺 / 未命名」如实说。

import { el, esc, num, chips } from "./ui.js";
import { animSummary, changedRows, clampFrame, frameRows } from "./lib/animView.js";

/// 引用类别 → 配色 + 单字图标。颜色只作辅助，文字永远是主载体。
const ROLE_STYLE = {
  模型: ["#0d8f79", "模"],
  网格: ["#3b7fd4", "网"],
  材质: ["#8a6bd1", "材"],
  贴图: ["#c07a12", "贴"],
  骨骼: ["#5d6f6a", "骨"],
  动画: ["#d8483f", "动"],
  着色器: ["#2f9e8f", "着"],
  父材质: ["#8a6bd1", "父"],
  特效: ["#d8483f", "效"],
  场景: ["#0a6f5f", "场"],
  共享材质: ["#6b8fb5", "共"],
  Shader: ["#2f9e8f", "着"],
  FX: ["#d8483f", "效"],
};

function styleOf(role) {
  const key = Object.keys(ROLE_STYLE).find((k) => String(role).includes(k));
  return key ? ROLE_STYLE[key] : ["#7d8c88", "其"];
}

// ---- 标签页 ----

/// 把详情切到某个标签。按钮高亮与面板显隐同源，一起改，不会走散。
export function showTabPane(name) {
  for (const b of el("dTabs").querySelectorAll(".tab")) {
    b.classList.toggle("on", b.dataset.tab === name);
  }
  for (const p of document.querySelectorAll(".tabpane[data-pane]")) {
    p.hidden = p.dataset.pane !== name;
  }
  for (const cb of tabCbs) cb(name);
}

/// 标签页打开的通知。动作页要等用户真点开才去读关键帧
/// （一条动作约 0.6 秒，压在每次选资产的路径上不值）。
const tabCbs = [];
export function onTabOpen(cb) {
  tabCbs.push(cb);
}

let tabsWired = false;
export function initTabs() {
  if (tabsWired) return;
  tabsWired = true;
  el("dTabs").addEventListener("click", (e) => {
    const b = e.target.closest(".tab");
    if (b) showTabPane(b.dataset.tab);
  });
}

// ---- 骨架页：节点表 + 动作表 ----
//
// 一个数字都不在这里算：绑定位移、声明骨骼数、每条动作几骨几帧、会动的骨数，
// 全部来自 skeleton_view 回包。这里只负责摆出来，以及把「没解出来的」原话说清。

const fx = (v) => (Number.isFinite(v) ? v.toFixed(3) : "—");

export function clearSkeleton() {
  el("skelSum").textContent = "";
  el("skelTable").innerHTML = "";
  el("skelAnims").innerHTML = "";
  el("skelMissing").innerHTML = "";
  el("tabSkelCount").textContent = "";
  el("secSkelAnims").hidden = true;
}

export function paintSkeleton(v) {
  clearSkeleton();
  const nodes = v.nodes || [];
  const anims = v.animations || [];
  el("tabSkelCount").textContent = nodes.length ? String(nodes.length) : "";
  if (!nodes.length) {
    // 静态网格、解不出字节、组里没网格——后端给的原因原样转述，不换成「暂无数据」
    el("skelSum").textContent = v.note || "这一组里没有骨架数据。";
    return;
  }
  el("skelSum").textContent =
    `骨架来自 ${v.mesh}：文件头声明 ${v.declared} 根骨，这里认出 ${nodes.length} 根的绑定位移。`;
  el("skelTable").innerHTML =
    `<table class="hl-table"><thead><tr><th>骨名</th><th>X</th><th>Y</th><th>Z</th><th>缩放</th></tr></thead><tbody>${nodes
      .map(
        (n) =>
          `<tr><td>${esc(n.name)}</td><td class="n">${fx(n.pos[0])}</td><td class="n">${fx(
            n.pos[1],
          )}</td><td class="n">${fx(n.pos[2])}</td><td class="n">${fx(n.scale)}</td></tr>`,
      )
      .join("")}</tbody></table>`;
  if (anims.length) {
    el("secSkelAnims").hidden = false;
    el("skelAnims").innerHTML =
      `<table class="hl-table"><thead><tr><th>动作文件</th><th>骨骼</th><th>关键帧</th><th>会动的骨</th></tr></thead><tbody>${anims
        .map(
          (a) =>
            `<tr><td>${esc(a.file)}</td><td class="n">${a.bones}</td><td class="n">${
              a.frames
            }</td><td class="n">${a.moving}</td></tr>`,
        )
        .join("")}</tbody></table>`;
  }
  el("skelMissing").innerHTML = (v.missing || []).map((m) => `<li>${esc(m)}</li>`).join("");
}

// ---- 动作页：整条关键帧一次取回，游标本地切帧（不逐帧打 IPC） ----

export function clearAnimation() {
  el("animSum").textContent = "";
  el("animPick").innerHTML = "";
  el("animTable").innerHTML = "";
  el("animMissing").innerHTML = "";
  el("tabAnimCount").textContent = "";
}

/// 摆一帧。取哪几行、越界怎么夹、未命名的骨叫什么，全在 lib/animView.js（有测试盯着），
/// 这里只负责写 DOM。
export function paintAnimation(rep, frame, onlyChanged, onPick) {
  clearAnimation();
  if (!rep) return;
  el("tabAnimCount").textContent = rep.frames ? String(rep.frames) : "";
  el("animSum").textContent = animSummary(rep, frame);
  el("animMissing").innerHTML = (rep.missing || []).map((m) => `<li>${esc(m)}</li>`).join("");
  if ((rep.files || []).length > 1) {
    chips(
      el("animPick"),
      rep.files.map((f) => ({ value: f, label: f.replace(/\.ani$/i, "") })),
      rep.file,
      onPick,
    );
  }
  const slider = el("animFrame");
  slider.min = "0";
  slider.max = String(Math.max(0, (rep.frames || 1) - 1));
  slider.value = String(clampFrame(frame, rep.frames));
  const rows = onlyChanged ? changedRows(rep.tracks, frame) : frameRows(rep.tracks, frame);
  const cell = (a) => (a ? a.map((v) => v.toFixed(3)).join(" ") : "—");
  el("animTable").innerHTML = rows.length
    ? `<table class="hl-table"><thead><tr><th>骨名</th><th>旋转 x y z w</th><th>位移 x y z</th><th>缩放</th></tr></thead><tbody>${rows
        .map(
          (r) =>
            `<tr><td>${esc(r.bone)}</td><td class="n">${cell(r.quat)}</td><td class="n">${cell(
              r.pos,
            )}</td><td class="n">${r.scale === null ? "—" : r.scale.toFixed(3)}</td></tr>`,
        )
        .join("")}</tbody></table>`
    : `<p class="dim">这一帧相对第 1 帧没有骨在动。取消「只列变了的骨」可以看全部 ${
        (rep.tracks || []).length
      } 根。</p>`;
}

// ---- 右栏：资源概况 + 引用关系 + 关系图谱 ----

/// 概况表的行。空值一律写「未读到」——不留下划线让人猜是空的还是没读。
/// 但整行都没意义时（中文名、用途、大小对不上）宁可不摆：一张七行六行是
/// 「未读到」的表，比少摆两行更让人以为工具坏了。
function profileRows(insp, card) {
  const c = (card && card.card) || {};
  const cn = (insp.names || []).find((n) => /[\u4e00-\u9fff]/.test(n.name));
  const t = card && card.file;
  const rows = [
    ["中文名", cn ? cn.name : ""],
    ["原名", c.name || insp.stem || ""],
    ["类型", insp.what || ""],
    ["用途", c.scenario || ""],
    ["完整程度", c.grade ? `${c.grade} · ${c.gradeWord || ""}`.trim() : ""],
    ["文件数", insp.parts != null ? num(insp.parts) : ""],
    ["文件大小", t && t.bytes != null ? `${num(t.bytes)} 字节` : ""],
    ["所在目录", insp.dir || ""],
  ];
  // 保留「必须有值」的三行（原名/类型/完整程度），其余空的不摆。
  const REQUIRED = new Set(["原名", "类型", "完整程度"]);
  return rows.filter(([k, v]) => v || REQUIRED.has(k)).map(([k, v]) => [k, v || "未读到"]);
}

/// 组成成员统计：把 members 按角色并起来，数「能对上 / 记了但客户端没有」。
///
/// 名字叫 memberStats 而不是 refStats——它数的是这组登记的文件（members），
/// 不是引用边（refs）。这两样在前端曾经共用一个「引用关系」的标题，
/// 把成员数说成引用数，正是项目纪律里「命名推断 ≠ 引用」禁止的事。
function memberStats(insp) {
  const byRole = new Map();
  const bump = (role, hit) => {
    const r = byRole.get(role) || { hit: 0, miss: 0 };
    if (hit) r.hit++;
    else r.miss++;
    byRole.set(role, r);
  };
  for (const m of insp.members || []) {
    const role = m.roleZh || m.role;
    bump(role, Boolean(m.resolved || m.path));
  }
  return [...byRole].map(([role, v]) => ({ role, ...v }));
}

export function paintSide(insp, card) {
  const sec = el("secProfile");
  const empty = el("sideEmpty");
  if (!insp || !insp.found) {
    sec.hidden = true;
    empty.hidden = false;
    return;
  }
  sec.hidden = false;
  empty.hidden = true;

  el("profMeta").innerHTML = profileRows(insp, card)
    .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
    .join("");

  const stats = memberStats(insp);
  const total = stats.reduce((a, r) => a + r.hit + r.miss, 0);
  el("profRefCount").textContent = total ? `（${num(total)}）` : "";

  const lis = stats
    .sort((a, b) => b.hit + b.miss - (a.hit + a.miss))
    .map((r) => {
      const [color, ch] = styleOf(r.role);
      const fail = r.miss > 0;
      return `<li>
        <span class="ric" style="background:${color}">${esc(ch)}</span>
        <span class="rn">${esc(r.role)}</span>
        <span class="rv ${fail ? "bad" : "good"}">${num(r.hit)}/${num(r.hit + r.miss)}</span>
      </li>`;
    })
    .join("");
  el("profRefs").innerHTML = lis || `<li class="dim">这组没有读到组成成员。</li>`;

  paintMiniGraph(insp);
}

/// 小关系图谱：中心 = 当前资产，四周 = 各类组成成员的命中数。
/// 只画回包里真有的类别，命中 0 的也不省略——「这一类一条都没对上」
/// 本身就是最该被看见的事。
function paintMiniGraph(insp) {
  const stats = memberStats(insp).sort((a, b) => b.hit + b.miss - (a.hit + a.miss)).slice(0, 6);
  const w = 268;
  const rowH = 34;
  const h = Math.max(96, 26 + stats.length * rowH);
  const cx = 68;
  const cy = h / 2;
  const rx = 196;
  const name = (insp.stem || "").slice(0, 16);
  const center = `<g>
      <rect x="${cx - 52}" y="${cy - 16}" width="104" height="32" rx="8" fill="#0d8f79"/>
      <text x="${cx}" y="${cy + 4}" text-anchor="middle" fill="#fff" font-size="11.5" font-weight="600">${esc(trunc(name, 14))}</text>
    </g>`;
  const nodes = stats
    .map((r, i) => {
      const y = 26 + i * rowH + rowH / 2 - 4;
      const [color, ch] = styleOf(r.role);
      const bad = r.miss > 0;
      return `<g>
          <path d="M${cx + 52} ${cy} C ${(cx + rx) / 2} ${cy}, ${(cx + rx) / 2} ${y}, ${rx - 26} ${y}"
            fill="none" stroke="${bad ? "#e8a9a4" : "#cfe4df"}" stroke-width="1.3"/>
          <rect x="${rx - 26}" y="${y - 11}" width="26" height="22" rx="6" fill="${color}"/>
          <text x="${rx - 13}" y="${y + 4}" text-anchor="middle" fill="#fff" font-size="11">${esc(ch)}</text>
          <text x="${rx + 6}" y="${y + 4}" fill="#5d6f6a" font-size="11">${esc(trunc(r.role, 5))} ${r.hit}/${r.hit + r.miss}</text>
        </g>`;
    })
    .join("");
  el("relGraph").innerHTML = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="引用关系图谱">${center}${nodes}</svg>`;
}

function trunc(s, n) {
  const t = String(s || "");
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

// ---- 详情标签上的计数 ----

/// 标签上的数字跟标签名必须同指一件事：这里两个数分别是
/// 「组成成员条数」和「缺失条数」，不是引用边数——引用边（refs）不在回包里。
export function paintTabCounts(insp) {
  const total = memberStats(insp).reduce((a, r) => a + r.hit + r.miss, 0);
  el("tabRelCount").textContent = total ? total : "";
  const gaps = (insp.missing || []).length;
  el("tabMissCount").textContent = gaps ? gaps : "";
}

// ---- 文件清单 / 原始数据 ----

export function paintFiles(insp) {
  const members = insp.members || [];
  el("fileCount").textContent = members.length ? `${num(members.length)} 个` : "";
  el("fileList").innerHTML =
    members
      .map(
        (m) =>
          `<div><dt>${esc(m.roleZh || m.role)}</dt><dd title="${esc(m.path || m.name)}">${esc(
            m.path ? basename(m.path) : m.name,
          )}${m.resolved || m.path ? "" : "（缺）"}</dd></div>`,
      )
      .join("") || `<div><dt>—</dt><dd>这组没有附属文件</dd></div>`;
}

function basename(p) {
  const segs = String(p || "").split(/[\\/]/).filter(Boolean);
  return segs[segs.length - 1] || p;
}

export function paintRaw(reply) {
  try {
    el("rawJson").textContent = JSON.stringify(reply, null, 2).slice(0, 40000);
  } catch {
    el("rawJson").textContent = "回包无法序列化。";
  }
}

// ---- 资源完整度环形图 ----

/// 环形图的每一路「体检项」。命中判据全部来自 absencesOf 已经算好的
/// {label, state, why}——不在这里另立一套口径，否则环里的百分比和下面
/// 「有什么·缺什么」的文字迟早打架。state 三态直接映射成 就绪/缺失/未解。
///   就绪 = 有（a-ok）
///   缺失 = 缺（a-missing）——客户端本来就没带
///   未解 = 还没解出（a-unknown）——客户端给了，工具还没读懂
function ringItems(absences) {
  return absences.map((a) => ({
    label: a.label,
    state: a.state === "ok" ? "ok" : a.state === "missing" ? "missing" : "unknown",
    why: a.why,
  }));
}

function ringColor(state) {
  return state === "ok" ? "#0d8f79" : state === "missing" ? "#d8483f" : "#c07a12";
}

/// 环形图 + 右侧一路一张小卡。百分比 = 就绪项 / 全部项。
/// 分母写在圆心下面，绝不让人猜这是「按文件算」还是「按引用算」。
/// st = lib/detailState.js::loaded() 算出来的展示状态（s.absences.items 已就绪）。
export function paintRing(st) {
  const items = ringItems((st && st.absences && st.absences.items) || []);
  const box = el("ringBox");
  if (!items.length) {
    box.innerHTML = `<p class="dim">这一组没有可评估的项。</p>`;
    return;
  }
  const ok = items.filter((i) => i.state === "ok").length;
  const miss = items.filter((i) => i.state === "missing").length;
  const unknown = items.filter((i) => i.state === "unknown").length;
  const pct = Math.round((ok / items.length) * 100);

  // 环形：r=34，周长 2πr；用 stroke-dasharray 画进度弧。
  const r = 34;
  const C = 2 * Math.PI * r;
  const arc = (C * pct) / 100;
  const color = missingOf(miss, unknown, pct);
  const ring = `<svg class="ring" viewBox="0 0 88 88" role="img" aria-label="资源完整度 ${pct}%">
      <circle cx="44" cy="44" r="${r}" fill="none" stroke="#eef2f1" stroke-width="9"/>
      <circle cx="44" cy="44" r="${r}" fill="none" stroke="${color}" stroke-width="9"
        stroke-linecap="round" stroke-dasharray="${arc.toFixed(1)} ${C.toFixed(1)}"
        transform="rotate(-90 44 44)"/>
      <text x="44" y="42" text-anchor="middle" fill="#16211e" font-size="20" font-weight="700">${pct}%</text>
      <text x="44" y="57" text-anchor="middle" fill="#8c9c97" font-size="9">${items.length} 项</text>
    </svg>`;

  const cards = items
    .map(
      (i) => `<div class="ring-card c-${i.state}" title="${esc(i.why)}">
        <span class="dot" style="background:${ringColor(i.state)}"></span>
        <span class="rl">${esc(i.label)}</span>
        <span class="rs">${i.state === "ok" ? "就绪" : i.state === "missing" ? "缺失" : "未解"}</span>
      </div>`,
    )
    .join("");

  const summary =
    `<span class="rk ok">就绪 ${ok}</span>` +
    (miss ? `<span class="rk bad">缺失 ${miss}</span>` : "") +
    (unknown ? `<span class="rk warn">未解 ${unknown}</span>` : "");

  box.innerHTML = `<div class="ring-main">${ring}</div><div class="ring-side">${summary}${cards}</div>`;
}

/// 圆环颜色：有硬缺失就是红，只有「还没解出」是橙，全绿是青。
/// 顺序不能反——有真缺的组里混进橙色，会让人以为那只是「工具还没跟上」。
function missingOf(miss, unknown, pct) {
  if (miss) return "#d8483f";
  if (unknown) return "#c07a12";
  return pct >= 100 ? "#0d8f79" : "#3b7fd4";
}

// ---- 底部修复建议条 ----

/// 只在真有缺失时出现。点击切到「缺失资源」标签——不去别处编一套修复流程。
export function paintFixBar(insp) {
  const host = el("fixBarHost");
  if (!host) return;
  const gaps = (insp.missing || []).length;
  if (!gaps) {
    host.innerHTML = "";
    return;
  }
  const first = trunc(insp.missing[0], 40);
  host.innerHTML = `<div class="fix-bar"><span class="ico">!</span><span>检测到 <b>${num(
    gaps,
  )} 个缺失项</b>（${esc(first)}…）— 建议检查 pak 是否完整，或核实这些资源是否本就未随包发布。</span>
    <button type="button" class="ghost sm" data-goto="missing">查看修复建议</button></div>`;
  host.querySelector("[data-goto]").addEventListener("click", () => showTabPane("missing"));
}
