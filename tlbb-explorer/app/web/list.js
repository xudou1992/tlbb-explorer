// 左栏筛选 + 中间列表。列表只回答「哪一条」，一条资产一行。
// 刻意不放缩略图：约 83% 的资产没有可解析的像素，一排类型轮廓只会让人以为那是图。
// 默认也不列未命名组：它们连路径都没记录，标题只能是 16 位编号，摆首屏等于让人读乱码。

import { el, esc, num, chips, line, errText } from "./ui.js";
import * as api from "./api.js";
import { state } from "./state.js";
import { showDetail } from "./detail.js";
import { listCount, railStats, rowMissChip } from "./lib/wording.js";
import { makeSeq } from "./lib/seq.js";

const ALL = { value: "全部", label: "全部" };
const seq = makeSeq();

export function paintRail() {
  const s = state.stats;
  if (!s) return;
  chips(el("kinds"), [ALL, ...s.kinds], state.kind, (v) => {
    state.kind = v;
    refresh();
  });
  chips(el("scenarios"), [ALL, ...s.scenarios], state.scenario, (v) => {
    state.scenario = v;
    refresh();
  });
  chips(
    el("grades"),
    [ALL, ...s.grades.map((g) => ({ value: g.value, label: `${g.value} ${g.label}`, count: g.count }))],
    state.grade,
    (v) => {
      state.grade = v;
      refresh();
    },
  );
  // 分母写在标签里，措辞集中在 lib/wording.js（有测试盯着）。
  // 实算纠正过两处：「主体能打开的」恒等于顶栏那句「已读完 N 组」，是同一件事说两遍；
  // 「有贴图线索的」曾经写 25，其实真有线索的是 9,589 组，25 是**能对上**的组数。
  el("stats").innerHTML = railStats(s).map(([k, v]) => line(k, v)).join("");

  const btn = el("unnamed");
  btn.textContent = state.named ? `看未命名资源 ${num(s.unnamed)}` : "回到有名字的资产";
  btn.classList.toggle("on", !state.named);
}

function rowHtml(c) {
  const parts = (c.parts || [])
    .slice(0, 4)
    .map((p) => `<i>${esc(p.label)} ${p.count}</i>`)
    .join("");
  const miss = c.refTotal - c.locatedTotal;
  const title = c.named ? c.name : "未命名资源";
  const sub = c.named ? c.subtitle : `${c.kind} · 客户端没留下名字和路径`;
  return `<button type="button" class="row-item${state.selected === c.gid ? " on" : ""}" data-gid="${c.gid}">
    <span class="t"><strong title="${esc(title)}">${esc(title)}</strong><em class="grade g${esc(c.grade)}" title="${esc(c.gradeNote)}">${esc(c.grade)}</em></span>
    <span class="s">${esc(sub)}</span>
    <span class="c">${parts || `<i class="dim">没读到部件</i>`}<i>${c.memberTotal} 文件</i>${
      rowMissChip(miss) ? `<i>${esc(rowMissChip(miss))}</i>` : ""
    }</span>
  </button>`;
}

export async function refresh() {
  // 筹码高亮必须跟着每次查询重画：以前只在状态广播时重画，预热一结束
  // 就再也不更新，用户点了筛选界面还显示「全部」。
  paintRail();
  const my = seq.next();
  const filter = {
    query: state.query || null,
    scenario: state.scenario,
    kind: state.kind,
    grade: state.grade,
    onlyWithImage: state.onlyImage,
    named: state.named,
    limit: 300,
  };
  try {
    const page = await api.listGroups(filter);
    if (seq.isStale(my)) return;
    const box = el("rows");
    box.innerHTML = page.items.map(rowHtml).join("");
    box.querySelectorAll(".row-item").forEach((n) => {
      n.onclick = () => showDetail(Number(n.dataset.gid));
    });
    el("empty").hidden = page.items.length > 0;
    el("count").textContent = listCount(page.total, page.items.length, page.ready);
    el("words").textContent =
      page.queryWords.length > 1 ? `按这几种拼法都找了：${page.queryWords.join("、")}` : "";
  } catch (e) {
    if (seq.isStale(my)) return;
    el("count").textContent = "读取失败";
    el("rows").innerHTML = `<p class="dim">${esc(errText(e))}</p>`;
  }
}

export async function refreshStats() {
  try {
    state.stats = await api.stats();
    state.scanned = state.stats.scanned;
    state.total = state.stats.totalGroups;
    state.ready = state.stats.ready;
    const p = state.total ? Math.round((state.scanned / state.total) * 100) : 0;
    el("bar").style.width = `${p}%`;
    el("progressText").textContent = state.ready
      ? `已读完 ${num(state.total)} 组`
      : `正在读取 ${p}% · ${num(state.scanned)}/${num(state.total)}`;
    paintRail();
  } catch {
    /* 启动早期状态还没就绪，这一轮先跳过 */
  }
}

/// 有名字的 ↔ 未命名的，两边互斥地看，混在一起就又是一墙编号。
export function toggleUnnamed() {
  state.named = !state.named;
  refresh();
}

export function resetFilters() {
  Object.assign(state, {
    query: "",
    kind: "全部",
    scenario: "全部",
    grade: "全部",
    onlyImage: false,
    named: true,
  });
  el("q").value = "";
  el("onlyImage").checked = false;
  refresh();
}
