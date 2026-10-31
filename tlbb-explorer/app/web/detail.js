// 详情页：只做两件事——把回包交给状态机算，然后把算出来的状态写进 DOM。
//
// 所有"哪些字段该出现、什么时候必须空"的判断都在 lib/detailState.js 里，
// 那边有 node --test 盯着（app/tests/detailState.test.js）。
// 这里刻意不做任何业务判断：判断留在能测的地方。

import { el, errText, num, chips } from "./ui.js";
import * as api from "./api.js";
import { evidenceShort } from "./lib/layerChips.js";
import { state } from "./state.js";
import { makeSeq } from "./lib/seq.js";
import { empty, loading, failed, notReady, loaded, isNotReadyMsg } from "./lib/detailState.js";
import { titleHtml } from "./lib/wording.js";
import {
  showMeshes,
  hideMeshes,
  applyTexture,
  tryLayerTexture,
  remesh,
  setTrialProvider,
  setTexturePlanProvider,
  setTexturePlanObserver,
  refreshTexturePlan,
  clearMeshTexture,
  onActiveMesh,
  currentMeshName,
} from "./mesh.js";
import { MeshViewer } from "./mesh-viewer.js";
import {
  makePoseGate,
  poseNote,
  poseNotesLine,
  nextFrame,
  PLAY_STEP_MS,
  clampFrame,
  meshTail,
  checkedPartList,
  partLoadSummary,
  matchPartPoses,
  sameNameList,
} from "./lib/animPose.js";
import { texBlock, trialPick, uvMapHtml, confirmTarget, texSlotsHtml } from "./lib/textureState.js";
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
    // 详情比视口高时，真正滚动的是窗口而不是 detailPane——换资产后停在上一件
    // 资产的滚动位置，人第一眼看到的是页面中段（2026-10-24 真窗口撞到）。
    window.scrollTo?.(0, 0);
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
  const stepFrame = (d) => {
    if (!animReply) return;
    if (playing) setPlaying(false); // 手点逐帧就停下播放，别和定时器抢游标
    const max = Math.max(0, (animReply.frames || 1) - 1);
    animFrame = Math.min(max, Math.max(0, animFrame + d));
    el("animFrame").value = String(animFrame);
    repaintAnim();
    poseCursor();
  };
  for (const [id, d] of [["animPrev", -1], ["animNext", 1]]) {
    const b = el(id);
    if (b) b.addEventListener("click", () => stepFrame(d));
  }
  const speed = el("animSpeed");
  if (speed) {
    speed.addEventListener("change", () => {
      const v = Number(speed.value);
      playSpeed = Number.isFinite(v) && v > 0 ? v : 1;
      if (playing) {
        clearInterval(playTimer);
        playTimer = setInterval(() => playStep(), playStepMs());
      }
    });
  }
  // 组成树里的「试画它」：名字是推出来的、清单没登记，但哈希在容器里核过 ⇒ 按哈希直读来画。
  el("tree").addEventListener("click", (ev) => {
    const btn = ev.target && ev.target.closest ? ev.target.closest("[data-trial-mesh]") : null;
    if (!btn) return;
    const name = btn.getAttribute("data-trial-mesh");
    const hash = btn.getAttribute("data-trial-hash");
    if (!name || !hash) return;
    showMeshes({ meshes: [{ name, hash, label: name }], visible: true, active: 0 });
    el("secMesh").scrollIntoView({ block: "center" });
  });
  el("animPlay").addEventListener("click", () => setPlaying(!playing));
