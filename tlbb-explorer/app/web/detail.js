// 详情页：只做两件事——把回包交给状态机算，然后把算出来的状态写进 DOM。
//
// 所有"哪些字段该出现、什么时候必须空"的判断都在 lib/detailState.js 里，
// 那边有 node --test 盯着（app/tests/detailState.test.js）。
// 这里刻意不做任何业务判断：判断留在能测的地方。

import { el, errText, num, chips } from "./ui.js";
import * as api from "./api.js";
import { state } from "./state.js";
import { makeSeq } from "./lib/seq.js";
import { empty, loading, failed, notReady, loaded, isNotReadyMsg } from "./lib/detailState.js";
import { titleHtml } from "./lib/wording.js";
import { showMeshes, hideMeshes, applyTexture } from "./mesh.js";
import { MeshViewer } from "./mesh-viewer.js";
import { makePoseGate, poseNote, nextFrame, PLAY_STEP_MS, clampFrame } from "./lib/animPose.js";
import { texBlock } from "./lib/textureState.js";
import {
  initTabs,
  showTabPane,
  paintSide,
  paintSkeleton,
  clearSkeleton,
  paintAnimation,
  clearAnimation,
  paintEffect,
  clearEffect,
  paintMaterial,
  clearMaterial,
  onTabOpen,
  paintTabCounts,
  paintRing,
  paintFiles,
  paintRaw,
  paintFixBar,
} from "./panels.js";
const seq = makeSeq();

/// 把一份状态整个铺到屏幕上。每个可写的位置都要出现在这里——
/// 漏一个就是"上一条资产的内容留在屏上"那种事故。
function paint(s) {
  el("secTex").hidden = true; // 每次铺屏先收起，loaded 后 paintTex 再决定要不要出现
  el("guide").hidden = s.phase !== "empty";
  el("body").hidden = s.phase === "empty";
  el("detailPane")?.scrollTo?.({ top: 0 });

  // 长资产名要按 `_` 分节断行，纯 textContent 铺不出 <wbr>；转义在 titleHtml 里做了。
  el("dName").innerHTML = titleHtml(s.title);
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
    ? "图是现场从客户端数据里解出来的；没解出来的不摆在这里，原因写在「缺失资源」里。"
    : "";
  // 预览标签页也得有话说：贴图和解出的模型都没有时，空着会让人以为界面坏了。
  el("pvEmpty").hidden = s.previews.visible || (s.mesh && s.mesh.hasView);

  if (s.mesh.visible) showMeshes(s.mesh);
  else hideMeshes();
}

/// 清空「只有 loaded 分支才会铺」的那几块：文件清单、原始数据、环形图、标签计数。
///
/// paint() 覆盖不到它们（数据来自 asset_inspect 回包，失败时根本没有回包），
/// 于是上一条资产的清单会留在屏上、标签还亮着——看着就像这条资产真有这些文件。
/// 每个「没铺成」的出口（未读到 / 读取失败 / 收回初始态）都必须走这里收干净。
function clearTabPanes() {
  el("fileList").innerHTML = "";
  el("fileCount").textContent = "";
  el("rawJson").textContent = "";
  el("ringBox").innerHTML = "";
  el("tabRelCount").textContent = "";
  el("tabMissCount").textContent = "";
  el("texSlots").innerHTML = "";
  el("texCand").innerHTML = "";
  texReply = null;
  clearSkeleton();
  clearAnimation();
  animReply = null;
  animFrame = 0;
  poseReset();
  clearEffect();
  fxReply = null;
  clearMaterial();
  mtlReply = null;
  showTabPane("preview"); // 停在有话说的那一页，别停在一页残留
}

