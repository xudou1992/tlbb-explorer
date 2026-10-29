// 地图灰模浏览器的状态机（纯函数，不碰 DOM）。
//
// 和详情页同一个病根：出事的方式不是"算错"，而是**脏**——换地图、换格子、
// 加载失败时上一张图的实例矩阵还挂在屏上，于是新地图 ID 配旧实例，等于凭空
// 造出一批这张图里不存在的物件。靠人在渲染代码里"记得清空"迟早会漏，
// 所以规定：loading() 和 failed() 一律从 empty() 出发，任何字段都残留不了。
//
// 另一条同源的红线：**地图名就是客户端原文 ID**。这个项目没有地图中文名表，
// 任何"帮它翻译一下"的加工都是编数据，所以 mapId 全程原样透传。
//
// 还有一条地图独有的纪律：**读到 0 个物件不等于还记得不知道。**
// 没数据时 counts 是 null（"还不知道"），只有真读到才给 {0,0,0}，
// 否则界面会把"还没读"显示成"这张图是空的"。

import { esc, num } from "../ui.js";

/// 每张图默认先列多少个格子。城战级地图能有几百个格子，列全部就是几千行 DOM。
export const ROWCAP = 40;

/// 缺失原因兜底。空原因绝不能落到界面上——那等于制造一个假原因。
const WHY_UNKNOWN = "原因未定";

/// 全空状态。字段清单就是"界面上有哪些地方会被写脏"的清单。
export function empty() {
  return {
    mapId: "",
    phase: "empty", // empty | loading | error | ready | noObjects
    error: "",
    title: "",
    sum: "",
    instances: [],
    scenes: { items: [], count: "", html: "", truncated: false },
    counts: null, // 还不知道 = null；绝不用 {0,0,0} 冒充"读到了 0 个"
    missing: { items: [], count: "", html: "" },
    absent: { items: [], html: "" },
    canDo: { items: [], visible: false, html: "" },
    tech: { rows: [], html: "" },
  };
}

export function loading(mapId) {
  const s = empty();
  s.mapId = rawId(mapId);
  s.phase = "loading";
  s.title = "正在读取这张地图…";
  s.sum = "还没读到任何东西。";
  return s;
}

export function failed(mapId, err) {
  const s = empty();
  s.mapId = rawId(mapId);
  s.phase = "error";
  s.error = whyOf(err, "读取失败，但没给出原因");
  s.title = "读取失败";
  s.sum = s.error;
  return s;
}

/// 场景在，但一个物件都没有——"读到了，里面是空的"，不是"没读到"。
/// phases 不同、措辞不同、counts 是真实的 0（因为确实读到了）。
export function noObjects(mapId, payload) {
  const s = ready(mapId, payload);
  s.phase = "noObjects";
  s.title = `${s.mapId} · 场景是空的`;
  s.sum = "场景读到了，里面一个物件都没有。";
  s.canDo = {
    items: ["旋转 / 缩放（只能看空场景）"],
    visible: true,
    html: renderCan(s.canDo.items),
  };
  return s;
}

/// 客户端原文地图 ID。不翻译、不编中文名——这个项目没有地图中文名表。
/// 只做裁剪和编解码，绝不改内容。
function rawId(mapId) {
  return decode(mapId) ?? String(mapId ?? "");
}

/// payload 里的 map_id 优先（回包自己说了是哪张图），否则用调用方传的。
function idOf(mapId, payload) {
  const fromPayload = payload && typeof payload === "object" ? payload.mapId ?? payload.map_id : null;
  return rawId(fromPayload ?? mapId);
}

function decode(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  return s === "" ? null : s;
}

/// 原因必须是给人看的一句话。没有原因就明确写"原因未定"，
/// 不能留空串、不能留 undefined —— 那在界面上就是一片空白。
function whyOf(reason, fallback) {
  const t = decode(reason);
  if (!t || t === "undefined" || t === "null" || t === "NaN") return fallback || WHY_UNKNOWN;
  return t;
}

