// 立体模型面板：WebGL 上下文只建一次，换资产只是换缓冲。
// 只有一个网格时不显示选择筹码；多个网格时默认自动加载第一个，第一眼就能看到形状。
//
// 状态由 lib/detailState.js 算好交进来（{ visible, meshes }），这里只管取数和画。

import { el, esc, num, errText } from "./ui.js";
import * as api from "./api.js";
import { MeshViewer } from "./mesh-viewer.js";
import { makeSeq } from "./lib/seq.js";
import { evidenceShort, layerChipLabels } from "./lib/layerChips.js";

let viewer = null;
const seq = makeSeq();
let meshes = [];
let current = -1;
/// 多件模型：画布一次画整组，`current` 只决定「下面贴图栏看哪一件」。
/// 单件模型仍走原来的 pick→load 路径（骨线、单张试贴都保持原样）。
let partsMode = false;
let partPlans = [];
let partStats = null;
/// 当前显示哪份网格变了就通知一声：贴图候选栏要把这份网格的榜排到第一份。
let meshChanged = null;

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

/// 详情可以停在别的标签加载，画布在隐藏状态下量到的是 1x1；切回预览标签时
/// 调这一下重新量视口并补一帧，不然网格永远停在 1 像素里（2026-10-07 验收现场）。
export function remesh() {
  if (!viewer) return;
  viewer.resize();
  viewer.draw();
}

/// 把立体区收成一行：没有画面可看时（无网格 / 取数失败 / 数据对不上），
/// 380px 的空盒子只是占屏，收起来让原因文字自己说话。
function foldStage() {
  el("secMesh").classList.add("folded");
  el("meshCanvas").hidden = true;
}

/// 部件筹码只显示公共前缀之后的短名（`_a`/`_b`、`yifu_001`），全名在 title 里。
/// 满屏 `w1351_npc_attack_dahuangfeng02_a.mesh` 会把标题和画布一起挤变形。
function partShortLabel(m) {
  const base = String((m && (m.label || m.name)) || "")
    .split("/")
    .pop()
    .replace(/\.mesh$/i, "");
  if (meshes.length < 2) return base;
  let prefix = base;
  for (const x of meshes) {
    const b = String((x && (x.label || x.name)) || "")
      .split("/")
      .pop()
      .replace(/\.mesh$/i, "");
    while (prefix && !b.startsWith(prefix)) prefix = prefix.slice(0, -1);
  }
  prefix = prefix.replace(/[_\-.]+$/, "");
  const short = prefix ? base.slice(prefix.length).replace(/^[_\-.]+/, "") : base;
  return short || base;
}

function paintPick() {
  const node = el("meshPick");
  node.innerHTML = "";
  if (meshes.length < 2) return;
  meshes.forEach((m, k) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "chip" + (k === current ? " on" : "");
    b.textContent = partShortLabel(m);
    b.title = m.name;
    b.onclick = () => pick(k);
    node.appendChild(b);
  });
}

/// 分层筹码：`全部` + 每层一个。点一层就只画那层——分层是「哪段几何配哪张图」
/// 的推断，配上「只看这一层」才能用眼睛核出配错没配错（用户 2026-10-27 的要求）。
let soloIndex = null;

function paintLayers(plan) {
  const box = el("meshLayers");
  if (!box) return;
  const labels = layerChipLabels(plan);
  soloIndex = null;
  if (!labels.length) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  const chips = ['<button type="button" class="chip on" data-li="">全部</button>'];
  for (const c of labels) {
    chips.push(
      `<button type="button" class="chip" data-li="${c.k}" title="${esc(c.title)}">${esc(c.name)}${c.seg ? ` <span class="dim">${esc(c.seg)}</span>` : ""}</button>`,
    );
  }
  box.innerHTML = chips.join("");
  box.hidden = false;
  box.onclick = (e) => {
    const b = e.target.closest("button[data-li]");
    if (b) soloLayer(b.dataset.li);
  };
}

/// 只看某一层（null = 全部）。整组模式下只作用于当前件。
export function soloLayer(i) {
  if (!viewer) return false;
  soloIndex = i == null || i === "" ? null : Number(i);
  if (partsMode) viewer.setPartLayerSolo(current, soloIndex);
  else viewer.setLayerSolo(soloIndex);
  const box = el("meshLayers");
  if (box) {
    const want = soloIndex == null ? "" : String(soloIndex);
    for (const b of box.querySelectorAll("button[data-li]")) {
      b.classList.toggle("on", String(b.dataset.li) === want);
    }
  }
  return true;
}