export async function showDetail(gid, retried = 0) {
  if (!gid) return;
  state.selected = gid;
  document.querySelectorAll(".row-item").forEach((n) => n.classList.toggle("on", Number(n.dataset.gid) === gid));
  const my = seq.next();
  // 换一件资产：骨架 / 动作 / 特效三页立刻清空。真窗口里撞到过——上一件的衣服
  // 写着「这一组旁边没有 ani/ 目录」，而新点的这只怪其实有 15 条动作，
  // 旧文字不清就等于给新资产编一句假话。同一件的重刷不清（免得闪）。
  if (gid !== paintedGid) {
    animReply = null;
    fxReply = null;
    mtlReply = null;
    animFrame = 0;
    clearSkeleton();
    clearAnimation();
    poseReset(); // 预览与在途状态跟着资产走：旧怪的姿势一格都不许留给新怪
    clearEffect();
    clearMaterial();
  }
  paint(loading(gid)); // 从 empty() 出发，旧内容结构上就留不下来
  try {
    const [d, insp] = await Promise.all([api.cardDetail(gid), api.assetInspect(gid)]);
    if (seq.isStale(my)) return;
    if (!d || !d.card || !insp.found) {
      paint(notReady(gid));
      state.lastInspect = null;
      paintSide(null);
      paintFixBar({ missing: [] });
      clearTabPanes();
    } else {
      state.lastInspect = insp; // 关系网浮层要按同一份回包铺图，不再重查
      const st = loaded(gid, d, insp);
      state.lastState = st;
      paint(st);
      paintTex(insp);
      paintSide(insp, d);
      paintTabCounts(insp);
      paintRing(st);
      paintFiles(insp);
      loadSkeleton(gid, ""); // 骨架要开容器读字节，放在主画面之后异步补，不挡第一眼
      paintRaw({ card: d, inspect: insp });
      paintFixBar(insp);
      if (paintedGid !== gid) {
        showTabPane("preview"); // 换资产回到第一眼该看的那一页；同一组的重刷不动
        paintedGid = gid;
      }
    }
  } catch (e) {
    if (seq.isStale(my)) return;
    const msg = e && e.message ? e.message : String(e);
    // 「还没读到」不是失败——钉子（isNotReadyMsg）跟后端原话逐字对齐，判定在
    // lib/detailState.js（有测试盯着）。摆出等待措辞，几秒后自动重试；真损坏/
    // 真查不到才走 failed() 的红线措辞。
    if (isNotReadyMsg(msg)) {
      paint(notReady(gid));
      clearTabPanes();
      // 重试设上限：预热要跑几分钟，无限轮询就是后台一直在小声敲门；三次
      // （约 7.5 秒）后停在「还没读到」的措辞上，用户再点一次就是新一轮。
      if (retried < 3) {
        setTimeout(() => {
          if (!seq.isStale(my)) showDetail(gid, retried + 1);
        }, 2500);
      }
      return;
    }
    paint(failed(gid, msg));
    state.lastInspect = null;
    paintSide(null);
    paintFixBar({ missing: [] });
    clearTabPanes();
  }
}

// ---- 贴图试贴候选（步骤③④⑤）：区块内容来自 lib/textureState.js（纯函数），
// 这里只负责铺 DOM 和接按钮。确认/撤销走覆盖表，套上看看只动显存拷贝。
let texReply = null;
/// 骨架页的在途标记：切资产后旧请求的回包一律丢掉
let skelSeq = 0;
/// 当前详情铺的是哪一组。后台刷新会重新走一遍 showDetail（同一组），
/// 那时不许把用户从他正在看的标签拽回「预览」——只有真的换了一组才回位。
let paintedGid = 0;
/// 动作页：整条关键帧取回一次，之后拖游标只重画表，不再打后端。
let animReply = null;
let animFrame = 0;
let animSeq = 0;

function animOnlyChanged() {
  return el("animOnlyChanged").checked !== false;
}

function repaintAnim() {
  if (!animReply) return;
  paintAnimation(animReply, animFrame, animOnlyChanged(), (f) => loadAnimation(state.selected, f));
}

async function loadAnimation(gid, file) {
  const my = ++animSeq;
  try {
    const v = await api.animationView(gid, file || "");
    if (my !== animSeq || state.selected !== gid) return;
    animReply = v;
    animFrame = 0;
    repaintAnim();
    poseAnimChanged(); // 换了关键帧：旧动作摆出来的回包与攒帧全部作废
    poseEnsure();      // 预览跟着新动作就位；画布还没建的这一刻补建
  } catch (e) {
    if (my !== animSeq || state.selected !== gid) return;
    animReply = null;
    clearAnimation();
    el("animSum").textContent = `动作没读到：${String((e && e.message) || e)}`;
  }
}