/// 每个实例一行。实例数组原样留着（渲染要 matrix），另存一个不含布尔的数值数组。
function instanceOf(it, i) {
  const o = it && typeof it === "object" ? it : {};
  return {
    meshIndex: Number.isInteger(o.meshIndex) ? o.meshIndex : -1,
    matrix: Array.isArray(o.matrix) ? o.matrix.slice() : o.matrix ?? null,
    name: decode(o.name) ?? `第 ${i + 1} 个实例`,
    label: decode(o.label) ?? "",
  };
}

/// 这个实例算不算"读到了"。matrix 是画它出来唯一的依据：
/// 没有 matrix 就画不出，不能算已解析。
function isResolved(it) {
  return Boolean(it && it.matrix && typeof it.matrix === "object");
}

/// 缺失清单：每项必须有非空的 name（客户端原文）和 reason（给人看的原因）。
function missingOf(payload) {
  const src = Array.isArray(payload && payload.missing) ? payload.missing : [];
  return src.map((m, i) => {
    if (m === null || m === undefined) {
      return { name: `第 ${i + 1} 项`, reason: WHY_UNKNOWN };
    }
    if (typeof m === "string") return { name: decode(m) ?? `第 ${i + 1} 项`, reason: WHY_UNKNOWN };
    return {
      name: decode(m.name) ?? `第 ${i + 1} 项`,
      reason: whyOf(m.reason ?? m.why, WHY_UNKNOWN),
    };
  });
}

/// 已知读不到的东西。照实说，不许圆场。
/// reason 为空的条目不会被丢掉——那等于把"读不到"藏起来，比留白更糟。
function absentOf(payload) {
  const src = (payload && payload.absent) || [];
  return src.map((a, i) => {
    if (typeof a === "string") return { name: decode(a) ?? `第 ${i + 1} 项`, reason: WHY_UNKNOWN };
    const o = a && typeof a === "object" ? a : {};
    return {
      name: decode(o.name) ?? `第 ${i + 1} 项`,
      reason: whyOf(o.reason ?? o.why, WHY_UNKNOWN),
    };
  });
}

/// 现在能做什么。没解出东西时说"只能看"，不能空着让人以为坏掉了。
function canOf(payload, n) {
  const src = (payload && payload.canDo) || [];
  const items = src.map((c) => decode(c)).filter(Boolean);
  if (items.length) return items;
  if (n > 0) return ["旋转 / 缩放", `点击查看（${num(n)} 个物件）`];
  return ["旋转 / 缩放"];
}

function renderCan(items) {
  return items.map((c) => `<i class="${/没对上|未解|尚未|只能/.test(c) ? "todo" : ""}">${esc(c)}</i>`).join("");
}

/// 每格一行：格子名 + 实例数 + 缺几件 + 是读到还是没读到。
function sceneRows(payload) {
  const src = (payload && payload.scenes) || [];
  const items = src.map((sc, i) => {
    const o = sc && typeof sc === "object" ? sc : {};
    const name = decode(o.name) ?? decode(sc) ?? `第 ${i + 1} 个格子`;
    // 数字缺失时给 null 而不是 0——0 是"读到了空的"，null 是"还不知道"。
    const inst = Number.isFinite(o.instances) ? o.instances : Number.isFinite(o.count) ? o.count : null;
    const missing = Number.isFinite(o.missing) ? o.missing : null;
    return {
      name,
      instances: inst,
      missing,
      ok: o.ok !== undefined ? Boolean(o.ok) : inst === null ? false : inst > 0,
      row: `${name} · ${inst === null ? "实例数未读到" : `${num(inst)} 个实例`}`,
    };
  });
  const shown = items.slice(0, ROWCAP);
  const truncated = items.length > ROWCAP;
  return {
    items,
    count: items.length ? `${num(items.length)} 个格子${truncated ? `（先列 ${ROWCAP} 个）` : ""}` : "0 个格子",
    html: shown.length
      ? shown
          .map(
            (r) =>
              `<li class="${r.ok ? "hit" : "miss"}"><span class="kd">${esc(r.name)}</span><em>${
                r.instances === null ? "实例数未读到" : `${num(r.instances)} 个实例`
              }</em>${r.missing ? `<em class="miss">缺 ${num(r.missing)}</em>` : ""}</li>`,
          )
          .join("") + (truncated ? `<li class="dim">另有 ${items.length - ROWCAP} 个格子未列出</li>` : "")
      : `<li class="dim">没读到格子清单。</li>`,
    truncated,
  };
}