const animBonesBox = el("animBones");
if (animBonesBox) {
  animBonesBox.addEventListener("change", () => applyPoseBones(poseLastReply));
}
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
    // 特效页的画布在面板里，隐藏时量到 0 宽；切回来让它按现在的尺寸重画一帧。
    if (
      (name === "effect" || name === "skeleton") &&
      typeof window !== "undefined" &&
      typeof Event === "function"
    ) {
      window.dispatchEvent(new Event("tlbb:viewer-resize"));
    }
    if (name === "material" && !mtlReply) loadMaterial(state.selected, "");
    if (name === "preview") remesh(); // 详情停在别的标签加载过：画布量的是隐藏时的 1x1，回来要重量
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
/// 贴图计划的作废令牌：与 poseSeq 分开——poseRequest 每帧都 next()，
/// 贴图回包晚于第一帧是常态，跟着 poseSeq 走会被误判成过期（实测贴图永不生效）。
let poseTexSeq = 0;
/// 该组网格路径清单（skeleton_view 回包的 meshes），按组缓存；切资产即失效。
let poseMeshGid = 0;
let poseMeshes = [];
let poseListBusy = false;
/// 当前摆着的网格路径（客户端原文）。后端自动挑的那次由回包的 mesh 字段告知。
let poseMeshPath = "";
let poseMeshLoaded = false;
let poseNoteShown = "";
/// 整组部件路径（组内登记 ≥2 份网格才走；单件与回退维持 loadPoseMesh 老路）。
/// partData 是**取到手**的全部部件几何（勾回来不用再取的库存）；
/// partNames 是**此刻在画布上**的件序（loadParts 的装载序，setPartPose 的
/// 下标按它对号）。两个名单有意分开：勾掉一件是把它从画布撤下，不是扔掉。
/// partChecks 只管库存里每件开不开，默认全开。
let poseMode = "single"; // "single" | "parts"
let partData = [];
let partNames = [];
let partChecks = new Map();
/// 逐件取几何的失败点名（partLoadSummary 的人话），画布下单独一行，不与
/// 「这一帧没摆出来」混用——一个是装载实况、一个是帧级事故。
let partLoadNote = "";
/// 播放：定时步进游标。PLAY_STEP_MS 只是参考速度——帧率刻度含义未证，
/// 不许当成「游戏就是 25fps」写进任何文案。
let playTimer = 0;
let playing = false;
/// 参考速度倍率：只改预览节奏，不改「帧率含义未证」那句口径。
let playSpeed = 1;
const playStepMs = () => Math.max(16, Math.round(PLAY_STEP_MS / playSpeed));

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
    playTimer = setInterval(() => playStep(), playStepMs());
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
}/// 预览总入口：viewer 建一次、网格清单按组取一次、网格就位后摆当前帧。
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
  // 复合的账：组内登记 ≥2 份网格 = 多件套（36% 的 .mesh 是这种），整组一起摆。
  // 单件网格组与整组失败回退的那一路仍走 loadPoseMesh 老路。
  if (poseMeshes.length >= 2) {
    loadPoseParts(gid);
    return;
  }
  const want = poseMeshPath || (poseMeshes.length ? poseMeshes[0] : "");
  if (want) loadPoseMesh(gid, want);
  else poseAutoPick(gid); // 清单是空的：让后端自己挑，回包带实际用的路径
}

/// 整组部件的 meta 行：组级事实（共几件、名单）+ 此刻画布上有几件。
function partsMetaText() {
  const total = partData.length;
  const drawn = partNames.length;
  const head = drawn === total ? `整组一起摆：${total} 件` : `整组一起摆：${drawn}/${total} 件`;
  return `${head}，共用一副骨架（${partData.map((o) => o.name).join("、")}）`;
}

/// 部件勾选区：每件一个 checkbox，复用 .check 的现成样式。关掉的不画不请求
/// （名单与画布同时少它），全关就是空画布加一行说明，绝不发空名单的请求。
function paintPartChecks() {
  const box = el("animPartPick");
  box.innerHTML = "";
  box.hidden = !partData.length;
  for (const o of partData) {
    const label = document.createElement("label");
    label.className = "check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = partChecks.get(o.name) !== false;
    input.addEventListener("change", () => togglePart(o.name, input.checked));
    const name = document.createElement("span");
    name.textContent = o.name;
    label.appendChild(input);
    label.appendChild(name);
    box.appendChild(label);
  }
}

function writePartNote(text) {
  el("animPartNote").hidden = !text;
  el("animPartNote").textContent = text || "";
}

/// 现在勾着的件名（按库存顺序，勾选状态见 partChecks）。
function checkedPartsNow() {
  return checkedPartList(
    partData.map((o) => o.name),
    (n) => partChecks.get(n) !== false,
  );
}

/// 勾选变了：画布整批换成还开着的件（loadParts 换缓冲），当前帧重新请求
/// （名单同时少它）。在途回包与攒帧一并作废——缓冲都换了，旧顶点对不上号。
function togglePart(name, on) {
  if (poseMode !== "parts" || !animReply || !state.selected) return;
  partChecks.set(name, on);
  partNames = partData.filter((o) => partChecks.get(o.name) !== false).map((o) => o.name);
  const my = poseSeq.next();
  poseGate.reset();
  poseMeshLoaded = false;
  if (!partNames.length) {
    // 一件没开：清画布、不发请求——空名单会让后端回落单件，那是画错
    poseViewer.clearParts();
    el("animPoseMeta").textContent = partsMetaText();
    writePartNote(
      [partLoadNote, "整组一件都没勾上：画布先空着，勾上任意一件再摆。"].filter(Boolean).join("；"),
    );
    return;
  }
  try {
    poseViewer.loadParts(partNames.map((n) => partData.find((o) => o.name === n).data));
  } catch (e) {
    poseBreak(`预览没摆出来：${errText(e)}`);
    return;
  }
  paintPosePartTextures(state.selected, partNames);
  el("animPoseMeta").textContent = partsMetaText();
  writePartNote(partLoadNote);
  poseMeshLoaded = true;
  poseCursor();
}

