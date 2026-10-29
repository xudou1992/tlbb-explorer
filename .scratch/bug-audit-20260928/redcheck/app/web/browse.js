// 浏览视图：左栏选 data，中栏文件夹树，右栏预览/导出。
// 树的纯逻辑（建树/过滤/收集）在 lib/browseState.js，这里只做渲染与接线。
// 纪律与全库一致：树里只摆客户端原文路径，无名文件进「(未命名)」桶，
// 文件名就是编号，不编造。

import { el, esc } from "./ui.js";
import * as api from "./api.js";
import { state, saveState } from "./state.js";
import {
  buildTree,
  childrenOf,
  searchTree,
  countTree,
  exportTargetOf,
  fmtSize,
  kindZh,
} from "./lib/browseState.js";
import { createBrowseMeshBox, isMeshEntry } from "./browseMeshBox.js";

let paksLoaded = false;
let clientRoot = "";
let tree = null; // 当前 pak 的树根
let currentPak = "";
let selectedDir = null; // 选中的目录节点
let selectedFile = null; // 选中的文件条目
let previewSeq = 0; // 作废迟到的预览回包
let pickedRow = null; // 树里高亮的那一行
let meshBox = null; // 右栏灰模盒子，懒建（见 showBrowseMesh）
let pakSeq = 0; // openPak 的作废锁：连点两个 pak 时，先点的那份回包可能后到
let exporting = false; // 导出进行中：按钮不许被重新点亮，动作不许重入
let wired = false; // initBrowse 只接一遍事件

const IMAGE_KINDS = new Set(["texture", "webp", "jpeg", "png"]);

// ---- 入口：切到浏览视图时拉一次 pak 清单；上次的 pak 自动接上 ----
export async function openBrowse() {
  if (paksLoaded) return;
  paksLoaded = true;
  try {
    const reply = await api.browsePaks();
    clientRoot = reply.root;
    el("browseRoot").textContent = `客户端目录：${clientRoot}`;
    renderPaks(reply.paks);
    if (state.browsePak && reply.paks.some((p) => p.name === state.browsePak)) {
      openPak(state.browsePak);
    }
  } catch (e) {
    el("browseRoot").textContent = String(e?.message || e);
  }
}

/// 视图切换（顶栏「浏览 / 资产」两个标签）。
export function showTab(v) {
  el("browseView").hidden = v !== "browse";
  el("assetsView").hidden = v !== "assets";
  el("tabBrowse").classList.toggle("on", v === "browse");
  el("tabAssets").classList.toggle("on", v === "assets");
  if (v === "browse") openBrowse();
}

function renderPaks(cards) {
  const host = el("pakCards");
  host.innerHTML = "";
  for (const card of cards) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pakcard";
    const strong = document.createElement("strong");
    strong.textContent = card.name;
    const sub = document.createElement("span");
    sub.className = "dim";
    sub.textContent = `${fmtSize(card.sizeBytes)} · 约 ${card.records.toLocaleString()} 个文件`;
    btn.append(strong, sub);
    btn.addEventListener("click", () => openPak(card.name));
    host.append(btn);
  }
}

async function openPak(name) {
  const my = ++pakSeq;
  previewSeq++; // 旧包在途的预览回包不能画进新包的面板——哪怕面板此刻是藏着的
  currentPak = name;
  tree = null;
  selectedDir = null;
  selectedFile = null;
  pickedRow = null; // 旧树的高亮行已经随 DOM 一起拆了，引用一并作废
  state.browsePak = name;
  saveState();
  el("treeFilter").value = "";
  el("treeFilter").hidden = false;
  el("exportReport").textContent = "";
  el("exportBox").hidden = true; // 新包还没就绪，导出框先收起来，成功后再亮
  el("treeBody").innerHTML = "";
  appendMsg(el("treeBody"), `正在打开 ${name}…第一次要对一遍名字表，稍等几秒。`);
  el("treeTitle").textContent = `正在打开 ${name}…`;
  updateExportButton();
  el("browseGuide").hidden = false;
  el("browseFilePane").hidden = true;
  retireBrowseMesh(); // 换包后旧网格的取数一律作废，不能画进新包的右栏
  try {
    const reply = await api.browseTree(name);
    // 期间又点了别的 pak：这份是旧账。树的归属必须跟 currentPak 对上，
    // 不然拿 A 的树配 B 的包名，导出和预览全都会张冠李戴。
    if (my !== pakSeq) return;
    tree = buildTree(reply.entries);
    el("treeTitle").textContent =
      `${name} · ${reply.named.toLocaleString()} 个有名字 / 共 ${reply.total.toLocaleString()} 条`;
    el("exportDest").value = defaultDest();
    el("exportBox").hidden = false;
    showDir(tree);
  } catch (e) {
    if (my !== pakSeq) return; // 迟到的失败也一样，别去动新包的界面
    // 后端树有进程级缓存，重试几乎必然命中缓存秒回——自动补一次，别把
    // 「偶发失败」留给用户面对一棵死树和死搜索框。
    setTimeout(() => {
      if (my === pakSeq && tree === null) openPak(name);
    }, 2500);
    el("treeTitle").textContent = `${name} · 打开失败，正在自动重试`;
    el("treeFilter").hidden = true; // 没有树可搜，搜索框空挂着只会让人白打字
    el("treeBody").innerHTML = "";
    appendMsg(el("treeBody"), String(e?.message || e));
  }
}