async function pick(k) {
  if (partsMode) {
    selectPart(k); // 整组模式：筹码只切贴图栏，不重装几何
    return;
  }
  current = k;
  partsMode = false;
  planSeq++; // 换网格：在途的分层刷新不能再落到新网格上
  texturePlanObserver?.(null); // 新计划回来前先按整组列，别拿上一只的槽名过滤
  meshChanged?.((meshes[current] && meshes[current].name) || "");
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
  paintLayers(null); // 换网格先收旧层筹码：分层计划回来前不能让人点到上一只的层
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
  // 骨头是绑定姿态上的附加线。取不到、解不出、空表都不挡灰模，也不另开错误。
  let bones = null;
  try {
    bones = await api.meshBoneLines(m.name, m.hash);
  } catch {
    bones = null;
  }
  if (seq.isStale(my)) return;
  let v;
  try {
    v = ensure();
  } catch (e) {
    foldStage();
    status(`3D 预览起不来：${errText(e)}`);
    return;
  }
  v.onlost = () => {
    seq.next();
    status("显卡上下文被系统收回了，重新点一下这个模型就能再看。");
  };
  try {
    v.load(data, bones);
  } catch (e) {
    // 缓冲长度对不上是数据/契约问题，别把锅甩给显卡。
    foldStage();
    status(`这个模型的顶点数据对不上：${errText(e)}`);
    return;
  }
  if (seq.isStale(my)) return; // 上面这些是同步的，但 load 里可能已经换人了
  status("");
  el("meshMeta").textContent = `${num(data.vertexCount)} 个顶点 · ${num(data.faceCount)} 个三角面`;
  el("meshMeta").title = "";
  el("meshTech").innerHTML = techHtml(data);
  if (m.sidecar) {
    el("meshMeta").textContent += " · 变体网格（sidecar）";
    el("meshTech").innerHTML +=
      `<div><dt>身份来源</dt><dd>sidecar（只读覆盖，resources.db 未改）</dd></div>`;
  }
  // 「加载即贴」：这格槽位有人工确认过的贴图就直接套上——确认层存在的意义就是
  // 让确认的成果持久，不该每次开模型都手动再套一遍。查不到（没确认过）不吭声；
  // 解不开会 reject，同样静默跳过：覆盖表是加分项，绝不能挡灰模。
  let applied = false;
  // 材质表里没有颜色图（水波/特效件）：这不是失败，别再拿候选榜去试贴——那只会把
  // 一张不相干的图盖到着色器件上。人工确认过的覆盖表仍然照旧生效。
  let noColorExplained = false;
  // 分层贴图优先：这只网格有多个子网格时，基础色只属于其中一段，特效层各有
  // 自己的 mask/颜色图。把一张基础色盖到全部子网格上，真窗口里就是「好多贴图
  // 一起糊在身上」（2026-10-26 用户现场指出）。后端按 `.mtl` 顺序给出分层计划；
  // 给不出时再退回单张老路。
  if (texturePlanProvider) {
    try {
      const plan = await texturePlanProvider(m.name, m.hash);
      if (seq.isStale(my)) return;
      if (plan && Array.isArray(plan.layers) && plan.layers.length) {
        v.setTextureLayers(plan.layers);
        paintLayers(plan);
        const fx = Number(plan.effectLayers) || 0;
        const op = Number(plan.opaqueLayers) || 0;
        const extra = [fx ? `${fx} 层特效` : "", op ? `${op} 层材质` : ""].filter(Boolean);
        el("meshMeta").textContent +=
          extra.length
            ? ` · 按子网格分层：基础 + ${extra.join(" + ")}（层次按材质表排）`
            : " · 按子网格分层：基础层";
        const evTxt = evidenceShort(plan.evidence);
        if (evTxt) el("meshMeta").textContent += ` · ${evTxt}`;
        if (plan.note) el("meshMeta").title = plan.note;
        texturePlanObserver?.(plan);
        applied = true;
      } else if (plan && plan.note) {
        // 有材质、但没有颜色图（水波/特效件）：不是解析失败，界面要说清为什么是灰的。
        el("meshMeta").textContent += ` · ${plan.note}`;
        el("meshMeta").title = plan.note;
        texturePlanObserver?.(plan);
        noColorExplained = true;
      }
    } catch {
      // 分层计划失败不挡模型：下面单张覆盖表/试贴仍可工作。
    }
  }
  if (!applied) try {
    const ov = await api.meshTextureOverride(m.name);
    if (seq.isStale(my)) return; // 等覆盖图解完的空档可能已经换了模型
    if (ov && ov.png) {
      v.setTexture(ov.png);
      el("meshMeta").textContent +=
        ov.source === "auto"
          ? ` · 已自动对上客户端文件${ov.autoPath ? `（${ov.autoPath}）` : "（convert/dxt）"}`
          : " · 已套用人工确认的贴图";
      applied = true;
    }
  } catch {
    // 查询失败不提示：槽位状态以贴图试贴区的 🟢/🟡 为准，这里不重复报错。
  }
  if (applied || noColorExplained || !trialProvider) return;
  // 🟢 没有才轮到试贴。试贴必须**在标题里写明白未确认**——榜首不是答案，
  // 把它悄悄套上就等于让灰模变成「看起来已解决」。
  try {
    const t = await trialProvider(m.name);
    if (seq.isStale(my)) return;
    if (t && t.png) {
      v.setTexture(t.png);
      el("meshMeta").textContent += ` · 已套试贴：${t.label}（未确认，不是客户端认定的那张）`;
    } else if (t && t.skip) {
      el("meshMeta").textContent += ` · 没套试贴：${t.skip}`;
    }
  } catch {
    // 试贴是加分项，取不到就留灰模，不报错挡渲染。
  }
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
  partsMode = false;
  el("meshCanvas").hidden = true;
  // 画不出就收成一行理由：空盒子配「放大」按钮，点了也只会被拒绝。
  el("secMesh").classList.add("folded");
  el("meshPick").innerHTML = "";
  el("meshMeta").textContent = "";
  el("meshTech").innerHTML = "";
  paintLayers(null);
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
    partsMode = false;
    if (viewer) viewer.stop();
    paintEmpty(meshState && meshState.why);
    return;
  }
  // LOD 件和主干一起画会打架：有主件时把它们从预览里剔掉，但保留单件模型。
  const noLod = meshes.filter((m) => !/(_opt|_lod)(\.[^.]+)?$/i.test(String(m.label || m.name || "")));
  if (noLod.length) meshes = noLod;
  const active = Math.min(Math.max(meshState.active ?? 0, 0), meshes.length - 1);
  // 多件模型一次画整组（身体+翅膀、衣服+脸），筹码只切当前贴图栏；
  // 没有分层提供者（独立网格面板）仍走单件老路。
  if (meshes.length > 1 && texturePlanProvider) {
    loadParts(active);
    return;
  }
  partsMode = false;
  pick(active);
}

