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

/// v2 因子 → 一张卡上的证据行。
///
/// 缺因子（旧离线缓存没有这一份）就整行不摆：那三个百分比是「系统量出来的
/// 特征」，编不出来也不能拿 0 顶——0 看着像「完全不贴合」，实际是「没量过」。
const pct = (x) => `${Math.round(Number(x) * 100)}%`;
function factorLine(c) {
  const f = c.factors;
  if (!f) return "";
  const bits = [`UV 贴合 ${pct(f.uvFit)}`, `透明边界 ${pct(f.alphaFit)}`, `尺寸先验 ${pct(f.sizeFit)}`];
  if (f.blackBias) bits.push("整体偏黑");
  if (f.whiteBias) bits.push("整体偏白");
  // 平均色只有三个 0..255 的数，够标一个色点；它说明的是「这张整体什么色调」，
  // 不是「和模型该是什么颜色」——所以不写「颜色匹配」。
  const swatch = Array.isArray(f.meanColor) && f.meanColor.length === 3
    ? `<span class="tex-mean" title="平均色 rgb(${f.meanColor.map((n) => Number(n) || 0).join(", ")})" ` +
      `style="background:rgb(${f.meanColor.map((n) => Number(n) || 0).join(", ")})"></span>`
    : "";
  return `<span class="tex-facts dim">${esc(bits.join(" · "))}</span>${swatch}`;
}

/// 岛外方差 = 0 时 `score = insideVar / (outsideVar + 4)` 退化成「这张图自己有多忙」，
/// 榜的先后不再有任何「贴合」含义。旧缓存没这个字段（undefined）不算无对比——
/// 「没量过」不能写成「有对比」，也不能反过来。
function noContrast(c) {
  return c && c.outsideVar === 0;
}

/// 一行分数：有综合分就两个都写（综合分是排序依据，方差比是它的原料）；
/// 只有方差分（旧缓存）就只写方差分——不拿缺的那项凑数。
function scoreLine(c) {
  const adj = Number.isFinite(c.adjustedScore) ? `综合分 ${Number(c.adjustedScore).toFixed(2)} · ` : "";
  const nc = noContrast(c) ? " · 岛外无对比" : "";
  return `${adj}系统评分 ${Number(c.score).toFixed(1)}（<b>未确认</b>）${nc}`;
}

/// 区分度那一行：这张贴图在多少只模型的榜首出现过。
///
/// 全库实测榜首只来自 147 张贴图、其中一张当了 260 只模型的第一名——不写这一行，
/// 人会把「通吃型冠军」当成专为这只模型挑出来的那张。只有 ≥50 才追加那句劝退：
/// 少量重复是正常现象（同一张通用纹样确实会被多只模型用到），不许把正常说成可疑。
function spreadLine(c) {
  const n = Number(c.alsoFirstFor);
  if (!Number.isFinite(n) || n <= 0) return "";
  const warn = n >= 50 ? "——它对这只模型说明得很少" : "";
  return `<br><span class="dim">这张在 ${esc(n)} 只模型的榜首出现过${warn}</span>`;
}

/// 候选卡：图 + 特征证据 + 两颗按钮。分数只作排序参考，必须写「未确认」。
/// 措辞原则（用户裁定）：这是系统排出来的指标分，不许写成「UV 对齐分」暗示正确率。
/// 全库批量缓存（source=batch）候选不带内嵌 PNG：img 不给 src，只摆占位框并标记
/// data-need-png + data-hash，由 detail.js 按编号现解——数据里没有的图不编造，
/// 现解失败也保持占位。旧缓存自带 data URL，照旧直接嵌。
/// `gi`/`gn` 是这只网格在第几份榜、共几份：一只怪常有多个网格，每份都要摆出来，
/// 只铺第一份等于让人工确认剩下几只时无从下手。按钮带 data-gi 回指自己的榜。
export function texCandidatesHtml(group, slots = [], gi = 0, gn = 1) {
  if (!group || !Array.isArray(group.candidates) || !group.candidates.length) return "";
  const openSlots = slots.filter((s) => !s.overrideHash);
  const pick = openSlots.length
    ? `<label class="dim">确认到槽位：<select class="tex-slot-pick"${gi === 0 ? ` id="texSlotPick"` : ""}>` +
      openSlots.map((s) => `<option value="${esc(s.name)}">${esc(s.name)}</option>`).join("") +
      `</select></label>`
    : `<span class="dim">所有槽位都已确认（撤销后可重选）</span>`;
  const head = gn > 1
    ? `<p class="dim">第 ${gi + 1} / ${gn} 份榜 · 网格 ${esc(group.mesh)}</p>`
    : "";
  // 榜首没了对比度，整份榜的含义就变了——这句话必须跟在人眼前，不能只写在卡片脚注里。
  const warn = noContrast(group.candidates[0])
    ? `<p class="dim">榜首那张的岛外像素方差是 0：这份榜只排得出「谁更忙」，排不出「谁贴合」，别照着它确认。</p>`
    : "";
  const cards = group.candidates.map((c, i) => {
    // 批量缓存的候选不带内嵌图：卡面必须先有一个**看得见**的占位（一行说明字 +
    // 底纹框），不能只放一张没有 src 的 img——浏览器那会儿画的是破图角，
    // 用户看到的就是「贴图呢」。占位文字由 detail.js 逐张更新（正在解 / 解不出来原因），
    // 解出来就整条撤掉换成图。
    const img = c.png
      ? `<img src="${esc(c.png)}" alt="候选贴图 ${i + 1}">`
      : `<span class="tex-ph" data-ph-for="${esc(c.hash)}">缩略图要现解，解出来自动填在这儿</span>
         <img alt="候选贴图 ${i + 1}" data-need-png="1" data-hash="${esc(c.hash)}">`;
    return `
    <figure class="tex-cand">
      ${img}
      <figcaption>候选 ${i + 1} · ${esc(c.w)}×${esc(c.h)} ${esc(c.codec)} · ${esc(c.mips)} 级 mip<br>
      ${scoreLine(c)}<br>${factorLine(c)}${spreadLine(c)}</figcaption>
      <button type="button" data-act="try" data-gi="${gi}" data-idx="${i}">套上看看</button>
      <button type="button" data-act="confirm" data-gi="${gi}" data-idx="${i}">确认这张</button>
    </figure>`;
  });
  return `<div class="tex-group" data-gi="${gi}">${head}${warn}${pick}<div class="tex-grid">${cards.join("")}</div></div>`;
}

