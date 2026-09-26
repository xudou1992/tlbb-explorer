// 库状态浮层：整库的引用能不能对上文件。
// 这一屏只回答一个问题，数字全部来自 Rust 侧的 ref_health，前端不做任何算术。
// 「谁提到了它」是反查：两份文件里写着同一个名字只说明它们都提到过，不代表共用同一份资源。

import { el, esc, num, errText } from "./ui.js";
import * as api from "./api.js";
import { state } from "./state.js";
import { pctText, citedVerdict, CITED_NOTE } from "./lib/wording.js";
import { makeSeq } from "./lib/seq.js";

const barColor = (p) => (p >= 80 ? "var(--jade)" : p >= 50 ? "var(--blue)" : "var(--amber)");

/// 比例只算不排：0 而有命中时必须走 pctText 的「不足 1%」，别再说 0%。
const pctOf = (h) => (h.assetsCiting ? Math.round((h.assetsCitingResolved / h.assetsCiting) * 100) : 0);

function bar(p) {
  return `<span class="mini-bar wide"><i style="width:${p}%;background:${barColor(p)}"></i></span>`;
}

function summaryHtml(h) {
  const extRows = h.byExt
    .map(
      (e) => `<tr>
        <td><span class="kd">${esc(e.kind)}</span> <code>${esc(e.ext)}</code></td>
        <td class="n">${num(e.total)}</td>
        <td class="n">${num(e.resolved)}</td>
        <td class="bar-cell"><span class="mini-bar"><i style="width:${e.resolvedPct}%;background:${barColor(e.resolvedPct)}"></i></span><em>${pctText(e.resolvedPct, e.resolved)}</em></td>
        <td class="n dim">${e.danglingNames ? num(e.danglingNames) : "—"}</td>
      </tr>`,
    )
    .join("");

  // data-key 用编号查（准），标题用客户端原文名说（人话）——
  // 拿编号当标题等于把 hash 摆成一行里最大的字。
  const nameRow = (x, who) => `<li class="${who === "dangling" ? "miss" : ""}">
      <span class="kd">${esc(x.kind)}</span><code title="${esc(x.name)}">${esc(x.name)}</code>
      <button type="button" class="mini" data-key="${esc(x.hash || x.name)}" data-name="${esc(x.name)}">${num(x.citations)} 处提到</button>
    </li>`;

  return `
  <p class="plain">客户端文件里写下的「谁用到谁」，有多少真能对上我们手上的文件。对不上的部分不是解析漏了，
  而是发布包当初就没带这些资源——所以照实列出来，不藏。</p>

  <div class="hl-cards">
    <div class="hl-card"><dt>引用总数</dt><dd>${num(h.refsTotal)}</dd><span>客户端文件里写下的引用条目</span></div>
    <div class="hl-card"><dt>能对上文件的</dt><dd>${num(h.refsResolved)} <em>${pctText(h.resolvedPct, h.refsResolved)}</em></dd>${bar(h.resolvedPct)}<span>剩下 ${num(h.refsTotal - h.refsResolved)} 条只有名字</span></div>
    <div class="hl-card"><dt>对不上的名字</dt><dd>${num(h.danglingNames)}</dd><span>只读到名字，没有对应资源</span></div>
    <div class="hl-card"><dt>有引用可查的文件</dt><dd>${num(h.assetsCitingResolved)} / ${num(h.assetsCiting)}</dd><span>按文件算，不是按资产组（全库里至少有一条引用能对上的文件 · ${pctText(pctOf(h), h.assetsCitingResolved)}）</span></div>
  </div>

  <section class="hl-sec">
    <h3>按文件类型看 <em>引用条目 —— 能不能对上</em></h3>
    <table class="hl-table">
      <thead><tr><th>类型</th><th class="n">引用</th><th class="n">对上</th><th>比例</th><th class="n">对不上的名字</th></tr></thead>
      <tbody>${extRows}</tbody>
    </table>
    <p class="foot">「引用」按条目数，「对不上的名字」按不同名字数，两列不是同一单位，别相加。</p>
  </section>

  <div class="hl-cols">
    <section class="hl-sec">
      <h3>被提到最多、且能对上文件 <em>可以顺着查</em></h3>
      <ul class="lines">${h.topCited.map((c) => nameRow(c, "cited")).join("") || `<li class="dim">还没有能对上文件的引用。</li>`}</ul>
    </section>
    <section class="hl-sec">
      <h3>被提到最多、但对不上 <em>包里没有</em></h3>
      <ul class="lines">${h.topDangling.map((d) => nameRow(d, "dangling")).join("") || `<li class="dim">没有对不上的名字。</li>`}</ul>
    </section>
  </div>`;
}