/// 整组多件模型：每件自己的几何 + 自己的分层贴图，一次画完。
async function loadParts(active = 0) {
  current = Math.min(Math.max(active, 0), meshes.length - 1);
  planSeq++;
  texturePlanObserver?.(null);
  meshChanged?.((meshes[current] && meshes[current].name) || "");
  el("meshCanvas").hidden = false;
  el("secMesh").classList.remove("folded");
  paintPick();
  status("正在取整组网格…");
  el("meshMeta").textContent = "";
  el("meshMeta").title = "";
  el("meshTech").innerHTML = "";
  paintLayers(null); // 新件还没到：先收掉上一件的层筹码，免得人点到旧层的按钮
  const my = seq.next();
  const settled = await Promise.allSettled(meshes.map((m) => api.meshData(m.name, m.hash)));
  if (seq.isStale(my)) return;
  const ok = [];
  const failed = [];
  settled.forEach((r, i) => {
    if (r.status === "fulfilled") ok.push({ mesh: meshes[i], data: r.value });
    else failed.push(meshes[i]);
  });
  if (!ok.length) {
    foldStage();
    status("这一组网格都取不出来，画不出整组；原因在「缺失资源」里。");
    return;
  }
  if (ok.length === 1) {
    partsMode = false;
    await pick(meshes.indexOf(ok[0].mesh));
    return;
  }
  let v;
  try {
    v = ensure();
  } catch (e) {
    foldStage();
    status(`3D 预览起不来：${errText(e)}`);
    return;
  }
  v.onlost = () => {
    seq.next();
    status("显卡上下文被系统收回了，重新点一下这个模型就能再看。");
  };
  try {
    v.loadParts(ok.map((o) => o.data));
  } catch (e) {
    // 整组装不起来就退回单件；画布不能停在半个黑屏。
    partsMode = false;
    status(`整组画不出来，先看单件：${errText(e)}`);
    await pick(meshes.indexOf(ok[0].mesh));
    return;
  }
  partsMode = true;
  meshes = ok.map((o) => o.mesh);
  current = Math.min(current, meshes.length - 1);
  partPlans = new Array(ok.length).fill(null);
  partStats = {
    v: ok.reduce((a, o) => a + (o.data.vertexCount || 0), 0),
    f: ok.reduce((a, o) => a + (o.data.faceCount || 0), 0),
  };
  paintPick();
  el("meshTech").innerHTML =
    `<details><summary>整组 ${ok.length} 件（${failed.length ? `失败 ${failed.length} 件` : "全部读到"}）</summary><p class="dim">` +
    ok
      .map(
        (o) =>
          `${esc(o.mesh.label || o.mesh.name)}：${num(o.data.vertexCount)} 顶点 / ${num(o.data.faceCount)} 面`,
      )
      .join("<br>") +
    `</p></details>`;
  const sidecarParts = meshes.filter((m) => m.sidecar).length;
  if (sidecarParts) {
    el("meshTech").innerHTML +=
      `<p class="dim">其中 ${sidecarParts} 件的身份来自 sidecar（只读覆盖，resources.db 未改）。</p>`;
  }
  // 几何先画灰色一帧，贴图逐件补上：不让大组的所有 PNG 卡住第一眼。
  const planJobs = await Promise.allSettled(ok.map((o) => texturePlanProvider(o.mesh.name, o.mesh.hash)));
  if (seq.isStale(my)) return;
  let layered = 0;
  planJobs.forEach((r, i) => {
    if (r.status === "fulfilled" && r.value && Array.isArray(r.value.layers) && r.value.layers.length) {
      partPlans[i] = r.value;
      v.setPartLayers(i, r.value.layers);
      layered++;
    }
  });
  // 分层取不到的件退回单张覆盖表（人工确认/自动同名槽），至少不空着。
  if (layered < ok.length && api.meshTextureOverride) {
    const fallbacks = await Promise.allSettled(
      ok.map((o, i) => (partPlans[i] ? Promise.resolve(null) : api.meshTextureOverride(o.mesh.name))),
    );
    if (!seq.isStale(my)) {
      fallbacks.forEach((r, i) => {
        if (r.status === "fulfilled" && r.value && r.value.png) {
          v.setPartSingleTexture(i, r.value.png);
        }
      });
    }
  }
  status(failed.length ? `整组 ${ok.length} 件已画；${failed.length} 件取不出来（不影响其余件）` : "");
  el("meshMeta").textContent = partsMetaText(layered > 0);
  el("meshMeta").title = (partPlans[current] && partPlans[current].note) || "";
  paintLayers(partPlans[current]);
  texturePlanObserver?.(partPlans[current] || null);
  meshChanged?.((meshes[current] && meshes[current].name) || "");
  v.draw();
}