let animWired = false;
function initAnim() {
  if (animWired) return;
  animWired = true;
  el("animFrame").addEventListener("input", (ev) => {
    animFrame = Number(ev && ev.target ? ev.target.value : 0);
    repaintAnim();
    poseCursor(); // 游标动 → 摆这一帧；连动时 gate 只保留最新，不排队积压
  });
  el("animOnlyChanged").addEventListener("change", repaintAnim);
  el("animPlay").addEventListener("click", () => setPlaying(!playing));
  // 点开才取数：一条动作约 0.6 秒，不该压在每次选资产的路径上
  onTabOpen((name) => {
    if (!state.selected) return;
    if (name === "animation") {
      if (!animReply) loadAnimation(state.selected, "");
      poseEnsure(); // animReply 已在时直接就位；viewer 只在此刻建——tab 隐藏时画布量到 0 宽
    } else {
      setPlaying(false); // 切走 tab 自动暂停：看不见的预览没理由继续占着后端
    }
    if (name === "effect" && !fxReply) loadEffect(state.selected, "");
    if (name === "material" && !mtlReply) loadMaterial(state.selected, "");
  });
}

// ---- 动作页 3D 预览：anim_pose 逐帧回蒙皮顶点，MeshViewer.setPose 摆姿势 ----
//
// 判断都在 lib/animPose.js（在途闸门 / 注记去重 / 播放步进）与 mesh-viewer 的
// setPose 校验里，这里只管取数、接线与降级：任何一步失败都写成画布下的
// 一行字，不抛、不挡关键帧表格与游标——那是这一页早就有的本事。
const poseGate = makePoseGate();
const poseSeq = makeSeq();
let poseViewer = null;
/// 该组网格路径清单（skeleton_view 回包的 meshes），按组缓存；切资产即失效。
let poseMeshGid = 0;
let poseMeshes = [];
let poseListBusy = false;
/// 当前摆着的网格路径（客户端原文）。后端自动挑的那次由回包的 mesh 字段告知。
let poseMeshPath = "";
let poseMeshLoaded = false;
let poseNoteShown = "";
/// 播放：定时步进游标。PLAY_STEP_MS 只是参考速度——帧率刻度含义未证，
/// 不许当成「游戏就是 25fps」写进任何文案。
let playTimer = 0;
let playing = false;

function setPlaying(on) {
  if (on === playing) return;
  playing = on;
  const b = el("animPlay");
  b.textContent = on ? "暂停" : "播放";
  b.setAttribute("aria-label", on ? "暂停" : "播放");
  if (on) {
    if (!animReply) {
      setPlaying(false); // 没有关键帧可播：按钮如实退回「播放」
      return;
    }
    playTimer = setInterval(() => playStep(), PLAY_STEP_MS);
    playStep(); // 点播放立刻走一步，不等第一个间隔
  } else if (playTimer) {
    clearInterval(playTimer);
    playTimer = 0;
  }
}

function playStep() {
  if (!animReply || !state.selected) {
    setPlaying(false);
    return;
  }
  animFrame = nextFrame(animFrame, animReply.frames);
  el("animFrame").value = String(animFrame); // 游标与画面同步：拖回去就从那里接着播
  repaintAnim();
  poseCursor();
}

function paintPoseMeshChips() {
  if (poseMeshes.length < 2) {
    el("animMeshPick").innerHTML = "";
    return;
  }
  chips(
    el("animMeshPick"),
    poseMeshes.map((m) => ({ value: m, label: m.replace(/\.mesh$/i, "") })),
    poseMeshPath,
    (m) => loadPoseMesh(state.selected, m),
  );
}

/// 预览总入口：viewer 建一次、网格清单按组取一次、网格就位后摆当前帧。
/// 谁触发都行（点开 tab / 动作回包落地 / 换动作筹码），每步都有
/// 「已就位就跳过」的闸，重复调用不会重复取数。
function poseEnsure() {
  if (!animReply || !state.selected) return;
  if (!poseViewer) {
    try {
      poseViewer = new MeshViewer(el("animCanvas"));
    } catch (e) {
      poseViewer = null;
      poseBreak(`3D 预览起不来：${errText(e)}`);
      return;
    }
  }
  el("animPoseBox").hidden = false;
  poseViewer.draw(); // 顺带把视口量对：tab 重新可见时画布尺寸可能变过
  ensurePoseMeshes(state.selected);
}

