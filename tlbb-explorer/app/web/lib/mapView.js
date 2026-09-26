// 地图浏览器的白话口径（v0.3.1）。纯函数，node --test 盯着。
//
// 别名红线（2026-09-26）：别名只来自人工标注/证据（map_aliases.json），
// 没有证据就叫「未命名地图」；原始 ID 永远另行展示，绝不替换。
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
    `<span class="miss">地形：未解析（.map 是地表编码格，不是高低数据）</span><br />` +
    `<span class="part">贴图：部分可恢复（候选机制已就绪，见资产页的试贴候选）</span><br />` +
    `<span class="miss">碰撞：未解析</span><br />` +
    `<span class="miss">寻路：未解析</span><br />` +
    `<span class="miss">朝向：R 还是 Rᵀ 未证，待与客户端比对</span>`
  );
}