/// 动作预览也穿贴图：与网格页同一份分层计划（按件名取，后端自己去对材质表）。
/// 取不到就保持灰模，不编、不提示——缺贴图在这套资源里是常态，画布不因此报错。
async function paintPosePartTextures(gid, names) {
  if (!poseViewer) return;
  const token = ++poseTexSeq;
  await Promise.all(
    names.map(async (n, i) => {
      try {
        const plan = await api.meshTexturePlan(gid, n, null);
        if (token !== poseTexSeq || state.selected !== gid) return;
        const layers = plan && Array.isArray(plan.layers) ? plan.layers : [];
        if (layers.length) poseViewer.setPartLayers(i, layers);
      } catch {}
    }),
  );
}

/// 单件路径的同一件事：整张网格套它的分层计划（mesh.js 的单件分支同款）。
async function paintPoseMeshTexture(gid, path) {
  if (!poseViewer) return;
  const token = ++poseTexSeq;
  try {
    const plan = await api.meshTexturePlan(gid, meshTail(path), null);
    if (token !== poseTexSeq || state.selected !== gid) return;
    const layers = plan && Array.isArray(plan.layers) ? plan.layers : [];
    if (layers.length) poseViewer.setTextureLayers(layers);
  } catch {}
}

/// 整组装载：懒取部件清单后逐件取几何（allSettled——单件失败点名跳过，
/// 不炸整组），loadParts 一次装好，之后每帧一个 anim_pose 请求按件对号摆。
/// 整组失败（一件几何都没取到 / 缓冲装不起来）回退单件路径，现状代码保留。
async function loadPoseParts(gid) {
  if (!poseViewer) return;
  const my = poseSeq.next(); // 换部件装法：旧回包与攒帧全部作废
  poseGate.reset();
  poseMeshLoaded = false;
  const paths = poseMeshes;
  const names = paths.map(meshTail);
  const settled = await Promise.allSettled(paths.map((p) => api.meshData(p, null)));
  if (poseSeq.isStale(my) || state.selected !== gid) return;
  const sum = partLoadSummary(names, settled);
  if (!sum.ok.length) {
    // 整组失败：回退单件老路（网格筹码也跟着回来，用户可以换一份再试）
    await loadPoseMesh(gid, paths[0]);
    return;
  }
  poseMode = "parts";
  partData = sum.ok;
  // 勾选默认全开；同一组重取（换动作回来）时保留用户勾过的选择
  partChecks = new Map(partData.map((o) => [o.name, partChecks.get(o.name) !== false]));
  partNames = partData.filter((o) => partChecks.get(o.name) !== false).map((o) => o.name);
  partLoadNote = sum.message || "";
  el("animMeshPick").innerHTML = ""; // 整组模式没有单件筹码：勾选区替它
  paintPartChecks();
  writePartNote(partLoadNote);
  if (!partNames.length) {
    poseViewer.clearParts();
    el("animStage").hidden = false;
    el("animPoseMeta").textContent = partsMetaText();
    writePartNote(
      [partLoadNote, "整组一件都没勾上：画布先空着，勾上任意一件再摆。"].filter(Boolean).join("；"),
    );
    return;
  }
  try {
    poseViewer.loadParts(partNames.map((n) => partData.find((o) => o.name === n).data));
  } catch (e) {
    // 缓冲装不起来也算整组失败：回退单件，画布不能停在半个黑屏上
    await loadPoseMesh(gid, paths[0]);
    return;
  }
  paintPosePartTextures(gid, partNames);
  el("animStage").hidden = false;
  el("animPoseMeta").textContent = partsMetaText();
  poseMeshLoaded = true;
  poseCursor();
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
  enterSinglePoseMode(); // 单件老路一进来，整组部件的库存/勾选/画布全部收干净
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
    paintPoseMeshTexture(gid, path);
    el("animStage").hidden = false;
    el("animPoseMeta").textContent = `${path} · ${num(data.vertexCount)} 个顶点`;
    paintPoseMeshChips(); // 回退到单件时筹码跟着回来，用户可以换一份再试
    poseCursor();
  } catch (e) {
    if (poseSeq.isStale(my) || state.selected !== gid) return;
    poseBreak(`预览没摆出来：${errText(e)}`); // 空画布会让人以为渲染坏了，收掉、给一行话
  }
}