function ensurePoseMeshes(gid) {
  if (poseMeshGid === gid) {
    pickPoseMesh(gid);
    return;
  }
  if (poseListBusy) return; // 清单已在途：等它落地自己接下面的流程
  poseListBusy = true;
  api
    .skeletonView(gid)
    .then((v) => {
      poseListBusy = false;
      if (state.selected !== gid) return; // 迟到的清单不进缓存
      poseMeshes = (v && v.meshes) || [];
      poseMeshGid = gid;
      paintPoseMeshChips();
      pickPoseMesh(gid);
    })
    .catch((e) => {
      poseListBusy = false;
      if (state.selected !== gid) return;
      poseBreak(`这套动作暂时摆不出来：${errText(e)}`);
    });
}

function pickPoseMesh(gid) {
  if (!animReply || state.selected !== gid) return;
  if (poseMeshLoaded) {
    poseCursor(); // 几何已在缓冲里（换动作回到这里就是这个分支）：只补当前帧
    return;
  }
  const want = poseMeshPath || (poseMeshes.length ? poseMeshes[0] : "");
  if (want) loadPoseMesh(gid, want);
  else poseAutoPick(gid); // 清单是空的：让后端自己挑，回包带实际用的路径
}

/// 后端自动挑网格的那一路：mesh 传空，回包的 mesh 字段是客户端原文，
/// 必须显示在 meta 行——不能让人猜画的是哪一份。
async function poseAutoPick(gid) {
  const my = poseSeq.next();
  try {
    const rep = await api.animPose(gid, animReply.file, null, clampFrame(animFrame, animReply.frames));
    if (poseSeq.isStale(my) || state.selected !== gid || !animReply) return;
    if (!rep || !rep.mesh) {
      poseBreak("这一组没找到能摆的网格。");
      return;
    }
    poseMeshPath = rep.mesh;
    paintPoseMeshChips();
    await loadPoseMesh(gid, rep.mesh);
  } catch (e) {
    if (poseSeq.isStale(my) || state.selected !== gid) return;
    poseBreak(`预览没摆出来：${errText(e)}`);
  }
}

async function loadPoseMesh(gid, path) {
  const my = poseSeq.next(); // 换网格：旧网格在途的 pose 回包连几何都对不上了，一并作废
  poseMeshLoaded = false;
  try {
    const data = await api.meshData(path, null); // hash 传 null：后端按路径找
    if (poseSeq.isStale(my) || state.selected !== gid) return;
    try {
      poseViewer.load(data, null); // 骨线是网格页绑定姿态的事，预览不摆它
    } catch (e) {
      poseBreak(`预览没摆出来：${errText(e)}`);
      return;
    }
    poseMeshPath = path;
    poseMeshLoaded = true;
    el("animStage").hidden = false;
    el("animPoseMeta").textContent = `${path} · ${num(data.vertexCount)} 个顶点`;
    poseCursor();
  } catch (e) {
    if (poseSeq.isStale(my) || state.selected !== gid) return;
    poseBreak(`预览没摆出来：${errText(e)}`); // 空画布会让人以为渲染坏了，收掉、给一行话
  }
}

/// 当前帧要摆出来。游标 input、播放步进、网格/动作就位都汇到这一处。
function poseCursor() {
  if (!poseMeshLoaded || !animReply || !state.selected) return;
  poseRequest(clampFrame(animFrame, animReply.frames));
}