/// 切换到某个目录：重画中栏 + 右栏显示文件夹信息。
function showDir(node) {
  selectedDir = node;
  selectedFile = null;
  el("treeBody").innerHTML = "";
  renderDirInto(node, el("treeBody"));
  showDirDetail(node);
  updateExportButton();
}

function renderDirInto(node, host) {
  const { rows, hidden } = childrenOf(node);
  const ul = document.createElement("ul");
  ul.className = "tree";
  for (const row of rows) {
    ul.append(row.type === "dir" ? dirRow(row.node) : fileRow(row.node));
  }
  host.append(ul);
  if (hidden > 0) {
    appendMsg(host, `这一层还有 ${hidden.toLocaleString()} 项没列出来，用上面的搜索框按路径找。`);
  } else if (!rows.length) {
    // 整包一条都没读到时中栏不能是一片空白，得有一句话说清为什么没东西可点。
    appendMsg(host, "这一层没有任何文件。");
  }
}

function dirRow(node) {
  const li = document.createElement("li");
  li.className = "tree-dir";
  const row = document.createElement("div");
  row.className = "tree-row dir-row";
  row.innerHTML =
    '<span class="caret" aria-hidden="true">▸</span><span class="tname"></span><span class="tcount"></span>';
  row.querySelector(".tname").textContent = node.name;
  row.querySelector(".tcount").textContent = `(${(node.dirs.size + node.files.length).toLocaleString()})`;

  const kids = document.createElement("div");
  kids.className = "tree-kids";
  kids.hidden = true;
  const caret = row.querySelector(".caret");
  const expand = () => {
    if (kids.hidden && !kids.dataset.built) {
      renderDirInto(node, kids);
      kids.dataset.built = "1";
    }
    kids.hidden = !kids.hidden;
    caret.textContent = kids.hidden ? "▸" : "▾";
  };
  caret.addEventListener("click", (e) => {
    e.stopPropagation();
    expand();
  });
  row.addEventListener("click", () => {
    pick(row);
    // 点文件夹 = 选中它：selectedDir 不改的话，导出按钮上算的还是上一个
    // 目录（多半是整包），右栏明明摆着这个文件夹的信息，点导出却导了别的。
    selectedDir = node;
    selectedFile = null;
    showDirDetail(node);
    updateExportButton();
    if (kids.hidden) expand();
  });
  li.append(row, kids);
  return li;
}

function fileRow(entry) {
  const li = document.createElement("li");
  li.className = "tree-file";
  const row = document.createElement("div");
  row.className = "tree-row";
  row.innerHTML = '<span class="tname"></span><span class="tcount"></span>';
  row.querySelector(".tname").textContent = entry.name;
  row.querySelector(".tcount").textContent = fmtSize(entry.size);
  row.addEventListener("click", () => {
    pick(row);
    selectedFile = entry;
    showFileDetail(entry);
    updateExportButton();
  });
  li.append(row);
  return li;
}

function pick(row) {
  if (pickedRow) pickedRow.classList.remove("picked");
  pickedRow = row;
  row.classList.add("picked");
}

// ---- 右栏：文件夹 / 文件详情 ----

// 网格灰模：3D 与取数细节全在 browseMeshBox.js，这里只认类型分支。
// 任何非网格内容占住预览区之前都必须 retire——不然上一次点击还在飞的
// 网格回包会把画布重新挂回预览区，盖住刚选的东西。

