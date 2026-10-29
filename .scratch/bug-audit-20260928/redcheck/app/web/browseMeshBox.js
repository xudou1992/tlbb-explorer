// 浏览视图右栏的网格灰模盒子：树里选中 .mesh 文件时，在这里画一个
// 可旋转/缩放的 WebGL 灰模。渲染器与资产视图是同一个 MeshViewer，
// 字节契约也是同一个 lib/meshLayout.js——只有外壳是自己的。
//
// 为什么不复用 mesh.js 那块面板：mesh.js 挂在 index.html 写死的一串 id 上
// （secMesh / meshCanvas / meshState…），那是资产视图的地盘；浏览右栏的预览区
// 是每次点击都重建的 bfPreview，往那套 id 里塞等于让两个视图抢同一块画布。
// 所以这里自己长一套 DOM，但绝不给节点起 el("meshCanvas") 这种重名 id。
//
// 节点全部 JS 动态创建、不进 index.html：这样 browseDom.test.js 那条
// 「browse.js 里 el() 引用的 id 都在 index.html」的防呆不用开洞。
//
// 本文件不 import api.js（它顶层就要摸 window，node 里 import 不了）：
// 取数函数由 browse.js 在建盒子时注入，纯逻辑部分因此能在 node --test 里直接测。

import { esc, num, errText } from "./ui.js";
import { MeshViewer } from "./mesh-viewer.js";
import { makeSeq } from "./lib/seq.js";

const CANVAS_ID = "browseMeshCanvas";

/// 浏览树里这条是不是网格文件。kind 是后端名表给的结论（"mesh"）；
/// 无名文件 kind 是空串，退回扩展名 / 树行名后缀——这些仍是客户端原文证据，
/// 不是猜。第一版只认 .mesh：.mdl 是模型组装文件，前端没有它的组装契约
/// （mesh_data 只解单一网格），硬把它当网格解只会画出错误的东西，宁缺毋假。
export function isMeshEntry(entry) {
  if (!entry) return false;
  if (entry.kind === "mesh") return true;
  const ext = String(entry.ext || "").replace(/^\./, "").toLowerCase();
  if (ext === "mesh") return true;
  return String(entry.name || "").toLowerCase().endsWith(".mesh");
}

/// mesh_data 两个入参各是什么角色：hash 才是定位键（Rust 侧按 hash 直接命中
/// 记录再解几何），name 只在出错文案里当个称呼。无名文件没有路径，
/// 就用树里那行名字（编号[.扩展名]）；两个都空时后端会管它叫「这个网格」。
export function meshDataRequestOf(entry) {
  return {
    name: entry?.path || entry?.name || "",
    hash: entry?.hash || null,
  };
}

/// 技术栏的四行。口径与资产视图 mesh.js 的 techHtml 一字不差（同一份回包、
/// 同一套说法），但少了两行：「客户端路径」和「顶点 / 三角面」——那两样在
/// 浏览右栏已经说过（bfMeta 和 meta 行），同一件事不说两遍。
export function meshTechRows(d) {
  return [
    ["表面朝向", d.hasNormals ? "文件里带着" : "文件里没读到，明暗按面自己算"],
    ["贴图坐标", d.hasUvs ? "读到了" : "没读到"],
    ["材质槽数", d.submeshCount],
    ["还没读懂的字节", `顶点之后 ${num(d.middleBytes)} · 结尾 ${num(d.trailingBytes)}`],
  ];
}