async function poseRequest(frame) {
  const issued = poseGate.request(frame);
  if (issued == null) return; // 已有在途：gate 记下最新想看的帧，回包落地自动补
  const gid = state.selected;
  const file = animReply.file;
  const mesh = poseMeshPath;
  const my = poseSeq.next();
  try {
    const rep = await api.animPose(gid, file, mesh, issued);
    // 陈旧回包一律丢：资产 / 动作 / 网格任何一个换了，这包顶点都画不得
    const fresh =
      !poseSeq.isStale(my) && state.selected === gid && animReply && animReply.file === file && poseMeshPath === mesh;
    if (fresh) applyPoseReply(rep);
  } catch (e) {
    const fresh =
      !poseSeq.isStale(my) && state.selected === gid && animReply && animReply.file === file && poseMeshPath === mesh;
    if (fresh) poseFail(e);
  } finally {
    // 这一位放出来了。在途期间游标若又动过，把攒下的**最新**一帧补上——
    // 补发按「现在」的资产/动作/网格取参，不看这个请求出生时的世界。
    const follow = poseGate.settled();
    if (follow != null && animReply && poseMeshLoaded && state.selected) poseRequest(follow);
  }
}

function applyPoseReply(rep) {
  const err = el("animPoseErr");
  err.hidden = true;
  err.textContent = "";
  if (!rep || !Array.isArray(rep.positions)) {
    poseFailLine("这一帧没摆出来：回包里没有顶点。");
    return;
  }
  if (!poseViewer.setPose(rep.positions)) {
    // setPose 校验过顶点数与坐标才动缓冲：被拒了就把话带给用户，不假装摆上了
    poseFailLine("这一帧没摆出来：顶点对不上这份网格。");
    return;
  }
  const note = poseNote(rep.notes, poseNoteShown);
  if (note != null) {
    poseNoteShown = note;
    el("animPoseNote").textContent = note;
    el("animPoseNote").hidden = !note;
  }
}

function poseFailLine(msg) {
  const err = el("animPoseErr");
  err.hidden = false;
  err.textContent = msg;
}

/// 一帧的失败：画布保着上一帧的画面（有就比空白强），错误写在画布下。
function poseFail(e) {
  poseFailLine(`这一帧没摆出来：${errText(e)}`);
}

/// 预览整体废了（viewer 起不来 / 清单或几何取不到）：画布收掉、一行说明顶上，
/// 表格与游标照常——它们不依赖画布。
function poseBreak(msg) {
  el("animStage").hidden = true;
  poseFailLine(msg);
}

/// 换动作：pose 的回包与攒帧是按那条动作摆的，全部作废（网格几何可以留用）。
function poseAnimChanged() {
  poseSeq.next();
  poseGate.reset();
}

/// 切资产 / 清页：预览整块收摊。viewer 留着（WebGL 上下文建一次是一份家底），
/// 但画布藏起来——上一只怪的最后一帧还在缓冲里，亮着就是拿旧图冒充新资产。
function poseReset() {
  setPlaying(false);
  poseSeq.next();
  poseGate.reset();
  poseMeshGid = 0;
  poseMeshes = [];
  poseListBusy = false;
  poseMeshPath = "";
  poseMeshLoaded = false;
  poseNoteShown = "";
  el("animPoseBox").hidden = true;
  el("animMeshPick").innerHTML = "";
  el("animPoseMeta").textContent = "";
  el("animStage").hidden = false;
  el("animPoseErr").hidden = true;
  el("animPoseErr").textContent = "";
  el("animPoseNote").hidden = true;
  el("animPoseNote").textContent = "";
}

/// 特效页：.pu 的材质链与各类类名。没有 .pu 的组后端会给原因，原样转述。
/// 一个组名下可能登记好几份 .pu，后端默认给与组同名的那份，其余摆成选择条。
let fxReply = null;
let fxSeq = 0;

async function loadEffect(gid, file) {
  const my = ++fxSeq;
  try {
    const v = await api.effectView(gid, file || "");
    if (my !== fxSeq || state.selected !== gid) return;
    fxReply = v;
    paintEffect(v, (f) => loadEffect(gid, f));
  } catch (e) {
    if (my !== fxSeq || state.selected !== gid) return;
    fxReply = null;
    clearEffect();
    el("fxSum").textContent = String((e && e.message) || e);
  }
}
/// 材质页：.mtl（JBCF）的槽位表。一组可能登记好几份材质，默认列与组同名那份。
let mtlReply = null;
let mtlSeq = 0;