function partsMetaText(layered = partPlans.some((p) => p && p.layers && p.layers.length)) {
  if (!partStats) return "";
  const cur = meshes[current];
  const sidecar = meshes.filter((m) => m.sidecar).length;
  const plan = partPlans[current];
  // 材质表里没有颜色图的件（水波/特效）：说清是着色器画的，不是加载失败。
  const explain = plan && plan.note && !(plan.layers || []).length ? "只有着色器（无颜色图）" : "";
  const bits = [
    `${num(partStats.v)} 个顶点`,
    `${num(partStats.f)} 个三角面`,
    `整组 ${meshes.length} 件`,
    cur ? `当前 ${partShortLabel(cur)}` : "",
    layered ? "分层贴图" : "",
    sidecar ? `${sidecar} 件 sidecar 网格` : "",
    explain,
  ].filter(Boolean);
  return bits.join(" · ");
}

/// 多件模式下切换当前件：只切下面贴图栏，不重装几何。
function selectPart(k) {
  if (!partsMode) return pick(k);
  current = Math.min(Math.max(k, 0), meshes.length - 1);
  paintPick();
  meshChanged?.((meshes[current] && meshes[current].name) || "");
  const plan = partPlans[current] || null;
  el("meshMeta").textContent = partsMetaText();
  el("meshMeta").title = (plan && plan.note) || "";
  paintLayers(plan);
  texturePlanObserver?.(plan);
}

