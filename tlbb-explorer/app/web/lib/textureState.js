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
/// noUv=true 说的是"批量试贴真跑过、这只网格读不出 UV"——跟"还没跑"是两回事，
/// 不能共用「离线试贴还没跑」那句（那会让人一直等一件不会发生的事）。
export function texSlotsHtml(slots = [], tried = true, noUv = false) {
  if (!slots.length) return "";
  const autoText = (s) =>
    s.autoHash
      ? `客户端自动对上文件 ${s.autoWidth ?? "?"}×${s.autoHeight ?? "?"} ${esc(s.autoCodec || "")}${
          s.autoPath ? `（${esc(s.autoPath)}）` : ""
        }`
      : "";
  return `<ul class="tex-slots">` + slots.map((s) => {
    if (s.overrideHash) {
      const auto = autoText(s);
      const clash = s.autoHash && String(s.autoHash).toLowerCase() !== String(s.overrideHash).toLowerCase();
      return `<li>🟢 <b>${esc(s.name)}</b>：已人工确认 → ${hash8(s.overrideHash)}…
        ${auto ? ` · ${auto}` : ""}${clash ? " · <b>⚠ 人工标注与自动对上的不是同一张</b>" : ""}
        <button type="button" data-act="clear" data-slot="${esc(s.name)}" data-cfg="${esc(s.cfgPath || "")}">撤销</button></li>`;
    }
    if (s.autoHash) {
      return `<li>🔵 <b>${esc(s.name)}</b>：${autoText(s)}（客户端转换路径，不是候选榜猜的）</li>`;
    }
    if (tried) {
      const icon = s.resolved ? "；库里对上的可能是 UI 小图标" : "";
      return `<li>🟡 <b>${esc(s.name)}</b>：候选未确认${
        s.cfgPath ? `（出处 ${esc(s.cfgPath)}${icon}）` : icon ? `（${icon.slice(1)}）` : ""
      }</li>`;
    }
    // 已对上实体的名字也可能是 UI 小图标（玩家衣服基础色实测如此）；
    // 它仍是模型贴图槽，要允许改标，但不能把「对上了」说成「包里没有」。
    const where = s.cfgPath
      ? s.resolved
        ? `cfg 登记路径 ${esc(s.cfgPath)}，已对上实体（可能是 UI 小图标，不一定是模型大图）`
        : `cfg 登记路径 ${esc(s.cfgPath)}，包里没有该文件`
      : s.resolved
        ? "已对上实体（可能是 UI 小图标，不一定是模型大图）"
        : "";
    if (noUv) {
      return `<li>⬜ <b>${esc(s.name)}</b>：引用未确认${where ? `（${where}；这只网格读不出 UV，试贴排不出候选）` : "（这只网格读不出 UV，试贴排不出候选）"}</li>`;
    }
    return `<li>⬜ <b>${esc(s.name)}</b>：引用未确认${where ? `（${where}；离线试贴还没跑）` : "（离线试贴还没跑）"}</li>`;
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

/// 确认该写进哪一条槽位。**只认下拉当前选中的那条**，选不中就不写。
///
/// 旧写法是 `|| slots.find(s => !s.overrideHash)`：下拉值对不上时（列表刚重画、
/// 槽位换了人、脚本塞进去的野值）静默改标到「第一条未确认」——人以为标在自己
/// 看着的那一格，实际标到了别的槽。覆盖表是贴图线唯一的标准答案来源，
/// 一条错标比一条没标更贵，所以这里宁可回一句原因、什么都不写。
export function confirmTarget(slots, pickValue) {
  const open = (Array.isArray(slots) ? slots : []).filter((s) => s && !s.overrideHash);
  if (!open.length) return { reason: "这一组的槽位都已经确认过了；要改，先在槽位清单里撤销那一条。" };
  if (!pickValue) return { reason: "没选中槽位，这次什么都没写。" };
  const hit = open.find((s) => s.name === pickValue);
  if (!hit) {
    return { reason: `槽位下拉里的「${pickValue}」已经不在清单上了，这次什么都没写——重新选一条槽位再点确认。` };
  }
  return { slot: hit };
}

/// 这份榜默认对准哪条槽：**只认「槽位文件名与网格同名」这一种确定关系**。
/// 一只怪常有 2~3 份网格（衣服/手套/武器），每份榜各要标各的槽；旧写法一律默认
/// 「第一条未确认」，于是第二份榜的标常常落错槽，人要自己从十条里找那一条。
/// 匹不上就返回 null（前端照旧用第一条，但必须把「没有同名槽位」写在脸上，
/// 不许让"默认值"看起来像系统认出来的答案）。
export function autoSlotForMesh(mesh, openSlots) {
  const stem = String(mesh || "").replace(/\.mesh$/i, "").toLowerCase();
  if (!stem) return null;
  const hit = (Array.isArray(openSlots) ? openSlots : []).find((s) => {
    const n = String((s && s.name) || "");
    return n.replace(/\.(tga|dds|png|jpg|jpeg|bmp|webp)$/i, "").toLowerCase() === stem;
  });
  return hit ? hit.name : null;
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
  const auto = autoSlotForMesh(group.mesh, openSlots);
  const hint = auto
    ? `<span class="dim"> · 已对准与网格同名的槽</span>`
    : `<span class="dim"> · 没有与本网格同名的槽，这条得自己选</span>`;
  const pick = openSlots.length
    ? `<label class="dim">确认到槽位：<select class="tex-slot-pick"${gi === 0 ? ` id="texSlotPick"` : ""}>` +
      openSlots.map((s) => `<option value="${esc(s.name)}"${s.name === auto ? " selected" : ""}>${esc(s.name)}</option>`).join("") +
      `</select>${hint}</label>`
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
      ${scoreLine(c)}
      <details class="tex-why"><summary>凭什么排它</summary>${factorLine(c)}${spreadLine(c)}</details></figcaption>
      <div class="tex-btns">
        <button type="button" data-act="try" data-gi="${gi}" data-idx="${i}">套上看看</button>
        <button type="button" data-act="confirm" data-gi="${gi}" data-idx="${i}">确认这张</button>
      </div>
    </figure>`;
  });
  // 客户端自动对上的真文件单独一排放在候选榜前面：它不是「猜」，是引擎自己的转换路径。
  const stem = String(group.mesh || "").replace(/\.mesh$/i, "").toLowerCase();
  const autos = slots.filter((s) => s.autoHash && (
    String(s.name || "").replace(/\.[^.]+$/, "").toLowerCase() === stem || s.overrideHash
  ));
  const autoCards = autos.length
    ? `<div class="tex-auto"><p class="dim">客户端自动对上（convert/dxt 路径，不是候选榜猜的；确认后写覆盖表）</p><div class="tex-grid">` +
      autos.map((s) => {
        const same = s.overrideHash && String(s.overrideHash).toLowerCase() === String(s.autoHash).toLowerCase();
        const clash = s.overrideHash && !same;
        return `<figure class="tex-cand tex-auto-card">
        <span class="tex-ph" data-ph-for="${esc(s.autoHash)}">正在解客户端文件…</span>
        <img alt="客户端自动对上" data-need-png="1" data-hash="${esc(s.autoHash)}">
        <figcaption><b>自动对上</b> · ${esc(s.autoWidth ?? "?")}×${esc(s.autoHeight ?? "?")} ${esc(s.autoCodec || "")}<br>
        <span class="dim">${esc(s.autoPath || "")}</span>${
          clash ? `<br><b>⚠ 人工标注是另一张</b>` : ""
        }</figcaption>
        <div class="tex-btns">
          <button type="button" data-act="try-auto" data-gi="${gi}" data-hash="${esc(s.autoHash)}" data-slot="${esc(s.name)}">套上看看</button>
          ${same
            ? `<span class="dim">已确认这张</span>`
            : `<button type="button" data-act="confirm-auto" data-gi="${gi}" data-hash="${esc(s.autoHash)}" data-slot="${esc(s.name)}" data-cfg="${esc(s.cfgPath || "")}">确认这张</button>`}
        </div>
      </figure>`;
      }).join("") + `</div></div>`
    : "";
  // 候选图排在最前，UV 分布图排到图后：先让人看到「能换哪几张」，证据跟着走。
  return `<div class="tex-group" data-gi="${gi}">${head}${warn}${pick}${autoCards}` +
    `<div class="tex-grid">${cards.join("")}</div>` +
    `<div class="tex-uvmap-slot" data-uvmap-for="${esc(group.mesh)}"></div></div>`;
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

/// UV 岛分布图那一格：图 + 覆盖率。覆盖率≈1 时补一句「岛外没有像素可比」——
/// 这就是「这份榜没有对比依据」的实物，比只写一个数字 1.000 说得清楚。
export function uvMapHtml(map) {
  if (!map || !map.png) return "";
  const cov = Number(map.coverage);
  const pct = Number.isFinite(cov) ? Math.round(cov * 100) : null;
  const tail = pct === null ? "" : pct >= 99
    ? ` · 覆盖率 ${pct}%：整张都铺了 UV，岛外没有像素可比`
    : ` · 覆盖率 ${pct}%（暗处是岛外，评分的对比就来自这些格子）`;
  const faces = Number.isFinite(Number(map.faces)) ? ` · ${esc(map.faces)} 面` : "";
  return `<div class="tex-uvmap"><img src="${esc(map.png)}" alt="UV 岛分布图">` +
    `<span class="dim">这只网格的 UV 岛分布${esc(tail)}${faces}</span></div>`;
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
///
/// `textureNoUv` 是后端在批量缓存里**明确读到**的「无 UV」网格名。它跟「还没跑」
/// 必须分开说：前者等多久都不会有候选，后者才是进度问题。
export function texBlock(reply, warm = null) {
  const slots = (reply && reply.texSlots) || [];
  const groups = (reply && reply.textureCandidates) || [];
  const noUv = (reply && reply.textureNoUv) || [];
  if (!slots.length && !groups.length && !noUv.length) return null;
  const group = groups[0] || null;
  const confirmed = slots.filter((s) => s.overrideHash).length;
  // 排序依据这句话跟着后端口径走（group.ranked）：综合分怎么算、什么时候才重排，
  // 规则在 Rust 那边，前端照着它写的说，免得改了公式而这句话还在说「按 UV 排」。
  const basis = group && group.ranked ? "UV 贴合 × 尺寸 × 透明边界的综合分" : "UV 岛内外方差比";
  const many = groups.length > 1 ? `这一组有 ${groups.length} 只网格，各出一份榜（` : "按网格 " + esc(group?.mesh) + " 的离线试贴排序（";
  const noUvWho = noUv.length === 1 ? `网格 ${esc(noUv[0])} 读不出贴图坐标（UV）` : `${noUv.length} 只网格读不出贴图坐标（UV）`;
  const resolvedCount = slots.filter((s) => s.resolved).length;
  const autoCount = slots.filter((s) => s.autoHash).length;
  const facts = [];
  if (autoCount) facts.push(`${autoCount} 个客户端转换路径自动对上`);
  if (resolvedCount) facts.push(`${resolvedCount} 个已对上实体（可能是 UI 小图标）`);
  const slotCount = facts.length
    ? `引用了 ${slots.length} 张贴图（其中 ${facts.join("、")}）`
    : `引用了 ${slots.length} 张贴图，包里都没对上文件`;
  const note = group
    ? `${many}${basis}） · 从 ${group.pool} 张匿名贴图中选出 · 全部未确认${noUv.length ? ` · 另有 ${noUvWho}` : ""}`
    : noUv.length
      ? `${slots.length ? `${slotCount}；` : ""}${noUvWho}，离线试贴排不出候选${
          autoCount ? `；自动对上的 ${autoCount} 个槽仍可直接套用` : "——名字清单在，暂时没法自动套图"
        }`
      : `${slotCount}；${
          autoCount
            ? `自动对上的 ${autoCount} 个槽可直接套用，其余没有候选榜`
            : "离线试贴还没跑，下面只是名字清单，不是候选榜"
        }`;
  return {
    // 读不出 UV 的份不再挂「还没跑」进度话术——那会让人以为等等就好。
    slotsHtml: texSlotsHtml(slots, Boolean(group), noUv.length > 0) + (group || noUv.length ? "" : warmControl(warm)),
    // 有榜就摆一颗撤图按钮：自动试贴会把贴图盖在模型上，得有一眼可见的路退回灰模。
    candHtml: groups.length
      ? groups.map((g, i) => texCandidatesHtml(g, slots, i, groups.length)).join("") +
        `<p class="dim"><button type="button" data-act="clearTrial">退回灰模</button>` +
        ` 立体预览可能自动套着榜首候选作试贴——那是猜测，不是客户端认定的那张。</p>`
      : "",
    note,
    confirmed,
    total: slots.length,
  };
}
