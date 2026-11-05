// 地图浏览器的白话口径（v0.3.1）。纯函数，node --test 盯着。
//
// 别名红线（2026-09-26）：别名只来自人工标注/证据（map_aliases.json），
// 没有证据就叫「未命名地图」；原始 ID 永远另行展示，绝不替换。
import { CELL, clustersOf, mainClusterBounds, occupiedCells } from "./topdownMath.js";

export const UNNAMED_MAP = "未命名地图";

export function rowLabel(alias) {
  return alias && String(alias).trim() ? String(alias).trim() : UNNAMED_MAP;
}

/// 「这张地图」头部事实。只回包里有的字段；类型（城镇/副本）没有数据来源，不显示。
export function factsHeader(s) {
  const unresolved = Number(s.records || 0) - Number(s.resolved || 0);
  return [
    ["名称", s.alias ? `${s.alias}（人工标注）` : `${UNNAMED_MAP}（没有证据别名）`],
    ["ID", `${s.id}（客户端原文，永远保留）`],
    ["格子", `${s.grids} 个`],
    ["实例", `${s.records} 条`],
    ["成功定位", `${s.resolved} 条`],
    ["无法定位", `${unresolved} 条（分母是上面的实测实例数）`],
  ];
}

/// 「还没解的」状态块。口径：只陈述事实——部分可恢复的贴图要写明依据，
/// 没解的直说没解，不许把「没读」说成「客户端没有」。
export function unresolvedHtml() {
  return (
    `<span class="miss">地形：未解析（.map 是地表编码格，不是高低数据；有 .map 的图已把编码格叠成底图：绿=地面、灰蓝=其它、黑=空）</span><br />` +
    `<span class="part">贴图：部分可恢复（候选机制已就绪，见资产页的试贴候选）</span><br />` +
    `<span class="miss">碰撞：未解析</span><br />` +
    `<span class="miss">寻路：未解析</span><br />` +
    `<span class="part">朝向：矩阵按文件原序直读（与客户端同序），R/Rᵀ 的叫法不影响画面；与游戏逐点比对未做</span>`
  );
}

/// 主簇/孤悬格计数。两个视图说同一句话，口径必须一样；算不出来回 null。
export function clusterStats(instances, gridFiles) {
  const cells = occupiedCells(instances || [], gridFiles || []);
  if (!cells.length) return null;
  const clusters = clustersOf(cells);
  const mainCells = clusters.length ? clusters[0].length : 0;
  return { cells: cells.length, clusters: clusters.length, mainCells, stray: cells.length - mainCells };
}

/// 立体视图的取景盒：只罩连片主体（主簇），孤悬格不参与定相机。
///
/// 实测 w1351_ll_wls_001：2,240 件里有一格孤悬在 1,466 单位外，按**全体**包围盒
/// 定相机会把 320 单位的主体压成画面上一块 22% 大小、还偏在左上角的东西——看着
/// 像「这张图什么都没画」。俯视和列表缩略图早就按 mainClusterBounds 取景（同一
/// 口径是钉过的规矩），立体视图是唯一没跟上的那一面。
export function clusterFrame(instances, gridFiles) {
  const box = mainClusterBounds(occupiedCells(instances || [], gridFiles || []));
  if (!box) return null;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, z0 = Infinity, z1 = -Infinity;
  let kept = 0;
  for (const it of instances || []) {
    const m = it && it.matrix;
    if (!m || m.length < 16) continue;
    const x = m[12], y = m[13], z = m[14];
    if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) continue;
    // 格子范围罩得住全簇物件（物件实测都躺在自己格子的 32×32 里），留一格余量。
    if (x < box.x0 - CELL || x > box.x1 + CELL || z < box.z0 - CELL || z > box.z1 + CELL) continue;
    if (x < x0) x0 = x;
    if (x > x1) x1 = x;
    if (y < y0) y0 = y;
    if (y > y1) y1 = y;
    if (z < z0) z0 = z;
    if (z > z1) z1 = z;
    kept++;
  }
  if (!kept) return null;
  return {
    center: [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2],
    size: Math.max(x1 - x0, y1 - y0, z1 - z0, 1),
    kept,
  };
}