async function loadMaterial(gid, file) {
  const my = ++mtlSeq;
  try {
    const v = await api.materialView(gid, file || "");
    if (my !== mtlSeq || state.selected !== gid) return;
    mtlReply = v;
    paintMaterial(v, (f) => loadMaterial(gid, f));
  } catch (e) {
    if (my !== mtlSeq || state.selected !== gid) return;
    mtlReply = null;
    clearMaterial();
    el("mtlSum").textContent = String((e && e.message) || e);
  }
}

// 这一栏最近一次铺的是什么回包 + 后台批量试贴的状态。
// texSource 与 texReply 分开是有原因的：texReply 只在「有候选榜」时非空，
// 而「没有榜」恰恰是要提示「后台还没跑完」的那一路——那时也得能重画这一栏。
let texSource = null;
let warmStatus = null;

function paintTex(insp) {
  texSource = insp;
  const block = texBlock(insp, warmStatus);
  texReply = block ? insp : null;
  el("secTex").hidden = !block;
  if (!block) return;
  el("texSlots").innerHTML = block.slotsHtml;
  el("texCand").innerHTML = block.candHtml;
  el("texNote").textContent = block.note;
  loadCandidatePngs();
}

/// 问一次后台批量试贴的状态。数不出来（没有桌面端 / 后端没这条命令）就保持
/// null：那一栏的话术会退回「离线试贴还没跑」，而不是编一句「都跑完了」。
function refreshWarm() {
  if (!api.textureWarmStatus) return;
  api
    .textureWarmStatus()
    .then((v) => {
      warmStatus = v || null;
      if (texSource && !el("secTex").hidden) paintTex(texSource);
    })
    .catch(() => {});
}
refreshWarm();

/// 进度广播只往「说明行」写字：批量跑一次要几分钟，用户此刻最想知道的就是
/// 还要等多久、这一栏为什么还空着。跑完立刻重问状态（榜可能刚补上）。
api.onTextureWarming?.((ev) => {
  const p = (ev && ev.payload) || ev || {};
  if (p.phase === "scored") {
    el("texNote").textContent = `后台批量试贴：已评 ${p.done} / ${p.total} 只模型`;
  } else if (p.phase === "pool") {
    el("texNote").textContent = `后台批量试贴：正在准备候选池，已解码 ${p.done} / ${p.total} 张贴图`;
  } else if (p.phase === "finished") {
    el("texNote").textContent = `后台批量试贴跑完：新评 ${p.scored} 只 / 全库 ${p.total} 只`;
    refreshWarm();
  } else if (p.phase === "error") {
    el("texNote").textContent = `后台批量试贴失败：${p.error}`;
    refreshWarm();
  }
});

/// 批量缓存（source=batch）的候选卡不带内嵌图：按候选编号 hash 逐张现解 256px
/// 缩略图。串行不并发——每次调用后端要开一次 pak，10 张齐发就是 10 次开盘。
/// 旧缓存自带 data URL，卡片上没有这个标记，不会走到这里，老链路零改动。
/// 取到的图顺手回填进回包，这样「套上看看」和旧缓存一样直接用现成的 png；
/// 回包 null / 报错都让占位框留着，title 说明原因——没有图就是没有图。
/// 认卡只认编号：榜单在 Rust 侧按综合分重排过，名次不再对应缓存里的下标。
/// 骨架页取数。切走资产后迟到的回包必须丢掉，否则会把上一只怪的骨名画到这一只上。
async function loadSkeleton(gid, mesh) {
  skelSeq = gid;
  try {
    const v = await api.skeletonView(gid, mesh || "");
    if (skelSeq !== gid || state.selected !== gid) return;
    paintSkeleton(v, (m) => loadSkeleton(gid, m));
  } catch (e) {
    if (skelSeq !== gid || state.selected !== gid) return;
    // 「这一组没有网格」是常态而不是故障，措辞跟着后端原话走
    paintSkeleton({ nodes: [], animations: [], missing: [], note: String((e && e.message) || e) });
  }
}

