// 地图浏览器：一层的「有什么 / 缺什么」都按资产页那套口径说话。
//
// 为什么走浮层而不是新页面：`health` 已经是这个形状（整屏浮层 + 一个返回按钮），
// 复用同一套壳，资产链路一行都不用改。地图不是新的一套工具，是同一个客户端的
// 另一类资源。
//
// 这一版只画得出三样东西，界面顶部必须把话说明白：
//   平地 + 格子线（.map 地形格式未解，高度不在这个文件里）、灰模（贴图全线断链）、
//   原文 ID（全库没有中文地图名）。朝向是第四件：R 还是 Rᵀ 未证，默认原样直读。

import { el, esc, num } from "./ui.js";
import * as api from "./api.js";
import { MeshViewer } from "./mesh-viewer.js";
import { makeSeq } from "./lib/seq.js";
import { pctText } from "./lib/wording.js";

const seq = makeSeq();
let viewer = null;
let rows = [];

function banner(html) {
  el("mapBanner").innerHTML = html;
}

function status(msg) {
  const box = el("mapState");
  box.textContent = msg || "";
  box.hidden = !msg;
}

/// 右侧那张信息表：每个数字都带自己的分母，四类"没画出来"分开说。
/// 混成一个「缺」就等于骗人——空格子、不是物件表的文件、名字对不上，
/// 是完全不同的三件事。
function info(s) {
  const pct = s.records ? (s.resolved / s.records) * 100 : 0;
  const line = (k, v) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`;
  const bits = [
    line("格子文件", `${num(s.grids)} 个`),
    line("摆位记录", `${num(s.records)} 条`),
    line(
      "能画出形状",
      `${num(s.resolved)} 条 · ${pctText(pct, s.resolved)}（分母是上面那个实测条数，不是文件头声明的条数）`,
    ),
    line("去重后的模型", `${num(s.uniqueMeshes)} 个 · 实例 ${num(s.instances.length)} 个`),
  ];
  if (s.emptyGrids) bits.push(line("空着的格子", `${num(s.emptyGrids)} 个：那一格本来就没摆东西`));
  if (s.unreadableGrids)
    bits.push(line("读不通的格子", `${num(s.unreadableGrids)} 个：不是物件清单那类文件`));
  if (s.unmatched)
    bits.push(line("名字对不上", `${num(s.unmatched)} 条：记了名字但没有任何文件叫这个，没去猜该用哪个模型`));
  if (s.emptyNamed) bits.push(line("名字为空", `${num(s.emptyNamed)} 条`));
  bits.push(
    line(
      "缺什么",
      `<span class="miss">贴图 ✘（材质引用的贴图名在客户端里没有实体）</span><br />` +
        `<span class="miss">地形高度 ✘（.map 存的是地表编码格、不是高低数据）</span><br />` +
        `<span class="miss">碰撞与能不能走 ✘（没读）</span><br />` +
        `<span class="miss">动作 ✘（没读）</span>`,
    ),
  );
  const reasons = s.gridReasons
    .map(
      (r) =>
        `<li class="a-missing"><span class="kd">${esc(r.reason)}</span><em>${num(r.grids)} 个</em>` +
        `<span>${r.sample.map(esc).join("、")}</span></li>`,
    )
    .join("");
  el("mapInfo").innerHTML = bits.join("");
  el("mapAbs").innerHTML = reasons || `<li class="a-ok"><span>这一版没有读不通的格子</span></li>`;
  const miss = s.unmatched_sample
    .map((n) => `<li>${esc(n)}</li>`)
    .join("");
  el("mapMiss").innerHTML =
    miss + (s.unmatchedTruncated ? `<li class="dim">…只显示前 60 个，其余按个数计在上面</li>` : "");
  el("secMapMiss").hidden = !miss;
}

async function openScene(id) {
  const my = seq.next();
  rows.forEach((r) => r.classList.toggle("on", r.dataset.id === id));
  status(`正在读 ${id} 的 ${""}格子…`);
  banner(`<b>灰模预览</b> 只把物件摆在该在的位置上。<span class="warn">地形没解出</span><span class="warn">没有花纹</span><span class="warn">朝向待比对</span><span class="dim">地图原名 ${esc(id)}</span>`);
  let s;
  try {
    s = await api.mapScene(id);
  } catch (e) {
    if (seq.isStale(my)) return;
    status(`这张图没读出来：${e instanceof Error ? e.message : String(e)}`);
    if (viewer) viewer.stop();
    el("mapCanvas").hidden = true;
    el("mapInfo").innerHTML = "";
    el("mapAbs").innerHTML = "";
    return;
  }
  if (seq.isStale(my)) return; // 已经切到别的图了

  info(s);
  // 一个实例都没有：画不出东西，但那不是失败，别把画布亮着假装在渲染。
  if (!s.instances.length) {
    if (viewer) viewer.stop();
    el("mapCanvas").hidden = true;
    status(
      s.records
        ? `读到了 ${num(s.records)} 条记录，可是一条都没对上模型文件——所以这里没有东西可画。`
        : `读到了，这张图 ${num(s.grids)} 个格子一个都没摆东西。能转、能缩放，就是看不到物件。`,
    );
    return;
  }
  el("mapCanvas").hidden = false;
  if (!viewer) {
    try {
      viewer = new MeshViewer(el("mapCanvas"));
    } catch (e) {
      status(`这台机器开不了 3D 预览：${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    viewer.onlost = () => {
      seq.next();
      status("显卡上下文被系统收回了，重新点一下这张图就能再看。");
    };
  }
  status("");
  try {
    // instances 的形状就是 expandInstances 吃的那个；矩阵是 .scene 原样直读，
    // 中间不许再转置（转一次全图叠到原点且不报错）。
    viewer.loadInstances({ meshes: s.meshes, instances: s.instances });
  } catch (e) {
    status(`画不出来：${e instanceof Error ? e.message : String(e)}`);
    return;
  }
  status(
    `${num(s.instances.length)} 件 · ${num(s.uniqueMeshes)} 个模型 · 平地是代替物（地形未解）`,
  );
}

export async function openMap() {
  el("maps").hidden = false;
  if (rows.length) return;
  status("正在列地图…");
  try {
    const list = await api.mapList(500);
    rows = list.map((m) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "maprow";
      b.dataset.id = m.id;
      b.innerHTML = `<span class="mid">${esc(m.id)}</span><span class="mg">${num(m.grids)} 格</span>`;
      b.onclick = () => openScene(m.id);
      el("mapRows").appendChild(b);
      return b;
    });
    status(
      `共 ${num(list.length)} 张图：口径是"至少有一个格子文件的目录"，不是客户端承认存在的地图全集`,
    );
  } catch (e) {
    status(`列不出地图：${e instanceof Error ? e.message : String(e)}`);
  }
}

export function closeMap() {
  el("maps").hidden = true;
  seq.next(); // 关掉就把在途回包作废：否则切回来会看到上一张图的残留
  if (viewer) viewer.stop();
}
