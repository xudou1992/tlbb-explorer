// 详情页：只做两件事——把回包交给状态机算，然后把算出来的状态写进 DOM。
//
// 所有"哪些字段该出现、什么时候必须空"的判断都在 lib/detailState.js 里，
// 那边有 node --test 盯着（app/tests/detailState.test.js）。
// 这里刻意不做任何业务判断：判断留在能测的地方。

import { el } from "./ui.js";
import * as api from "./api.js";
import { state } from "./state.js";
import { makeSeq } from "./lib/seq.js";
import { empty, loading, failed, notReady, loaded } from "./lib/detailState.js";
import { showMeshes, hideMeshes } from "./mesh.js";

const seq = makeSeq();

/// 把一份状态整个铺到屏幕上。每个可写的位置都要出现在这里——
/// 漏一个就是"上一条资产的内容留在屏上"那种事故。
function paint(s) {
  el("guide").hidden = s.phase !== "empty";
  el("body").hidden = s.phase === "empty";
  el("detailPane")?.scrollTo?.({ top: 0 });

  el("dName").textContent = s.title;
  const cn = el("dCn");
  cn.textContent = s.cn;
  cn.hidden = !s.cn;

  const badge = el("dGrade");
  badge.className = `grade g${s.grade}`;
  badge.textContent = s.grade ? `${s.grade} ${s.gradeWord}`.trim() : "";
  badge.title = s.gradeNote;

  el("dSum").textContent = s.sum;

  // 「有什么 · 缺什么」在 ready 时一定出现：不留空白，也不许编原因。
  el("secAbs").hidden = s.phase !== "ready";
  el("abs").innerHTML = s.absences.html;

  el("tree").innerHTML = s.tree.html;
  el("treeCount").textContent = s.tree.count;

  el("gaps").innerHTML = s.phase === "ready" ? s.gaps.html : "";
  el("gapCount").textContent = s.gaps.count;

  el("secCan").hidden = !s.canDo.visible; // 空的区块不占位，否则看着像坏了
  el("canDo").innerHTML = s.canDo.html;

  el("tech").innerHTML = s.tech.html;

  el("secPv").hidden = !s.previews.visible;
  el("pvGrid").innerHTML = s.previews.html;
  el("pvCount").textContent = s.previews.count;
  el("pvNote").textContent = s.previews.visible
    ? "图是现场从客户端数据里解出来的；没解出来的不摆在这里，原因写在下面「缺什么」。"
    : "";

  if (s.mesh.visible) showMeshes(s.mesh);
  else hideMeshes();
}

export async function showDetail(gid) {
  if (!gid) return;
  state.selected = gid;
  document.querySelectorAll(".row-item").forEach((n) => n.classList.toggle("on", Number(n.dataset.gid) === gid));
  const my = seq.next();
  paint(loading(gid)); // 从 empty() 出发，旧内容结构上就留不下来
  try {
    const [d, insp] = await Promise.all([api.cardDetail(gid), api.assetInspect(gid)]);
    if (seq.isStale(my)) return;
    if (!d || !d.card || !insp.found) paint(notReady(gid));
    else paint(loaded(gid, d, insp));
  } catch (e) {
    if (seq.isStale(my)) return;
    paint(failed(gid, e && e.message ? e.message : String(e)));
  }
}

/// 列表清空/重查时把详情区收回初始态，避免"列表换了、右边还是旧资产"。
export function clearDetail() {
  seq.next();
  state.selected = 0;
  paint(empty());
}
