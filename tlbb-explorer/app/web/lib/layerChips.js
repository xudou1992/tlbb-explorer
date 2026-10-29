// 分层筹码的标签：把后端的「哪段几何用哪张图」翻成「基础 / 特效 2 / 材质 3 · 第 4 段」。
// 纯函数，不碰 DOM——这样 node 里能直接钉住，真窗口只负责摆按钮。
//
// 段号是**证据**，不是装饰：分层顺序是按材质表排的推断，人点开「只看这一层」时
// 要能对上「这层说的是第几段」，才能发现配错（2026-10-27 用户要的可核性）。

/// 这层盖的是第几段子网格。`faceCounts` 是每段的面数；层给的是 faceStart/faceCount。
/// 跨多段的（基础层吞掉前几段）报成「第 1–3 段」；对不上任何段回空串，不编。
export function layerSegmentLabel(plan, k) {
  const counts = (plan && Array.isArray(plan.faceCounts) && plan.faceCounts) || [];
  const l = plan && plan.layers && plan.layers[k];
  if (!l || !counts.length) return "";
  let at = 0;
  let first = -1;
  let last = -1;
  for (let i = 0; i < counts.length; i++) {
    const start = at;
    const end = at + counts[i];
    at = end;
    if (l.faceStart < end && l.faceStart + l.faceCount > start) {
      if (first < 0) first = i;
      last = i;
    }
  }
  if (first < 0) return "";
  return first === last ? `第 ${first + 1} 段` : `第 ${first + 1}–${last + 1} 段`;
}

/// 每层的筹码文案：`{k, name, seg, title}`。层数为 0 回空数组（界面据此收起筹码行）。
/// 名字只分三类：第 0 层是基础，其余按后端给的混合模式叫「特效」或「材质」。
export function layerChipLabels(plan) {
  const layers = (plan && Array.isArray(plan.layers) && plan.layers) || [];
  return layers.map((l, k) => {
    const seg = layerSegmentLabel(plan, k);
    const name = k === 0 ? "基础" : l && l.blend === "add" ? `特效 ${k}` : `材质 ${k}`;
    const title = [String((l && l.slot) || ""), seg].filter(Boolean).join(" · ");
    return { k, name, seg, title };
  });
}

/// 对齐证据 → 标题里的短句。**与后端 `evidence_line` 同一口径**（三形状各说各的）：
/// 相等 = 一张对一段；颜色少于段 = 材质表就那么几张、其余段按基础层铺；
/// 颜色多于段 = 多出的叠在基础段上。改口径要两边一起改。
export function evidenceShort(ev) {
  if (!ev || !ev.submeshes) return "";
  const c = Number(ev.colorLayers) || 0;
  const n = Number(ev.submeshes) || 0;
  if (ev.aligned) return `颜色 ${c} 张 = 子网格 ${n} 段`;
  if (c < n) return `颜色 ${c} 张 < 子网格 ${n} 段（其余 ${n - c} 段按基础层铺）`;
  return `颜色 ${c} 张 > 子网格 ${n} 段（多出的 ${c - n} 张叠在基础段上）`;
}