function bindDrill() {
  el("healthBody")
    .querySelectorAll(".mini[data-key]")
    .forEach((b) => {
      b.onclick = () =>
        showCitations(b.dataset.key, b.dataset.name, b.closest("li")?.querySelector(".kd")?.textContent);
    });
}

// 连点两个名字时，先回来的那个不能盖在后回来的上面。
const citeSeq = makeSeq();

async function showCitations(key, title, kindWord) {
  if (!key) return;
  const box = el("healthBody");
  const my = citeSeq.next();
  box.innerHTML = `<p class="dim">正在从客户端数据里找哪些文件提到了它…</p>`;
  try {
    const r = await api.citedBy(key, 200);
    if (citeSeq.isStale(my)) return;
    const rows = r.citations.filter((c) => c.fromPath);
    const blank = r.citations.length - rows.length;
    box.innerHTML = `
      <button type="button" class="ghost back-link" data-back="1">← 返回汇总</button>
      <p class="title">${esc(title || key)}</p>
      ${kindWord ? `<p class="sub">${esc(kindWord)}</p>` : ""}
      <div class="verdict vB">
        <strong>${citedVerdict(rows.length)}</strong>
        <span>${rows.length ? CITED_NOTE : "这个名字目前的引用记录里没有任何来源。"}</span>
      </div>
      <section class="hl-sec"><h3>提到它的文件 <em>${num(rows.length)}</em></h3>
        <ul class="lines">${rows
          .map((c) => `<li><span class="kd">${esc(c.kind)}</span><code title="${esc(c.fromPath)}">${esc(c.fromPath)}</code></li>`)
          .join("") || `<li class="dim">没有任何文件提到它。</li>`}</ul>
      </section>
      ${r.truncated ? `<p class="foot">这条被提到得太多次，只列出了前 ${num(r.citations.length)} 条，实际更多。</p>` : ""}
      ${blank ? `<p class="foot">另有 ${num(blank)} 条来自资源组内部的引用，没有可显示的文件路径，未列出。</p>` : ""}`;
    // 钻进来之前的汇总还在 state.health 里：回去不用重查，重画就行。
    box.querySelector("[data-back]").onclick = () => {
      if (!state.health) return;
      box.innerHTML = summaryHtml(state.health);
      bindDrill();
    };
  } catch (e) {
    if (citeSeq.isStale(my)) return;
    box.innerHTML = `<p class="dim">反查失败：${esc(errText(e))}</p>`;
  }
}

export async function openHealth() {
  el("health").hidden = false;
  const box = el("healthBody");
  if (state.health) {
    box.innerHTML = summaryHtml(state.health);
    bindDrill();
    return;
  }
  if (state.healthBusy) return;
  state.healthBusy = true;
  box.innerHTML = `<p class="dim">正在统计整库的引用…</p>`;
  try {
    state.health = await api.refHealth(40);
    box.innerHTML = summaryHtml(state.health);
    bindDrill();
  } catch (e) {
    box.innerHTML = `<p class="dim">读取失败：${esc(errText(e))}</p>`;
  } finally {
    state.healthBusy = false;
  }
}

export function closeHealth() {
  el("health").hidden = true;
}