function renderMissing(items) {
  return items.length
    ? items.map((m) => `<li class="miss">${esc(m.name)}：${esc(m.reason)}</li>`).join("")
    : `<li class="ok">没有发现明显缺失</li>`;
}

function renderAbsent(items) {
  return items.length
    ? items.map((a) => `<li class="a-missing">${esc(a.name)}：${esc(a.reason)}</li>`).join("")
    : "";
}

/// 技术信息。缺值也要占一行说明"未读到"，不能留空行。
export function techRows(mapId, payload, counts) {
  const t = (payload && payload.tech) || {};
  const miss = "未读到";
  const bytes = t.unreadBytes ?? t.unknownBytes;
  const base = t.base ?? t.baseOffset;
  const stride = t.stride;
  const c = counts || { instances: 0, resolved: 0, missing: 0 };
  return [
    ["客户端地图 ID", mapId || miss],
    ["实例数", num(c.instances)],
    ["已解析", num(c.resolved)],
    ["缺失", num(c.missing)],
    ["记录表起点", base ?? miss],
    ["每条记录步长", stride ?? miss],
    ["没读懂的字节", bytes ?? miss],
    ["本次核对耗时", t.elapsedMs != null ? `${num(t.elapsedMs)} 毫秒` : miss],
  ];
}

/// 从后端 map_scene 回包推出这一张图的界面状态。
export function ready(mapId, payload) {
  const p = payload && typeof payload === "object" ? payload : {};
  const s = empty();
  s.mapId = idOf(mapId, p);
  s.phase = "ready";
  s.title = s.mapId;

  const instances = Array.isArray(p.instances) ? p.instances.map(instanceOf) : [];
  const missing = missingOf(p);
  const absent = absentOf(p);
  const scenes = sceneRows(p);

  // 统计的分子分母必须都落在同一批实例上：resolved 和 missing 都是
  // 从 instances 数出来的，所以加起来一定等于 instances.length。
  // 后端另外报了一个和实例数对不上的 unresolved 时，不把它塞进计数——
  // 那会做出一份自相矛盾的表，宁可让界面显示"数据对不上"也不行。
  const total = instances.length;
  const resolved = instances.filter(isResolved).length;
  const missingCount = total - resolved;
  if (resolved + missingCount !== total) {
    throw new Error(
      `地图 ${s.mapId} 的统计对不上：已解析 ${resolved} + 缺失 ${missingCount} ≠ 实例 ${total}`,
    );
  }

  s.instances = instances;
  s.scenes = scenes;
  // 后端另报了一个"没摆放矩阵"的条数时，它必须和实例数对得上。
  // 对不上说明这条回包自相矛盾——宁可让界面显示"数据对不上"，
  // 也不能拿两套互相打架的数凑一个看着成立的百分比。
  const declared = p.unresolvedCount ?? p.unresolved;
  if (Number.isFinite(declared) && declared + resolved !== total) {
    throw new Error(
      `地图 ${s.mapId} 的统计对不上：回包说未解析 ${declared} 个，已解析 ${resolved} 个，` +
        `加起来 ${declared + resolved} ≠ 实例 ${total}`,
    );
  }
  s.counts = { instances: total, resolved, missing: missingCount };
  s.missing = {
    items: missing,
    count: total ? `缺 ${num(missingCount)} 个` : "0 个",
    html: renderMissing(missing),
  };
  s.absent = { items: absent, html: renderAbsent(absent) };
  const can = canOf(p, total);
  s.canDo = { items: can, visible: can.length > 0, html: renderCan(can) };
  const grounded = instances.filter(
    (it) => Number.isInteger(it.meshIndex) && it.meshIndex >= 0 && isResolved(it),
  ).length;
  s.sum =
    `${total ? `${num(total)} 个实例` : "没读到实例"}` +
    ` · 能定位到 ${num(grounded)} 个 · 缺 ${num(missingCount)} 个`;
  s.tech = { rows: techRows(s.mapId, p, s.counts), html: "" };
  s.tech.html = s.tech.rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join("");
  return s;
}