/// 立体预览的「自动试贴」由详情页注册进来：mesh 面板不该认识候选榜的格式，
/// 它只问「这只网格该套哪张贴图试」，提供者回 `{png, label}` 或 `{skip: 原因}`。
/// 没有提供者（独立用 mesh 面板、或详情页还没拿到候选榜）就一直是灰模。
let trialProvider = null;
export function setTrialProvider(fn) {
  trialProvider = typeof fn === "function" ? fn : null;
}

/// 分层贴图提供者：详情页按当前 gid 向后端要「哪段子网格用哪张图」。
/// 没有提供者、或后端给不出（缺材质/基础色解不出）才回退到单张「加载即贴」。
let texturePlanProvider = null;
let texturePlanObserver = null;
let planSeq = 0;
export function setTexturePlanProvider(fn) {
  texturePlanProvider = typeof fn === "function" ? fn : null;
}

/// 分层计划拿到/失效时通知详情页：贴图槽清单要收窄到当前网格自己的材质表，
/// 不能把同组别的模型的贴图全摆出来让人标错。
export function setTexturePlanObserver(fn) {
  texturePlanObserver = typeof fn === "function" ? fn : null;
}

/// 确认/撤销一条槽位后重取分层计划：不能再用单张图把整只网格盖回去。
/// 返回后端计划（含 note），拿不到就返回 null，让调用方走单张老路。
export async function refreshTexturePlan() {
  if (!viewer || !texturePlanProvider || current < 0) return null;
  const name = currentMeshName();
  if (!name) return null;
  const idx = current;
  const my = ++planSeq;
  try {
    const plan = await texturePlanProvider(name, (meshes[current] && meshes[current].hash) || null);
    if (my !== planSeq || name !== currentMeshName() || idx !== current) return null;
    if (plan && Array.isArray(plan.layers) && plan.layers.length) {
      if (partsMode) {
        partPlans[idx] = plan;
        viewer.setPartLayers(idx, plan.layers);
        if (idx === current) paintLayers(plan);
      } else {
        viewer.setTextureLayers(plan.layers);
        paintLayers(plan);
      }
      texturePlanObserver?.(plan);
      return plan;
    }
  } catch {
    // 分层取不到就回退，调用方自己决定怎么显示。
  }
  texturePlanObserver?.(null);
  return null;
}

/// 贴图栏订阅「当前网格换了」：一份组常有多份网格，候选榜也各出一份，
/// 不跟着切的话人得自己在几份榜里找模型身上那一份。
export function onActiveMesh(fn) {
  meshChanged = typeof fn === "function" ? fn : null;
}

export function currentMeshName() {
  return (meshes[current] && meshes[current].name) || "";
}

/// 撤掉模型身上的贴图（人工确认的或试贴的），回到绑定姿态灰模。
/// 没有 viewer 就回 false，调用方自己决定要不要提示——不让人以为点了没反应。
export function clearMeshTexture() {
  if (!viewer) return false;
  if (partsMode) viewer.clearPartTextures();
  else viewer.clearTexture();
  paintLayers(null);
  return true;
}

/// 把候选贴图套到当前显示的模型上（只换显存里的拷贝）。
/// 多件模式只套当前这一件，别把别的件一起盖掉。
export function applyTexture(dataUrl) {
  if (!viewer) return false;
  if (partsMode) return viewer.setPartSingleTexture(current, dataUrl);
  viewer.setTexture(dataUrl);
  return true;
}

/// 分层模式下只换某条槽位的图；不是分层模式回 false，调用方走整张老路。
export function tryLayerTexture(slotName, dataUrl) {
  if (!viewer) return false;
  if (partsMode) return viewer.setPartLayerTexture(current, slotName, dataUrl);
  return viewer.setLayerTexture(slotName, dataUrl);
}

/// 诊断用：只画第 i 个子网格，null 复原。真窗口里用来分辨层次，不接界面。
export function debugSubmesh(index) {
  if (!viewer) return false;
  return viewer.setSubmeshOnly(index);
}