/// 单件路径的收尾：清掉整组部件的库存、勾选与勾选区 DOM。viewer 侧的 parts
/// 缓冲由 load() 的互斥逻辑（unloadParts）顺手收掉，这里不重复删。
function enterSinglePoseMode() {
  poseMode = "single";
  partData = [];
  partNames = [];
  partChecks = new Map();
  el("animPartPick").innerHTML = "";
  el("animPartPick").hidden = true;
  writePartNote("");
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
  // 整组路径发勾着的名单（mesh 参数让位给 null），单件路径发网格路径——
  // 两条路共用一个命令，后端按 parts 在不在分辨。
  const parts = poseMode === "parts" ? checkedPartsNow() : null;
  const mesh = poseMode === "parts" ? null : poseMeshPath;
  const my = poseSeq.next();
  try {
    const rep = await api.animPose(gid, file, mesh, issued, parts);
    // 陈旧回包一律丢：资产 / 动作 / 网格 / 勾选任何一个换了，这包顶点都画不得。
    // 名单逐位比对（sameNameList）：勾选刚变过 = 缓冲换过一批，旧顶点对不上号。
    const alive =
      !poseSeq.isStale(my) && state.selected === gid && animReply && animReply.file === file;
    const fresh = alive &&
      (parts
        ? poseMode === "parts" && sameNameList(checkedPartsNow(), parts)
        : poseMode === "single" && poseMeshPath === mesh);
    if (fresh) {
      if (parts) applyPartsReply(rep);
      else applyPoseReply(rep);
    }
  } catch (e) {
    const fresh =
      !poseSeq.isStale(my) && state.selected === gid && animReply && animReply.file === file;
    if (fresh) poseFail(e);
  } finally {
    // 这一位放出来了。在途期间游标若又动过，把攒下的**最新**一帧补上——
    // 补发按「现在」的资产/动作/网格/勾选取参，不看这个请求出生时的世界。
    const follow = poseGate.settled();
    if (follow != null && animReply && poseMeshLoaded && state.selected) poseRequest(follow);
  }
}

let poseLastReply = null;

/// 动作回包里的逐骨锚点：勾了「画布叠加骨架线」才画，线段按父下标连。
function applyPoseBones(rep) {
  // 测试里的 viewer 桩没有骨线接口：没有就当不支持，别把摆姿势那条路带崩。
  if (!poseViewer || typeof poseViewer.setBoneLines !== "function" || typeof poseViewer.draw !== "function") {
    return;
  }
  const box = el("animBones");
  if (!box || !box.checked) {
    poseViewer.setBoneLines(null);
    poseViewer.draw();
    return;
  }
  const bones = (rep && rep.bones) || [];
  const lines = [];
  for (const b of bones) {
    if (!b || b.parent == null) continue;
    const p = bones[b.parent];
    if (p && b.pos && p.pos) lines.push([b.pos, p.pos]);
  }
  // 根骨/落脚点这类骨常落在世界原点，会从身体拖一条长线到脚下；
  // 按段长中位数把明显离谱的段丢掉（只影响画线，不动数据）。
  const len = ([a, b]) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  if (lines.length >= 5) {
    const lens = lines.map(len).sort((x, y) => x - y);
    const med = lens[lens.length >> 1];
    const kept = lines.filter((l) => len(l) <= med * 3);
    lines.length = 0;
    lines.push(...kept);
  }
  poseViewer.setBoneLines(lines.length ? { lines } : null);
  poseViewer.draw();
}

function applyPoseReply(rep) {
  poseLastReply = rep;
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
  applyPoseBones(rep);
}