function retireBrowseMesh() {
  if (meshBox) meshBox.retire();
}

function showBrowseMesh(entry) {
  if (!meshBox) meshBox = createBrowseMeshBox(api.meshData);
  meshBox.show(el("bfPreview"), entry);
}

function showDirDetail(node) {
  previewSeq++; // 文件夹详情不是一种预览，是关掉预览：在途的贴图回包到了也不许画进来
  el("browseGuide").hidden = true;
  el("browseFilePane").hidden = false;
  const isRoot = node === tree;
  const c = countTree(node);
  el("bfName").textContent = isRoot ? currentPak : node.path;
  el("bfKind").textContent = "文件夹";
  el("bfMeta").innerHTML = metaRows([
    ["包含文件", `${c.files.toLocaleString()} 个（本层 ${(node.dirs.size + node.files.length).toLocaleString()} 项）`],
  ]);
  el("bfPreview").innerHTML = "";
  retireBrowseMesh();
  el("bfNote").textContent = "文件夹没有预览；点下面的导出可以把里面全部文件解包出来。";
}

async function showFileDetail(entry) {
  el("browseGuide").hidden = true;
  el("browseFilePane").hidden = false;
  el("bfName").textContent = entry.name;
  el("bfKind").textContent = entry.kind ? kindZh(entry.kind) : "未命名";
  el("bfMeta").innerHTML = metaRows([
    ["路径", entry.path || "没存路径，编号即身份"],
    ["大小", `${entry.size.toLocaleString()} 字节`],
    ["编号", entry.hash],
  ]);
  el("bfNote").textContent = "";
  // 领号要在所有分支之前：点文件夹、点非图片、点网格，一样都得作废上一张
  // 还在解码的贴图——不然它回来会把刚摆好的详情连锅端掉，重画成它的图。
  const seq = ++previewSeq;
  const host = el("bfPreview");
  host.innerHTML = "";
  retireBrowseMesh(); // 换了选择先收掉灰模盒子；选中的还是网格的话下面马上重新亮出来
  if (isMeshEntry(entry)) {
    // 灰模取数有自己的锁（盒子内部那把），这里领的号只为拦住贴图回包。
    el("bfNote").textContent = "灰模只有形状，没有贴图。";
    showBrowseMesh(entry);
    return;
  }
  // 类型明确不是图就不浪费一次解码；无名文件让后端嗅探，说不定是张图。
  if (entry.kind && !IMAGE_KINDS.has(entry.kind)) {
    // 不走 innerHTML 拼接：kindZh 今天只会吐固定词，但拼接点少一个是一个。
    const p = document.createElement("p");
    p.className = "dim";
    p.textContent = `这个类型（${kindZh(entry.kind)}）暂时没有预览，可以直接导出。`;
    host.append(p);
    return;
  }
  host.innerHTML = '<p class="dim">正在解码…</p>';
  try {
    const pv = await api.browsePreview(currentPak, entry.hash);
    if (seq !== previewSeq) return;
    host.innerHTML = "";
    if (pv.ok) {
      const img = document.createElement("img");
      img.className = "bp-img";
      img.src = pv.dataUrl;
      img.alt = entry.name;
      host.append(img);
    } else if (pv.reason) {
      appendMsg(host, pv.reason);
    }
    if (pv.info?.length) {
      const ul = document.createElement("ul");
      ul.className = "bp-info";
      for (const line of pv.info) {
        const li = document.createElement("li");
        li.textContent = line;
        ul.append(li);
      }
      host.append(ul);
    }
  } catch (e) {
    if (seq !== previewSeq) return;
    host.innerHTML = "";
    appendMsg(host, String(e?.message || e));
  }
}

// ---- 导出 ----

function defaultDest() {
  const base = clientRoot.replace(/[\\/]+$/, "");
  const pak = currentPak.replace(/\.pak$/i, "");
  // 默认导到客户端根下的 .scratch/unpacked/<pak>：.scratch 是既有产物区
  // （resources.db、预热缓存都在里面），后端允许写入；根内其他位置会被
  // 后端以「客户端目录只读」拒绝——默认值必须一填就过，不该必报错。
  return `${base}/.scratch/unpacked/${pak}`;
}