async function loadCandidatePngs() {
  if (el("secTex").hidden) return; // 区块没露脸就不花这份解码钱
  const reply = texReply; // 换资产后 texReply 会换人：旧回包的图不许写进新榜
  const byHash = (hash) => {
    for (const g of reply.textureCandidates || []) {
      const c = (g.candidates || []).find((x) => x.hash === hash);
      if (c) return c;
    }
    return null;
  };
  const imgs = Array.from(el("texCand").querySelectorAll("img[data-need-png]"));
  for (const img of imgs) {
    if (!img.isConnected || texReply !== reply) return; // 已被下一轮 paint 换掉
    try {
      const png = await api.candidatePng(img.dataset.hash);
      if (!img.isConnected || texReply !== reply) return;
      if (png) {
        img.src = png;
        const c = byHash(img.dataset.hash);
        if (c && !c.png) c.png = png;
      } else {
        img.title = "缩略图没读出来";
      }
    } catch {
      img.title = "缩略图没读出来";
    }
  }
}

el("secTex").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.act === "warm") {
    // 「后台跑完它们」要能在没有候选榜时点得动：那一路 texReply 恰恰是空的。
    const msg = await api.textureWarmStart();
    el("texNote").textContent = String(msg || "已开始后台批量试贴");
    refreshWarm();
    return;
  }
  if (!texReply) return;
  const group = (texReply.textureCandidates || [])[0];
  const slots = texReply.texSlots || [];
  if (b.dataset.act === "try") {
    const c = group && group.candidates[Number(b.dataset.idx)];
    if (c && !applyTexture(c.png)) el("texNote").textContent = "先在上方立体预览里把网格调出来，才能套贴图。";
    return;
  }
  if (b.dataset.act === "confirm") {
    const pick = el("texSlotPick");
    const slot = (pick && slots.find((s) => s.name === pick.value)) || slots.find((s) => !s.overrideHash);
    const c = group && group.candidates[Number(b.dataset.idx)];
    if (!slot || !c) return;
    await api.textureOverrideSet(slot.name, slot.cfgPath, c.hash, "uvfit v1 人工确认");
    showDetail(state.selected);
    return;
  }
  if (b.dataset.act === "clear") {
    await api.textureOverrideClear(b.dataset.slot, b.dataset.cfg);
    showDetail(state.selected);
  }
});

// ---- 详情工具栏：只有「导出」是真动作，其余如实说明为什么还不行 ----
// 不摆灰按钮装样子：点下去没反应比按钮不存在更让人恼火。
let toolsWired = false;
function initTools() {
  if (toolsWired) return;
  toolsWired = true;
  const note = (text) => {
    el("dSum").textContent = text;
  };
  el("btnFav").addEventListener("click", () => note("收藏需要本地策展表，这一版还没接上——先不假装能存。"));
  el("btnLocate").addEventListener("click", () => note("定位到目录树需要浏览视图里先打开对应的 data 包，这一版还没打通这两条链路。"));
  // 「导出」是真动作：一次把这一组的文件导到默认目录，不用人切去「浏览」标签搜名字。
  el("btnExportOne").addEventListener("click", async () => {
    const gid = state.selected;
    if (!gid) {
      note("还没选中资产：先在左边列表里点一条。");
      return;
    }
    if (state.exportBusy) return;
    state.exportBusy = true;
    note("正在导出这一组的文件…");
    try {
      const rep = await api.browseExportGroup(gid, "");
      let text = `已导出 ${rep.written.toLocaleString()} 个文件到 ${rep.dest}`;
      const bad = (rep.failed?.length ?? 0) + (rep.failed_more ?? 0);
      if (bad) {
        text += `；另有 ${bad} 项没导出来（${rep.failed[0]}）`;
      }
      note(text);
    } catch (e) {
      note(`导出没成：${String(e?.message ?? e)}`);
    } finally {
      state.exportBusy = false;
    }
  });
}

/// 列表清空/重查时把详情区收回初始态，避免"列表换了、右边还是旧资产"。
export function clearDetail() {
  seq.next();
  state.selected = 0;
  paintedGid = 0;
  state.lastInspect = null;
  paint(empty());
  paintSide(null);
  paintFixBar({ missing: [] });
  clearTabPanes();
}

initTabs();
initTools();
initAnim();