/// 整组回包按件对号摆：rep.parts[i].mesh 的尾名对到画布上的件（matchPartPoses
/// 不按位置硬配），逐件 setPartPose——某件顶点不合格只丢那一件，其余照摆。
function applyPartsReply(rep) {
  poseLastReply = rep;
  const err = el("animPoseErr");
  err.hidden = true;
  err.textContent = "";
  if (!rep || !Array.isArray(rep.parts)) {
    // 后端一个件都没匹配上会回落单件（不带 parts 字段）：整组模式下这包顶点
    // 对不上画布的任何一件，如实说，不拿单件顶点去灌多件缓冲。
    poseFailLine("这一帧没摆出来：后端这次按单件回的包，整组顶点没有。");
    return;
  }
  const matched = matchPartPoses(rep.parts, partNames);
  if (!matched.length) {
    poseFailLine("这一帧没摆出来：回包的部件和画布上的对不上号。");
    return;
  }
  let rejected = 0;
  for (const m of matched) {
    if (!poseViewer.setPartPose(m.index, m.positions)) rejected += 1;
  }
  if (rejected === matched.length) {
    poseFailLine("这一帧没摆出来：顶点对不上这些部件。");
    return;
  }
  if (rejected > 0) {
    poseFailLine(`这一帧有 ${rejected} 件没摆出来（顶点对不上，那件停在上一帧），其余照摆。`);
  }
  // 「这件不变形」这类部件实况由后端追加在固定三条后面，整段一起上屏才叫如实。
  const line = poseNotesLine(rep.notes, poseNoteShown);
  if (line != null) {
    poseNoteShown = line;
    el("animPoseNote").textContent = line;
    el("animPoseNote").hidden = !line;
  }
  applyPoseBones(rep);
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
  // 整组部件随资产走：库存、勾选、注记全部清零，显存里的部件缓冲一并删掉——
  // 上一只怪的衣服留在缓冲里，亮着就是拿旧图冒充新资产。
  poseMode = "single";
  partData = [];
  partNames = [];
  partChecks = new Map();
  partLoadNote = "";
  if (poseViewer) poseViewer.clearParts();
  el("animPoseBox").hidden = true;
  el("animMeshPick").innerHTML = "";
  el("animPartPick").innerHTML = "";
  el("animPartPick").hidden = true;
  el("animPoseMeta").textContent = "";
  el("animStage").hidden = false;
  el("animPoseErr").hidden = true;
  el("animPoseErr").textContent = "";
  el("animPoseNote").hidden = true;
  el("animPoseNote").textContent = "";
  writePartNote("");
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
/// 自动试贴当前套的是哪份榜的第几张：只用于在候选卡上标「已套（未确认）」。
let trialApplied = null;
let warmStatus = null;
/// 这一栏当前铺的是哪一只资产的榜。确认/撤销之后要重刷**这一只**，
/// 不是 `state.selected`——真窗口里撞到过：两次点击之间 state.selected 已经被
/// 别处改走（列表重画、别的驱动点了别的行），照 state.selected 重刷会让人
/// 刚标完就看不见自己那条 🟢。
let texGid = 0;
/// 当前画布上那只网格的贴图槽名单（由 mesh_texture_plan 回包带来）。
/// null = 还没拿到分层计划，槽位按整组列；Set = 只列这只网格材质表里的名字。
let activeSlotNames = null;

/// 当前显示的是哪份网格，就只留它的候选榜。一只怪常有 2~3 份网格
/// （衣服/手套/武器），把别的网格的榜摆在这里，人会拿错榜往当前槽位里写确认。
function activeMeshSorted(insp) {
  const groups = (insp && insp.textureCandidates) || [];
  // 画布给的是完整路径（data/source/.../x.mesh），榜里只写文件名；按最后一段比。
  const base = (s) => String(s || "").replaceAll("\\", "/").split("/").pop().toLowerCase();
  const active = base(currentMeshName());
  if (!active) return insp;
  return { ...insp, textureCandidates: groups.filter((g) => base(g.mesh) === active) };
}

/// 在候选卡上标出「自动试贴当前套的是这张」。只做视觉标记，不改试贴逻辑。
function paintTrialBadge() {
  const host = el("texCand");
  if (!host) return;
  for (const f of host.querySelectorAll("figure.tex-cand.trial-on")) f.classList.remove("trial-on");
  for (const b of host.querySelectorAll(".trial-badge")) b.remove();
  if (!trialApplied || !texReply) return;
  const groups = texReply.textureCandidates || [];
  const g = groups[trialApplied.gi];
  if (!g) return;
  const base = (s) => String(s || "").replaceAll("\\", "/").split("/").pop().toLowerCase();
  if (base(g.mesh) !== trialApplied.mesh) return;
  const btn = host.querySelector(
    `button[data-act="try"][data-gi="${trialApplied.gi}"][data-idx="${trialApplied.idx}"]`,
  );
  const fig = btn && btn.closest ? btn.closest("figure.tex-cand") : null;
  if (!fig) return;
  fig.classList.add("trial-on");
  const tag = document.createElement("span");
  tag.className = "trial-badge";
  tag.textContent = "已套（未确认）";
  fig.prepend(tag);
}

function paintTex(insp) {
  texSource = insp;
  if (texGid !== state.selected) activeSlotNames = null; // 换资产：别拿上一只的槽名过滤
  texGid = state.selected;
  const reply = activeMeshSorted(insp);
  const allSlots = reply.texSlots || [];
  let slots = allSlots;
  if (activeSlotNames) {
    const hit = allSlots.filter((s) => activeSlotNames.has(String(s.name).toLowerCase()));
    if (hit.length) slots = hit;
  }
  const view = slots === allSlots ? reply : { ...reply, texSlots: slots };
  const block = texBlock(view, warmStatus);
  texReply = block ? view : null;
  el("secTex").hidden = !block;
  if (!block) return;
  el("texSlots").innerHTML = block.slotsHtml;
  el("texCand").innerHTML = block.candHtml;
  el("texNote").textContent = block.note;
  loadCandidatePngs();
  loadUvMaps();
  paintTrialBadge();
}

// 换网格（画布上方的筹码）时重排候选栏，不重开容器：已解出的 png 都在回包里。
onActiveMesh(() => {
  if (texSource && !el("secTex").hidden) paintTex(texSource);
});

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

/// 立体预览的自动试贴：这只网格没有 🟢 确认记录时，把这份榜的第一名套上去看效果，
/// 标题里写明「未确认，不是客户端认定的那张」。要不要套、套不了为什么，
/// 全交给纯函数 `trialPick` 判（没榜 / 岛外无对比 / 综合分低于 1.3 都不套，并把原因说出来）。
setTexturePlanProvider((name, hash) => api.meshTexturePlan(state.selected, name, hash));

// 分层计划带回「这只网格自己的材质表里有哪些贴图」：槽位清单只列这些名字。
// 大组里同组有十几个模型，整组槽位混在一起会让人把别的模型的图标到这只身上。
setTexturePlanObserver((plan) => {
  activeSlotNames = plan && Array.isArray(plan.slotNames) && plan.slotNames.length
    ? new Set(plan.slotNames.map((n) => String(n).toLowerCase()))
    : null;
  if (texSource && !el("secTex").hidden) paintTex(texSource);
});

setTrialProvider(async (name) => {
  trialApplied = null;
  paintTrialBadge();
  const groups = (texReply && texReply.textureCandidates) || [];
  // 画布给的是完整路径，榜里只有文件名：按最后一段比。
  const base = (s) => String(s || "").replaceAll("\\", "/").split("/").pop().toLowerCase();
  const want = base(name);
  const g = groups.find((x) => base(x.mesh) === want);
  // 没这只网格的榜就不套，**绝不退回第一份**——那会把脸的贴图套到头发上。
  if (!g) return { skip: "这只网格没有候选榜" };
  const pick = trialPick(g);
  if (pick.skip) return { skip: pick.skip };
  const c = pick.candidate;
  let png = c.png;
  if (!png && api.candidatePng) {
    try {
      png = await api.candidatePng(c.hash);
    } catch {
      png = null;
    }
  }
  if (!png) return { skip: "榜首那张的缩略图没解出来" };
  c.png = png; // 回填给「套上看看」复用，省一次开容器
  trialApplied = { gi: groups.indexOf(g), idx: 0, mesh: want };
  paintTrialBadge();
  const adj = Number.isFinite(Number(c.adjustedScore)) ? ` · 综合分 ${Number(c.adjustedScore).toFixed(2)}` : "";
  return { png, label: `${g.mesh} 候选 1${adj}` };
});

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

/// 每份榜顶上取一张 UV 岛分布图。为什么值得多这几枪：榜的分数全靠「岛内 vs 岛外」，
/// 而岛外有多少格子是看不见的——铺满整张的网格（覆盖率≈1）那份榜其实没有对比依据。
/// 取不到就写「没有 UV / 没读到」，不摆空图框。
async function loadUvMaps() {
  if (!api.uvMap) return;
  const reply = texReply;
  const slots = Array.from(el("texCand").querySelectorAll("[data-uvmap-for]"));
  for (const box of slots) {
    if (!box.isConnected || texReply !== reply) return;
    try {
      const m = await api.uvMap(box.dataset.uvmapFor);
      if (!box.isConnected || texReply !== reply) return;
      box.innerHTML = m && m.png
        ? uvMapHtml(m)
        : `<span class="dim">这只网格没有 UV，画不出岛分布图</span>`;
    } catch {
      if (box.isConnected) box.innerHTML = `<span class="dim">岛分布图没读到</span>`;
    }
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
  // 占位条与它那张图同处一个 figure：按 data-ph-for=hash 找，找不到就算了（旧缓存）。
  const phOf = (img) =>
    img.parentElement?.querySelector(`[data-ph-for="${CSS.escape(img.dataset.hash)}"]`) || null;
  const note = el("texNote");
  const baseNote = note.textContent;
  for (const [i, img] of imgs.entries()) {
    if (!img.isConnected || texReply !== reply) return; // 已被下一轮 paint 换掉
    const ph = phOf(img);
    if (ph) ph.textContent = `正在解第 ${i + 1} / ${imgs.length} 张…`;
    try {
      const png = await api.candidatePng(img.dataset.hash);
      if (!img.isConnected || texReply !== reply) return;
      if (png) {
        img.src = png;
        if (ph) ph.remove();
        const c = byHash(img.dataset.hash);
        if (c && !c.png) c.png = png;
      } else if (ph) {
        ph.textContent = "这张解不出来：容器里没有它";
        img.title = "缩略图没读出来";
      }
    } catch (e) {
      // 原因写上卡面：只挂在 title 里等于没说，用户只会看到一格空。
      if (ph) ph.textContent = `这张解不出来：${String((e && e.message) || e)}`;
      img.title = "缩略图没读出来";
    }
  }
  if (note.textContent === baseNote && imgs.length) {
    note.textContent = `${baseNote} · 候选缩略图 ${imgs.length} 张已逐张现解（每张要开一次容器）`;
  }
}

/// 网格 meta 的前两段（顶点 / 三角面）与贴图状态无关，重写后段时要留着；
/// 多件模式的「整组 N 件 · 当前 x」也要留着，否则确认一条就丢掉当前件上下文。
function meshMetaHead() {
  const seg = el("meshMeta").textContent.split(" · ");
  const keep = seg.filter((s, i) => i < 2 || /^(整组 |当前 )/.test(s));
  return keep.join(" · ");
}

/// 分层计划 → 一句人话。特效层与不透明材质层分开数，不把第二材质说成特效；
/// 末尾带上**可核的那对数**：颜色贴图张数与子网格段数对不对得上。
function layeredMetaLine(plan) {
  const fx = Math.max(0, Number(plan && plan.effectLayers) || 0);
  const op = Math.max(0, Number(plan && plan.opaqueLayers) || 0);
  const extra = [fx ? `${fx} 层特效` : "", op ? `${op} 层材质` : ""].filter(Boolean);
  const evShort = evidenceShort(plan && plan.evidence);
  const evTxt = evShort ? ` · ${evShort}` : "";
  return `${meshMetaHead()} · ${
    extra.length ? `按子网格分层：基础 + ${extra.join(" + ")}（层次按材质表排）` : "按子网格分层：基础层"
  }${evTxt}`;
}

el("secTex").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.act === "clearTrial") {
    const ok = clearMeshTexture();
    el("texNote").textContent = ok
      ? "已退回灰模。立体预览上刚才套的可能是试贴，不是客户端认定的贴图。"
      : "现在没有正在显示的模型，无需退回。";
    return;
  }
  if (b.dataset.act === "warm") {
    // 「后台跑完它们」要能在没有候选榜时点得动：那一路 texReply 恰恰是空的。
    const msg = await api.textureWarmStart();
    el("texNote").textContent = String(msg || "已开始后台批量试贴");
    refreshWarm();
    return;
  }
  if (!texReply) return;
  const groups = texReply.textureCandidates || [];
  const group = groups[Number(b.dataset.gi)];
  const slots = texReply.texSlots || [];
  // 客户端自动对上的真文件：不是候选榜的猜测，单独一条路。
  if (b.dataset.act === "try-auto") {
    try {
      const png = await api.candidatePng(b.dataset.hash);
      if (!png) {
        el("texNote").textContent = "客户端自动对上的这张没解出来（容器里没有它）。";
      } else if (tryLayerTexture(b.dataset.slot, png)) {
        el("texNote").textContent = "已只套到这条槽位对应的子网格层，其它层保持原样。";
      } else if (!applyTexture(png)) {
        el("texNote").textContent = "先在上方立体预览里把网格调出来，才能套贴图。";
      } else {
        el("texNote").textContent = "已套上客户端自动对上的那张（convert/dxt 路径，不是候选榜猜的）。";
      }
    } catch (e) {
      el("texNote").textContent = `客户端自动对上的这张没解出来：${String((e && e.message) || e)}`;
    }
    return;
  }
  if (b.dataset.act === "confirm-auto") {
    const slotName = b.dataset.slot;
    const cfg = b.dataset.cfg || null;
    const hash = b.dataset.hash;
    try {
      await api.textureOverrideSet(
        slotName,
        cfg,
        hash,
        "客户端自动对上（convert/dxt）",
        group && group.mesh,
      );
      const hit = slots.find((s) => s.name === slotName && String(s.cfgPath || "") === String(cfg || ""));
      if (hit) hit.overrideHash = hash;
      // 重画整栏（不是只重画槽位）：自动卡上的「人工标注是另一张」警告必须当场消失。
      if (texSource) paintTex(texSource);
      // 确认一条槽位后要重取**分层计划**，不能拿单张图把全部子网格盖回去。
      const plan = await refreshTexturePlan();
      if (plan) {
        el("meshMeta").textContent = layeredMetaLine(plan);
      } else {
        try {
          const png = await api.candidatePng(hash);
          if (png && applyTexture(png)) {
            el("meshMeta").textContent = `${meshMetaHead()} · 已套用人工确认的贴图`;
          }
        } catch {
          // 图没解出来：表已经写进去了，下面那句说明状态。
        }
      }
      el("texNote").textContent = `已记进覆盖表：${slotName} ← 客户端自动对上的那张（convert/dxt）`;
    } catch (e) {
      el("texNote").textContent = `没写进覆盖表：${String((e && e.message) || e)}`;
    }
    return;
  }
  if (b.dataset.act === "try") {
    const c = group && group.candidates[Number(b.dataset.idx)];
    if (c && !applyTexture(c.png)) el("texNote").textContent = "先在上方立体预览里把网格调出来，才能套贴图。";
    return;
  }
  if (b.dataset.act === "confirm") {
    const pick = b.closest(".tex-group")?.querySelector(".tex-slot-pick");
    const chosen = confirmTarget(slots, pick ? pick.value : null);
    if (chosen.reason) {
      el("texNote").textContent = chosen.reason;
      return;
    }
    const slot = chosen.slot;
    const idx = Number(b.dataset.idx);
    const c = group && group.candidates[idx];
    if (!c) return;
    // 把画布上那只网格一起写进表：槽名和网格名不同名时（头发/衣服），
    // 只靠「网格同名槽」找不到这条确认，模型下次打开就不会自动套上。
    await api.textureOverrideSet(
      slot.name,
      slot.cfgPath,
      c.hash,
      "uvfit v1 人工确认",
      group.mesh,
    );
    // 只重画槽位清单，不整页重刷：实测一次 showDetail 要 2.8 秒（20 张缩略图 + 2 张
    // 分布图全得重解一遍），而人在做的事是「连着标十几条」——每标一条闪回灰框、
    // 滚动位置丢一次，就没人标得下去了。撤销那条路保持整页重刷：它要把槽位还回下拉，
    // 那是偶尔才做一次的動作，慢一点换来的一定是状态干净。
    slot.overrideHash = c.hash;
    el("texSlots").innerHTML = texSlotsHtml(slots, Boolean(texReply));
    for (const g of el("texCand").querySelectorAll(".tex-group")) {
      const sel = g.querySelector(".tex-slot-pick");
      if (!sel) continue;
      const opt = Array.from(sel.options).find((o) => o.value === slot.name);
      if (opt) sel.removeChild(opt);
      if (!sel.options.length) {
        const lab = sel.closest("label");
        if (lab) lab.outerHTML = `<span class="dim">所有槽位都已确认（撤销后可重选）</span>`;
      }
    }
    el("texNote").textContent =
      `已记进覆盖表：${slot.name} ← 第 ${idx + 1} 张（榜和图都不重画，接着标下一条）`;
    // 确认的成果得当场看得见。上一版只把槽位清单画成 🟢，模型身上仍是那张未确认的试贴，
    // 人点完会以为"没生效"——实测要重开一次模型才换上（10-11 真窗口撞到的）。
    // 2026-10-26 起先重取分层计划：确认的可能只是某个特效槽，不能把整只网格换成单张图。
    const plan = await refreshTexturePlan();
    if (plan) {
      el("meshMeta").textContent = layeredMetaLine(plan);
    } else if (api.meshTextureOverride) {
      try {
        const r = await api.meshTextureOverride(group.mesh);
        if (r && r.png && applyTexture(r.png)) {
          el("meshMeta").textContent = `${meshMetaHead()} · 已套用人工确认的贴图（${r.slot}）`;
        }
      } catch {
        // 确认的贴图解不出来就别装作套上了：留着原来那句，让说明行说清发生了什么。
        el("texNote").textContent =
          `已记进覆盖表：${slot.name} ← 第 ${idx + 1} 张，但那张图现在解不出来，模型上还是原来的样子`;
      }
    }
    return;
  }
  if (b.dataset.act === "clear") {
    await api.textureOverrideClear(b.dataset.slot, b.dataset.cfg);
    showDetail(texGid || state.selected);
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