function updateExportButton() {
  const btn = el("exportGo");
  const t = exportTargetOf(selectedFile, selectedDir, tree);
  if (!t) {
    btn.textContent = "先在左边打开一个 data";
    btn.disabled = true;
    return;
  }
  if (exporting) return; // 导出进行中：按钮保持禁用，别被行点击重新点亮
  btn.disabled = false;
  if (t.kind === "file") {
    btn.textContent = "导出这个文件";
  } else if (t.kind === "dir") {
    btn.textContent = `导出这个文件夹（${t.files.toLocaleString()} 个文件）`;
  } else {
    btn.textContent = `导出整包（${t.files.toLocaleString()} 个文件）`;
  }
}

async function doExport() {
  // 目标与按钮吃同一份裁决（exportTargetOf）：按钮说导哪个，导的就是哪个。
  // exporting 同时拦键盘回车/连点——按钮的 disabled 挡不住编程式触发。
  const t = exportTargetOf(selectedFile, selectedDir, tree);
  if (!t || exporting) return;
  exporting = true;
  const dest = el("exportDest").value.trim();
  const btn = el("exportGo");
  btn.disabled = true;
  el("exportReport").textContent = "正在导出…";
  try {
    const rep = await api.browseExport(currentPak, t.hashes, dest);
    let text = `已导出 ${rep.written.toLocaleString()} 个文件到 ${rep.dest}`;
    const failCount = rep.failed.length + (rep.failedMore || 0);
    if (failCount) {
      text += `\n失败 ${failCount.toLocaleString()} 个${rep.failedMore ? "（下面只列前几条）" : ""}：`;
      text += `\n${rep.failed.slice(0, 5).join("\n")}`;
    }
    el("exportReport").textContent = text;
  } catch (e) {
    el("exportReport").textContent = String(e?.message || e);
  }
  exporting = false;
  // 收尾不直接亮按钮：导出期间用户可能换了选择甚至换了 pak，按现状重算。
  updateExportButton();
}

// ---- 小工具 ----

function metaRows(pairs) {
  // 键今天都是我们自己写的字面量，也照样过 esc：这个拼接点要保证往后塞
  // 什么都不会变成标签。值不走拼接，由下面的 textContent 落进去。
  const html = pairs
    .map(
      ([k]) =>
        `<div><dt>${esc(k)}</dt><dd></dd></div>`,
    )
    .join("");
  const wrap = document.createElement("dl");
  wrap.className = "tech";
  wrap.innerHTML = html;
  const dds = wrap.querySelectorAll("dd");
  pairs.forEach(([_, v], i) => {
    dds[i].textContent = v;
  });
  return wrap.innerHTML;
}

function appendMsg(host, text) {
  const p = document.createElement("p");
  p.className = "tree-msg";
  p.textContent = text;
  host.append(p);
}

// ---- 事件接线（app.js 启动时调一次；防呆：调两次也不能把事件接两遍）----
export function initBrowse() {
  // 双绑定不报错，只有「点一下当两下」的怪病——拦在这里比排查省事。
  if (wired) return;
  wired = true;
  el("tabBrowse").addEventListener("click", () => {
    state.view = "browse";
    saveState();
    showTab("browse");
  });
  el("tabAssets").addEventListener("click", () => {
    state.view = "assets";
    saveState();
    showTab("assets");
  });

  let filterTimer = 0;
  el("treeFilter").addEventListener("input", (e) => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => {
      if (!tree) {
        // 树还没就绪（打开失败/还在重试）时不许静默——静默就是「点搜索没反应」。
        el("treeBody").innerHTML = "";
        appendMsg(el("treeBody"), currentPak
          ? `「${currentPak}」还没就绪，等它打开后再搜。`
          : "先在左边打开一个 data 再搜索。");
        return;
      }
      const hits = searchTree(tree, e.target.value, 200);
      el("treeBody").innerHTML = "";
      if (hits === null) {
        // 清空搜索 = 回到整棵树。搜索已经把树的展开状态全冲掉了，
        // 回子目录的话用户就被困在那个目录里（树没有面包屑），一律回根。
        showDir(tree);
        return;
      }
      for (const f of hits) el("treeBody").append(fileRow(f));
      if (!hits.length) appendMsg(el("treeBody"), "没有命中，换个词试试。");
    }, 200);
  });

  el("exportGo").addEventListener("click", doExport);
}