/// 立体预览自动试贴的取舍：**只有说得出「凭什么试这张」才套**。
/// 三种情况不套，并把原因原样交给界面显示（不静默留灰模）：
///   · 没有候选榜；
///   · 榜首那张岛外方差为 0 —— 分数里没有对比，套上只会误导；
///   · 榜首综合分 < 1.3 —— 与批量统计里「度量退化」那条带同一个阈值，两处必须一起改。
export function trialPick(group) {
  const cs = group && group.candidates;
  if (!Array.isArray(cs) || !cs.length) return { skip: "这只网格没有候选榜" };
  const c = cs[0];
  if (c.outsideVar === 0) return { skip: "榜首那张岛外没有可比像素，套上只会误导" };
  const adj = Number(c.adjustedScore);
  if (Number.isFinite(adj) && adj < 1.3) {
    return { skip: `榜首综合分 ${adj.toFixed(2)} 低于 1.3，分数说明不了贴合` };
  }
  return { candidate: c };
}

/// 后台批量试贴的入口状态（texture_warm_status 回包）。只在「这只网格还没有
/// 候选榜」时说话——有榜就不用提这事。
///
/// 三种口径必须分开：pending 是数字（还差 N 只）、0（全库都进榜了）、
/// null/缺字段（数不出来，本机没有资源清单库）。最后一种绝不许写成
/// 「都跑完了」——那是把「不知道」说成结论。
function warmControl(warm) {
  if (!warm) return "";
  if (warm.running) return `<p class="dim">后台批量试贴已经在跑了，跑完这一栏会自己更新。</p>`;
  if (warm.pending === null || warm.pending === undefined) {
    return `<p class="dim">还差多少只模型没进榜：数不出来（读不到资源清单）。</p>`;
  }
  if (!warm.pending) return `<p class="dim">全库模型都已进批量试贴榜，这只网格是榜里没有可用候选。</p>`;
  return `<p class="dim">这只网格还没进榜：全库还差 <b>${Number(warm.pending)}</b> 只模型没跑批量试贴。
    <button type="button" data-act="warm">后台跑完它们</button></p>`;
}

/// 回包 → 区块内容。没有候选也没有槽位就回 null（区块整个不出现）。
/// `warm` 是后台批量试贴的状态，只影响「没有榜」时的那句话。
export function texBlock(reply, warm = null) {
  const slots = (reply && reply.texSlots) || [];
  const groups = (reply && reply.textureCandidates) || [];
  if (!slots.length && !groups.length) return null;
  const group = groups[0] || null;
  const confirmed = slots.filter((s) => s.overrideHash).length;
  // 排序依据这句话跟着后端口径走（group.ranked）：综合分怎么算、什么时候才重排，
  // 规则在 Rust 那边，前端照着它写的说，免得改了公式而这句话还在说「按 UV 排」。
  const basis = group && group.ranked ? "UV 贴合 × 尺寸 × 透明边界的综合分" : "UV 岛内外方差比";
  const many = groups.length > 1 ? `这一组有 ${groups.length} 只网格，各出一份榜（` : "按网格 " + esc(group?.mesh) + " 的离线试贴排序（";
  const note = group
    ? `${many}${basis}） · 从 ${group.pool} 张匿名贴图中选出 · 全部未确认`
    : `引用了 ${slots.length} 张贴图，包里都没对上文件；离线试贴还没跑，下面只是名字清单，不是候选榜`;
  return {
    slotsHtml: texSlotsHtml(slots, Boolean(group)) + (group ? "" : warmControl(warm)),
    // 有榜就摆一颗撤图按钮：自动试贴会把贴图盖在模型上，得有一眼可见的路退回灰模。
    candHtml:
      groups.map((g, i) => texCandidatesHtml(g, slots, i, groups.length)).join("") +
      `<p class="dim"><button type="button" data-act="clearTrial">退回灰模</button>` +
      ` 立体预览可能自动套着榜首候选作试贴——那是猜测，不是客户端认定的那张。</p>`,
    note,
    confirmed,
    total: slots.length,
  };
}
