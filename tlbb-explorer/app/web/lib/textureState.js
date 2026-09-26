// 贴图试贴候选区块：asset_inspect 回包 → 展示状态。纯函数，node --test 盯着。
//
// 状态口径（2026-09-26 用户裁定，不许混）：
//   🟢 已确定   = 覆盖表（model_texture_override.json）里有人工确认记录
//   🟡 候选     = uvfit 离线试贴排出来的榜，**未确认**
//   🔴 无法确定 = 没有候选缓存（没有就是没有，不编造）
//
// 候选分数是 uvfit 的「UV 岛内外方差比」——特征指标，不是归属概率，
// 所以界面上必须带「未确认」字样；确认只能来自覆盖表。

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function hash8(h) {
  return esc(String(h || "").slice(0, 8));
}

/// 槽位清单：每行一个槽，🟢 带「撤销」。
export function texSlotsHtml(slots = []) {
  if (!slots.length) return "";
  return `<ul class="tex-slots">` + slots.map((s) => {
    if (s.overrideHash) {
      return `<li>🟢 <b>${esc(s.name)}</b>：已人工确认 → ${hash8(s.overrideHash)}…
        <button type="button" data-act="clear" data-slot="${esc(s.name)}" data-cfg="${esc(s.cfgPath || "")}">撤销</button></li>`;
    }
    return `<li>🟡 <b>${esc(s.name)}</b>：候选未确认${s.cfgPath ? `（出处 ${esc(s.cfgPath)}）` : ""}</li>`;
  }).join("") + `</ul>`;
}

/// 候选卡：图 + 特征证据 + 两颗按钮。分数只作排序参考，必须写「未确认」。
export function texCandidatesHtml(group, slots = []) {
  if (!group || !Array.isArray(group.candidates) || !group.candidates.length) return "";
  const openSlots = slots.filter((s) => !s.overrideHash);
  const pick = openSlots.length
    ? `<label class="dim">确认到槽位：<select id="texSlotPick">` +
      openSlots.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join("") +
      `</select></label>`
    : `<span class="dim">所有槽位都已确认（撤销后可重选）</span>`;
  const cards = group.candidates.map((c, i) => `
    <figure class="tex-cand">
      <img src="${esc(c.png)}" alt="候选贴图 ${i + 1}">
      <figcaption>候选 ${i + 1} · ${esc(c.w)}×${esc(c.h)} ${esc(c.codec)} · ${esc(c.mips)} 级 mip<br>
      UV 对齐分 ${Number(c.score).toFixed(1)}（<b>未确认</b>）</figcaption>
      <button type="button" data-act="try" data-idx="${i}">套上看看</button>
      <button type="button" data-act="confirm" data-idx="${i}">确认这张</button>
    </figure>`);
  return `${pick}<div class="tex-grid">${cards.join("")}</div>`;
}

/// 回包 → 区块内容。没有候选也没有槽位就回 null（区块整个不出现）。
export function texBlock(reply) {
  const slots = (reply && reply.texSlots) || [];
  const groups = (reply && reply.textureCandidates) || [];
  if (!slots.length && !groups.length) return null;
  const group = groups[0] || null;
  const confirmed = slots.filter((s) => s.overrideHash).length;
  const note = group
    ? `按网格 ${esc(group.mesh)} 的 UV 离线试贴排序 · 从 ${group.pool} 张匿名贴图中选出 · 全部未确认`
    : `${slots.length} 个槽位，还没有试贴缓存`;
  return {
    slotsHtml: texSlotsHtml(slots),
    candHtml: texCandidatesHtml(group, slots),
    note,
    confirmed,
    total: slots.length,
  };
}
