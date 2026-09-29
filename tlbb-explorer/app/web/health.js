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

  <section class="hl-sec" id="gapSec">
    <h3>容器与清单 <em>pak 索引里有多少、清单登记了多少</em></h3>
    <p class="dim">正在数容器索引…</p>
  </section>`;
}

/// 清单是某一刻扫容器落下来的快照。客户端打了补丁（`data_1.pak` 又长几代索引）
/// 或者换机后没重建库，容器里就有文件是清单不认识的：「浏览」按容器列文件看得见，
/// 「资产检索 / 反查」按清单查看不见。这个不一致必须由工具自己说出来——
/// 不然用户只会以为「客户端里没这个文件」。
async function paintGap() {
  const sec = el("gapSec");
  if (!sec) return;
  try {
    const g = await api.catalogGap();
    const miss = g.uncovered;
    sec.innerHTML = `<div class="hl-cards">
      <div class="hl-card"><dt>容器索引条目</dt><dd>${num(g.containerUnique)}</dd><span>${g.paks} 个容器去重后的文件数</span></div>
      <div class="hl-card"><dt>清单已登记</dt><dd>${num(g.dbResources)}</dd><span>resources.db 里的条数</span></div>
      <div class="hl-card"><dt>清单没登记</dt><dd class="${miss ? "bad" : ""}">${num(miss)}</dd><span>${
        miss
          ? "这些文件「浏览」里能翻到，资产检索与反查查不到"
          : "容器里的每一条都在清单里"
      }</span></div>
    </div>
    ${
      miss
        ? `<p class="foot">清单比容器少 ${num(miss)} 条：客户端打过补丁，或这台机器还没重建过清单。重建方法见 README「首次运行」第 2 步（一趟几分钟）。</p>`
        : ""
    }
    ${(g.unreadable || []).length ? `<p class="foot">有容器打不开：${esc(g.unreadable.join("；"))}</p>` : ""}`;
  } catch (e) {
    sec.innerHTML = `<p class="dim">数不出容器与清单的缺口：${esc(errText(e))}</p>`;
  }
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
  // 从哪个视图进来的就退回哪儿：写死「返回资产」，浏览首屏进来的人会被说糊涂。
  el("closeHealth").textContent = state.view === "browse" ? "返回浏览" : "返回资产";
  const box = el("healthBody");
  if (state.health) {
    box.innerHTML = summaryHtml(state.health);
    bindDrill();
    paintGap();
    return;
  }
  // 懒预热之后「还没开始读取」是浏览首屏的常态，不是故障。ref_health 不触发
  // 预热，硬查只会拿回一整页 0——把「还没读」摆成「引用总数 0」是在替库里
  // 编造事实。给指路文案和一个直接的入口，别让人对着空表猜哪里坏了。
  if (!state.ready && !(state.stats && state.stats.totalGroups > 0)) {
    const started = Boolean(state.stats); // stats 回过但还没有数字：预热刚起步
    box.innerHTML = `
      <p class="plain">资产库还没有可统计的内容——${
        started ? "它刚开始读取，还没有读出数字。" : "它还没开始读取。"
      }浏览、预览、导出不依赖这份统计，现在就能用。</p>
      <p class="plain">要看整库的引用能对上多少，进「资产」标签让它开始读取，过一会儿再来这里。</p>
      <p><button type="button" class="ghost" data-warm>去「资产」标签开始读取</button></p>`;
    box.querySelector("[data-warm]").addEventListener("click", () => {
      closeHealth();
      // 走顶栏标签自己的切换流程：视图持久化、懒预热、界面显示都归它管。
      el("tabAssets").click();
    });
    return;
  }
  if (state.healthBusy) return;
  state.healthBusy = true;
  box.innerHTML = `<p class="dim">正在统计整库的引用…${
    state.ready ? "" : "（资产库还在后台读取，先出的是已读部分的数字）"
  }</p>`;
  try {
    state.health = await api.refHealth(40);
    box.innerHTML = summaryHtml(state.health);
    if (!state.ready) {
      // 中途看的统计只是部分真相，必须说出来，不然「对上 62%」会被当成终稿。
      box.insertAdjacentHTML(
        "afterbegin",
        `<p class="plain">资产库还在后台读取（顶栏有进度），下面是已读部分的统计，读完后数字会变。</p>`,
      );
    }
    bindDrill();
    paintGap();
  } catch (e) {
    box.innerHTML = `<p class="dim">读取失败：${esc(errText(e))}</p>`;
  } finally {
    state.healthBusy = false;
  }
}

export function closeHealth() {
  el("health").hidden = true;
}