/// 建一个灰模盒子。loadData 即 api.meshData（browse.js 注入），签名 (name, hash)。
export function createBrowseMeshBox(loadData) {
  const seq = makeSeq();
  let root = null;
  let stage = null;
  let canvas = null;
  let statusEl = null;
  let metaEl = null;
  let whyEl = null;
  let whyText = null;
  let techEl = null;
  let viewer = null;

  function ensureDom() {
    if (root) return;
    root = document.createElement("div");
    metaEl = document.createElement("p");
    metaEl.className = "dim";
    stage = document.createElement("div");
    stage.className = "mesh-stage";
    canvas = document.createElement("canvas");
    canvas.id = CANVAS_ID;
    canvas.setAttribute("aria-label", "网格灰模预览");
    statusEl = document.createElement("p");
    statusEl.className = "mesh-state";
    statusEl.hidden = true;
    const hint = document.createElement("p");
    hint.className = "mesh-hint";
    hint.textContent = "按住拖动旋转 · 滚轮远近 · 双击回到正面";
    stage.append(canvas, statusEl, hint);
    whyEl = document.createElement("details");
    whyEl.hidden = true;
    const summary = document.createElement("summary");
    summary.textContent = "为什么（给排查的人看）";
    whyText = document.createElement("p");
    whyText.className = "dim";
    whyEl.append(summary, whyText);
    techEl = document.createElement("dl");
    techEl.className = "tech";
    root.append(metaEl, stage, whyEl, techEl);
  }

  function status(msg) {
    statusEl.textContent = msg || "";
    statusEl.hidden = !msg;
  }

  /// 收/放 380px 的画布盒。取数中和失败时都收：折着的时候画布亮着上一份
  /// 顶点的最后一帧，等于拿旧图冒充新文件（mesh.js 失败路径上同一个道理）。
  function setFolded(on) {
    stage.classList.toggle("bm-folded", on);
  }

  function fail(head, detail) {
    setFolded(true);
    status(head);
    whyText.textContent = detail;
    whyEl.hidden = false;
  }

  async function show(host, entry) {
    const my = seq.next(); // 换了选择就作废上一次还在飞的取数
    ensureDom();
    host.append(root); // 中途可能被别的选择摘走：同一块画布挂回去接着用
    setFolded(true);
    status("正在从客户端取这个网格的顶点…");
    metaEl.textContent = "";
    techEl.innerHTML = "";
    whyEl.hidden = true;
    let data;
    try {
      const req = meshDataRequestOf(entry);
      data = await loadData(req.name, req.hash);
    } catch (e) {
      if (seq.isStale(my)) return;
      if (viewer) viewer.stop();
      fail("这个网格暂时画不出来，原因写在下面。", errText(e));
      return;
    }
    if (seq.isStale(my)) return;
    // 必须先放出来再建上下文/量尺寸：折着（display:none）的画布量不到宽高，
    // 首帧会画进 1×1 的视口里（mesh.js 的 pick 为此先 unhide 再 ensure，同一个坑）。
    setFolded(false);
    try {
      if (!viewer) viewer = new MeshViewer(canvas);
    } catch (e) {
      setFolded(true);
      status(`3D 预览起不来：${errText(e)}`);
      return;
    }
    viewer.onlost = () => {
      // 显卡上下文被收回后 draw 会静默变空操作，必须收起来说一句话。
      seq.next();
      setFolded(true);
      status("显卡上下文被系统收回了，重新点一下这个文件就能再看。");
    };
    try {
      viewer.load(data);
    } catch (e) {
      // 缓冲长度对不上是数据/契约问题（lib/meshLayout.js 拦的），别把锅甩给显卡。
      setFolded(true);
      status(`这个网格的顶点数据对不上：${errText(e)}`);
      return;
    }
    if (seq.isStale(my)) return;
    status("");
    metaEl.textContent = `${num(data.vertexCount)} 个顶点 · ${num(data.faceCount)} 个三角面`;
    techEl.innerHTML = meshTechRows(data)
      .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
      .join("");
  }

  /// 右栏换内容（点了文件夹 / 非网格文件 / 换了 data 包）就收摊：作废在途
  /// 取数、停掉动画、把节点从预览区摘下来。viewer 不销毁——WebGL 上下文
  /// 整个浏览视图只建一次，换文件只是换缓冲，与 mesh.js 的口径一致。
  function retire() {
    seq.next();
    if (viewer) viewer.stop();
    if (root) root.remove();
  }

  return { show, retire };
}
