// 预览放大：3D 画布默认只有 360px 高，看衣服细节不够。每个画布舞台右上角
// 加一枚「放大」按钮，点了把它铺到视口（固定定位 + 背景遮罩），再点或按 Esc 还原。
//
// 不改画布本身的尺寸语义：只给舞台加/去 `.zoomed` 类，CSS 负责撑开；
// 变化后发一个 `tlbb:viewer-resize` 事件，MeshViewer 收到就 syncViewport + 重画。
// 事件而不是直接持有 viewer：舞台和 viewer 分属不同模块，彼此不知道对方。

const HOSTS = ".mesh-stage, .map-stage";

/// 给任意画布舞台补一枚「放大」按钮。浏览页的预览盒子是点文件时才建的，
/// 启动时扫不到，必须由建舞台的一方主动叫一声。
export function attachStageZoom(stage) {
  if (!stage || !stage.querySelector("canvas")) return;
  if (stage.querySelector(":scope > .stage-zoom")) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "stage-zoom";
  btn.textContent = "放大";
  btn.title = "把这块预览铺满窗口（Esc 还原）";
  btn.addEventListener("click", () => toggleStage(stage));
  stage.appendChild(btn);
}

export function initStageZoom() {
  for (const stage of document.querySelectorAll(HOSTS)) attachStageZoom(stage);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const z = document.querySelector(".mesh-stage.zoomed, .map-stage.zoomed");
    if (z) toggleStage(z);
  });
  // 点放大块以外的任何地方（遮罩）也还原：遮罩本来就挡住了页面，
  // 让人非去找 Esc 是多余的。
  document.addEventListener(
    "click",
    (e) => {
      const z = document.querySelector(".mesh-stage.zoomed, .map-stage.zoomed");
      if (!z || z.contains(e.target)) return;
      toggleStage(z);
    },
    true,
  );
}

function toggleStage(stage) {
  // 画布还没就绪（地图正在读格子、或这张图本来就没有可画的东西）时不放大：
  // 铺出来只会是一块空白面板，还把「正在读」的提示挡在遮罩后面。
  const ready = [...stage.querySelectorAll("canvas")].some(
    (c) => !c.hidden && c.offsetWidth > 0 && c.offsetHeight > 0,
  );
  if (!ready) return;
  const on = stage.classList.toggle("zoomed");
  const btn = stage.querySelector(":scope > .stage-zoom");
  if (btn) {
    btn.textContent = on ? "还原" : "放大";
    btn.title = on ? "回到原来的大小（Esc）" : "把这块预览铺满窗口（Esc 还原）";
  }
  const any = Boolean(document.querySelector(".mesh-stage.zoomed, .map-stage.zoomed"));
  document.body.classList.toggle("stage-zoom-open", any);
  window.dispatchEvent(new Event("tlbb:viewer-resize"));
}
