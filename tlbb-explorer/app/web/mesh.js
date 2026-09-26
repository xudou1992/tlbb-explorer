// 立体模型面板：WebGL 上下文只建一次，换资产只是换缓冲。
// 只有一个网格时不显示选择筹码；多个网格时默认自动加载第一个，第一眼就能看到形状。
//
// 状态由 lib/detailState.js 算好交进来（{ visible, meshes }），这里只管取数和画。

import { el, esc, num, errText } from "./ui.js";
import * as api from "./api.js";
import { MeshViewer } from "./mesh-viewer.js";
import { makeSeq } from "./lib/seq.js";

let viewer = null;
const seq = makeSeq();
let meshes = [];
let current = -1;

function status(msg) {
  const box = el("meshState");
  box.textContent = msg || "";
  box.hidden = !msg;
}

function techHtml(d) {
  return [
    ["客户端路径", d.path],
    ["顶点 / 三角面", `${num(d.vertexCount)} / ${num(d.faceCount)}`],
    ["表面朝向", d.hasNormals ? "文件里带着" : "文件里没读到，明暗按面自己算"],
    ["贴图坐标", d.hasUvs ? "读到了" : "没读到"],
    ["材质槽数", d.submeshCount],
    ["还没读懂的字节", `顶点之后 ${num(d.middleBytes)} · 结尾 ${num(d.trailingBytes)}`],
  ]
    .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
    .join("");
}

function ensure() {
  if (!viewer) viewer = new MeshViewer(el("meshCanvas"));
  return viewer;
}

/// 把立体区收成一行：没有画面可看时（无网格 / 取数失败 / 数据对不上），
/// 380px 的空盒子只是占屏，收起来让原因文字自己说话。
function foldStage() {
  el("secMesh").classList.add("folded");
  el("meshCanvas").hidden = true;
}

function paintPick() {
  const node = el("meshPick");
  node.innerHTML = "";
  if (meshes.length < 2) return;
  meshes.forEach((m, k) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (k === current ? " on" : "");
    b.textContent = m.label;
    b.title = m.name;
    b.onclick = () => pick(k);
    node.appendChild(b);
  });
}

async function pick(k) {
  current = k;
  // 上一次可能是 paintEmpty 把画布收掉的：必须在 ensure() 建上下文之前放回来，
  // 隐藏中的 canvas 量不到尺寸。
  el("meshCanvas").hidden = false;
  el("secMesh").classList.remove("folded");
  paintPick();
  const m = meshes[k];
  const my = seq.next();
  status("正在从客户端取这个模型的顶点…");
  el("meshMeta").textContent = "";
  el("meshTech").innerHTML = "";
  let data;
  try {
    data = await api.meshData(m.name, m.hash);
  } catch (e) {
    if (seq.isStale(my)) return;
    if (viewer) viewer.stop();
    // 画布必须收掉：它还留着上一个模型的最后一帧，亮着就是拿旧图冒充新模型。
    foldStage();
    status("这个模型暂时画不出来，原因写在下面。");
    el("meshTech").innerHTML = `<details open><summary>为什么（给排查的人看）</summary><p class="dim">${esc(
      errText(e),
    )}</p></details>`;
    return;
  }
  if (seq.isStale(my)) return; // 已经切到别的模型了
  let v;
  try {
    v = ensure();
  } catch (e) {
    foldStage();
    status(`这台机器开不了 3D 预览：${errText(e)}`);
    return;
  }
  v.onlost = () => {
    seq.next();
    status("显卡上下文被系统收回了，重新点一下这个模型就能再看。");
  };
  try {
    v.load(data);
  } catch (e) {
    // 缓冲长度对不上是数据/契约问题，别把锅甩给显卡。
    foldStage();
    status(`这个模型的顶点数据对不上：${errText(e)}`);
    return;
  }
  if (seq.isStale(my)) return; // 上面这些是同步的，但 load 里可能已经换人了
  status("");
  el("meshMeta").textContent = `${num(data.vertexCount)} 个顶点 · ${num(data.faceCount)} 个三角面`;
  el("meshTech").innerHTML = techHtml(data);
}

/// 收起立体面板。必须同时把序号推走：否则上一次点击还在飞的 mesh_data 回包
/// 会通过 guard，把旧模型画进已经隐藏的面板里，还占着显存和 rAF。
export function hideMeshes() {
  seq.next();
  el("secMesh").hidden = true;
  if (viewer) viewer.stop();
}

/// 画不出时的样子：画布收掉，但面板不消失，理由就写在这一栏里。
/// 文案来自 lib/detailState.js 的 absencesOf —— 和下面「缺什么」里那条是同一句，
/// 不在这里另编一套原因，否则两处口径迟早分家。
function paintEmpty(why) {
  el("meshCanvas").hidden = true;
  el("meshPick").innerHTML = "";
  el("meshMeta").textContent = "";
  el("meshTech").innerHTML = "";
  status(why || "这一组没读到可画的网格。");
}

/// meshState = lib/detailState.js 算出来的 s.mesh。
export function showMeshes(meshState) {
  seq.next(); // 换资产就作废上一批在途请求
  meshes = (meshState && meshState.meshes) || [];
  el("secMesh").hidden = !(meshState && meshState.visible);
  // 没网格可画时整块收成一行理由：380px 的空盒子占着屏，看着像渲染坏了，
  // 实际是 84% 的资产组本来就没有网格——这不是异常，不该用异常的排版展示。
  el("secMesh").classList.toggle("folded", !meshes.length);
  if (!meshes.length) {
    if (viewer) viewer.stop();
    paintEmpty(meshState && meshState.why);
    return;
  }
  pick(Math.min(Math.max(meshState.active ?? 0, 0), meshes.length - 1));
}

/// 把候选贴图套到当前显示的模型上（只换显存里的拷贝）。
/// 没有正在显示的网格（viewer 未建）就如实回 false，调用方不必猜。
export function applyTexture(dataUrl) {
  if (!viewer) return false;
  viewer.setTexture(dataUrl);
  return true;
}
