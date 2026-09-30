/// 动作页的纯函数：把「整条动作的关键帧」按游标切成一帧的表。
///
/// 判断全部放这里，因为这一层有 node --test 盯着；DOM 侧只负责摆，不算数。
/// 纪律与全库一致：后端没给的不编，名字空的骨写「未命名骨」而不是造一个。

/// 游标夹在 [0, frames-1]。越界、非数字都退回 0，不让表格出现空洞。
export function clampFrame(v, frames) {
  const n = Number(v);
  if (!Number.isFinite(n) || !(frames > 0)) return 0;
  return Math.min(Math.max(0, Math.trunc(n)), frames - 1);
}

/// 第 frame 帧的表行。缺帧数据（长度不齐）时该格给 null，由界面显示「—」。
export function frameRows(tracks, frame) {
  const f = clampFrame(frame, (tracks || []).reduce((m, t) => Math.max(m, t.rotations?.length || 0), 0));
  return (tracks || []).map((t) => ({
    bone: t.bone && t.bone.length ? t.bone : "未命名骨",
    quat: t.rotations?.[f] ?? null,
    pos: t.positions?.[f] ?? null,
    scale: Number.isFinite(t.scales?.[f]) ? t.scales[f] : null,
  }));
}

/// 只列「这一帧跟第一帧不一样」的骨：46 根骨里通常只有十几根在动，
/// 全列出来等于让人自己在几百行里找变化。
export function changedRows(tracks, frame) {
  const rows = frameRows(tracks, frame);
  const base = frameRows(tracks, 0);
  const same = (a, b) =>
    a === null || b === null ? a === b : a.every((v, i) => Math.abs(v - (b[i] ?? Infinity)) < 1e-6);
  return rows.filter((r, i) => frame > 0 && !(same(r.quat, base[i].quat) && same(r.pos, base[i].pos)));
}

/// 摘要一行。帧率刻度按后端原话带出，不换算成秒——含义没证。
export function animSummary(rep, frame) {
  if (!rep || !rep.tracks?.length) return "这条动作没读到关键帧数据。";
  const f = clampFrame(frame, rep.frames);
  return (
    `${rep.file} · ${rep.bones} 根骨 · 第 ${f + 1} / ${rep.frames} 帧 · ` +
    `会动的骨 ${rep.moving} 根 · 帧率刻度 ${rep.tick}（含义未证，不换算成秒）`
  );
}
