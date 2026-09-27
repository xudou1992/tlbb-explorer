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
/// 🟡 只许标"试贴榜里排出来的候选"（tried=true）；离线试贴没跑过时这个槽
/// 只是"材质引用了、包里没对上文件"的名字——挂 🟡 会把名字清单冒充成候选榜。
export function texSlotsHtml(slots = [], tried = true) {
  if (!slots.length) return "";
  return `<ul class="tex-slots">` + slots.map((s) => {
    if (s.overrideHash) {
      return `<li>🟢 <b>${esc(s.name)}</b>：已人工确认 → ${hash8(s.overrideHash)}…
        <button type="button" data-act="clear" data-slot="${esc(s.name)}" data-cfg="${esc(s.cfgPath || "")}">撤销</button></li>`;
    }
    if (tried) {
      return `<li>🟡 <b>${esc(s.name)}</b>：候选未确认${s.cfgPath ? `（出处 ${esc(s.cfgPath)}）` : ""}</li>`;
    }
    return `<li>⬜ <b>${esc(s.name)}</b>：引用未确认${s.cfgPath ? `（cfg 登记路径 ${esc(s.cfgPath)}，包里没有该文件；离线试贴还没跑）` : "（离线试贴还没跑）"}</li>`;
  }).join("") + `</ul>`;
}

/// 候选卡：图 + 特征证据 + 两颗按钮。分数只作排序参考，必须写「未确认」。
/// 措辞原则（用户裁定）：这是系统排出来的指标分，不许写成「UV 对齐分」暗示正确率。
/// 全库批量缓存（source=batch）候选不带内嵌 PNG：img 不给 src，只摆占位框并标记
/// data-need-png，由 detail.js 按（网格, 名次）现解——数据里没有的图不编造，
/// 现解失败也保持占位。旧缓存自带 data URL，照旧直接嵌。
export function texCandidatesHtml(group, slots = []) {
  if (!group || !Array.isArray(group.candidates) || !group.candidates.length) return "";
  const openSlots = slots.filter((s) => !s.overrideHash);
  const pick = openSlots.length
    ? `<label class="dim">确认到槽位：<select id="texSlotPick">` +
      openSlots.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join("") +
      `</select></label>`
    : `<span class="dim">所有槽位都已确认（撤销后可重选）</span>`;
  const cards = group.candidates.map((c, i) => {
    const img = c.png
      ? `<img src="${esc(c.png)}" alt="候选贴图 ${i + 1}">`
      : `<img alt="候选贴图 ${i + 1}" data-need-png="1" data-idx="${i}" data-mesh="${esc(group.mesh)}">`;
    return `
    <figure class="tex-cand">
      ${img}
      <figcaption>候选 ${i + 1} · ${esc(c.w)}×${esc(c.h)} ${esc(c.codec)} · ${esc(c.mips)} 级 mip<br>
      系统评分 ${Number(c.score).toFixed(1)}（<b>未确认</b>）</figcaption>
      <button type="button" data-act="try" data-idx="${i}">套上看看</button>
      <button type="button" data-act="confirm" data-idx="${i}">确认这张</button>
    </figure>`;
  });
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
    : `引用了 ${slots.length} 张贴图，包里都没对上文件；离线试贴还没跑，下面只是名字清单，不是候选榜`;
  return {
    slotsHtml: texSlotsHtml(slots, Boolean(group)),
    candHtml: texCandidatesHtml(group, slots),
    note,
    confirmed,
    total: slots.length,
  };
}
