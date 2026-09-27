// 详情页状态机（纯函数，不碰 DOM）。
//
// 为什么单独拎出来：这个页面出事的方式不是"算错"，而是**脏**——切换资产或加载
// 失败时，上一组的缺什么/图片/等级徽章还挂在屏上，于是新标题配旧内容，等于
// 凭空造出一条不存在的资产关系。靠人在渲染代码里"记得清空"迟早会漏，
// 所以规定：loading() 和 failed() 一律从 empty() 出发，任何字段都残留不了。

import { esc, num } from "../ui.js";
import { texPair } from "./wording.js";

/// 每类区块封顶多少行。那一辆 3,405 件的载具会把整页塞成几千行 DOM。
export const ROWCAP = 40;

/// 全空状态。字段清单就是"界面上有哪些地方会被写脏"的清单。
export function empty() {
  return {
    gid: 0,
    phase: "empty", // empty | loading | error | ready
    error: "",
    title: "",
    cn: "",
    grade: "",
    gradeWord: "",
    gradeNote: "",
    named: true,
    sum: "",
    mesh: { visible: false, meshes: [], active: -1, meta: "", tech: "", state: "" },
    previews: { visible: false, html: "", count: "" },
    tree: { html: "", count: "" },
    gaps: { items: [], count: "" },
    absences: { items: [], html: "" },
    canDo: { items: [], visible: false },
    tech: { html: "", rows: [] },
  };
}

export function loading(gid) {
  const s = empty();
  s.gid = gid;
  s.phase = "loading";
  s.title = "正在核对这条资产…";
  s.tree.html = `<p class="dim">正在读取组成…</p>`;
  return s;
}

export function failed(gid, err) {
  const s = empty();
  s.gid = gid;
  s.phase = "error";
  s.error = String(err || "");
  s.title = "读取失败";
  s.sum = s.error;
  s.tree.html = `<p class="dim">没读到组成。</p>`;
  return s;
}

/// 后端说"这条还没读到"（预热未完 / gid 不存在）——不是失败，措辞也不同。
export function notReady(gid) {
  const s = empty();
  s.gid = gid;
  s.phase = "loading";
  s.title = "这条记录还没读到";
  s.sum = "后台仍在读取客户端资源，稍等一次再点。";
  s.tree.html = `<p class="dim">没读到组成。</p>`;
  return s;
}

/// 判定一条后端报错是不是「还没读到」（不是失败）。后端的原话有两处，钉子必须
/// 逐字对得上，tests/detailState.test.js 里有源码断言盯着两边别走散：
///   card_detail（src-tauri/src/lib.rs）  ——「这条资产现在读不出来（预热还在跑…）」
///   asset_inspect（src-tauri/src/inspector.rs）——「…（它还在后台读取中，或编号不存在）」
/// 曾经的 bug：前端拿 msg.includes("还在读取") 当钉子，而这两句原话里都没有这四个
/// 连字——「还没读到」的措辞和自动重试因此从未生效过，预热中途点详情会看到红线
/// 「读取失败」，把没读到说成了失败。
export function isNotReadyMsg(msg) {
  const s = String(msg || "");
  return s.includes("预热还在跑") || s.includes("还在后台读取");
}

/// 编号只留在悬停提示里给排查的人看；既没名字又没路径的文件写「未命名文件」。
const HEX16 = /^[0-9a-f]{16}$/;
export function nameCell(name) {
  const n = String(name || "");
  if (!n || n === "<缺>") return `<code>没有读到名字</code>`;
  if (HEX16.test(n)) return `<code class="noname" title="编号 ${esc(n)}">未命名文件</code>`;
  return `<code title="${esc(n)}">${esc(n)}</code>`;
}

/// 一行「角色 + 名称 → 落点」。判定必须和后端一样看 `resolved`：
/// 定位到实体但清单里没有路径是合法状态，只按 path 判会显示「缺」，
/// 而「缺什么」里又没有它——两块自相矛盾。
///
/// 「缺」只留给真该有而没有的资源文件。两类引用标了也不算损失：
///   着色器        —— 程序里的名字，不是文件；
///   template_* 父材质 —— 引擎拼装用的模板，客户端本来就不带。
export function slotRow(name, role, dest, resolved) {
  const hit = Boolean(dest) || resolved === true;
  const at = dest ? esc(dest) : "已定位，但客户端没给路径";
  if (!hit) {
    const n = String(name || "");
    if (String(role).includes("着色器"))
      return `<li><span class="kd">${esc(role)}</span>${nameCell(n)} → <em class="na">程序里的着色器名，不是文件</em></li>`;
    if (String(role).includes("父材质") && /^template_/i.test(n))
      return `<li><span class="kd">${esc(role)}</span>${nameCell(n)} → <em class="na">模板材质，资源包里没有</em></li>`;
    return `<li class="miss"><span class="kd">${esc(role)}</span>${nameCell(n)}
      → <em class="miss">缺</em></li>`;
  }
  return `<li class="hit">
    <span class="kd">${esc(role)}</span>${nameCell(name)}
    → <span class="at">${at}</span>
  </li>`;
}

export function capNote(kind, total) {
  return total > ROWCAP ? `<li class="dim">另有 ${total - ROWCAP} 个${esc(kind)}未列出</li>` : "";
}

/// 组成树：模型定义解出来的（骨骼 / 部件 / 材质槽）+ 组内其余文件。
export function treeHtml(mdl, members) {
  const out = [];
  const inTree = new Set();
  if (mdl) {
    if (mdl.name) {
      out.push(`<li class="label">模型定义 ${esc(mdl.name)}</li>`);
      inTree.add(`${mdl.name}.mdl`); // .mdl 自己是树根，别在文件清单里重复一遍
    }
    if (mdl.skeletons && mdl.skeletons.length) {
      out.push(
        `<ul class="lines">${mdl.skeletons
          .slice(0, ROWCAP)
          .map((s) => slotRow(s.name, "骨骼", s.path, s.resolved))
          .join("")}${capNote("骨骼", mdl.skeletons.length)}</ul>`,
      );
      for (const s of mdl.skeletons) inTree.add(s.name);
    }
    if (mdl.bodies && mdl.bodies.length) {
      const rows = mdl.bodies
        .slice(0, ROWCAP)
        .map((b) => {
          const label = b.label ? `<li class="label">${esc(b.label)}</li>` : "";
          // 槽位是"这个材质自己用到的东西"——不写清的话，父材质那一行会和上面
          // 的材质同名同标签，看着像同一件事说了两遍。
          const slots = (b.textureSlots || []).length
            ? `<li class="label">这个材质用到的</li><ul class="lines sub">${b.textureSlots
                .slice(0, ROWCAP)
                .map((t) => slotRow(t.name, t.role, t.path, t.resolved))
                .join("")}${capNote("引用", b.textureSlots.length)}</ul>`
            : "";
          for (const x of [b.mesh, b.material]) if (x) inTree.add(x.name);
          return `${label}${slotRow(b.mesh.name, "网格", b.mesh.path, b.mesh.resolved)}${slotRow(
            b.material.name,
            "材质",
            b.material.path,
            b.material.resolved,
          )}${slots}`;
        })
        .join("");
      out.push(`<ul class="lines">${rows}${capNote("部件", mdl.bodies.length)}</ul>`);
    }
  }
  const rest = (members || []).filter((m) => !inTree.has(m.name));
  if (rest.length) {
    const byRole = new Map();
    for (const m of rest) {
      const role = m.roleZh || m.role;
      if (!byRole.has(role)) byRole.set(role, []);
      byRole.get(role).push(m);
    }
    out.push(
      [...byRole]
        .map(([role, items]) => {
          const shown = items.slice(0, ROWCAP);
          return `<h4>${esc(role)} <em>${items.length}</em></h4><ul class="lines">${shown
            .map((m) => slotRow(m.name, role, m.path, m.resolved))
            .join("")}${capNote(role, items.length)}</ul>`;
        })
        .join(""),
    );
  }
  return out.join("") || `<p class="dim">这组没有读到附属文件。</p>`;
}

/// 贴图预览：一张真图都没解出来时整块不出现。那些灰卡说的"为什么没图"
/// 和下面「缺什么」是同一句话，摆一排只会让人以为预览坏了。
/// hash 跟着 figure 走：lightbox 点开时按它找后端要大图（没有就放缩略图）。
export function previewsOf(pv) {
  const items = (pv && pv.items) || [];
  const real = items.filter((p) => p.ok);
  if (!real.length) return { visible: false, html: "", count: "" };
  const html = real
    .map(
      (p) =>
        `<figure class="pv" data-hash="${esc(p.hash || "")}"><img src="${esc(p.dataUrl)}" alt=""><figcaption>${esc(p.label)}</figcaption></figure>`,
    )
    .join("");
  const extra = items.length > real.length ? `（试过 ${items.length} 个来源）` : "";
  return { visible: true, html, count: `${real.length}${extra}` };
}

/// 技术信息：给排查的人看，缺值也要占一行说明"未读到"，不能留空行。
export function techRows(d, insp) {
  const t = (d && d.tech) || {};
  const miss = "未读到";
  return [
    ["编号", t.id || miss],
    ["所在数据容器", t.container || miss],
    ["容器内位置", t.offset ?? miss],
    ["展开后字节", t.bytes ?? miss],
    ["图形编码", t.codec || miss],
    ["所在目录", t.folder || (insp && insp.dir) || miss],
    ["完整路径", t.path || miss],
    ["名字从哪来", d.nameSource || miss],
    ["主体是否读回", d.hubDecoded ? "是" : "否"],
    ["判定依据", (t.rules || []).join(" · ") || "无"],
    ["本次核对耗时", insp && insp.elapsedMs != null ? `${insp.elapsedMs} 毫秒` : miss],
  ];
}

/// 「缺什么·为什么」每一行的状态。三类，绝不合并：
///   ok      —— 拿到了
///   missing —— 客户端就没给（不是工具的错）
///   unknown —— 客户端给了，但这个工具还没解出来（是工具的边界）
function abs(label, state, why) {
  return { label, state, why };
}

/// 从真实字段推出这一组资产"有什么、缺什么、为什么"。
/// 规矩：ready 状态下这个列表**永远非空**——不许留白，也不许编原因。
///
/// 三条来源各管各的事，不能互相代替：
///   members  —— 文件到底在不在客户端（role + resolved）
///   mdl      —— 有没有被 .mdl 串成可画的模型
///   missing  —— 材质/模型引用了但没路径的名字（"贴图 N 个"从这里数）
/// 只看 mdl 会把"有贴图但没路径"说成"没有贴图"，那是假原因，比留白更糟。
export function absencesOf(insp, card) {
  const c = insp.counts || {};
  const mdl = insp.mdl || null;
  const members = insp.members || [];
  const out = [];
  const ofRole = (role) => members.filter((m) => m.role === role);
  const resolvedOf = (role) => ofRole(role).filter((m) => m.resolved || m.path).length;
  // 「缺什么」里以「贴图 」开头的条目 = 材质/模型引用了但落不到文件的名字。
  // 2026-09-26 起 cfg 出过处的条目带「已找到原始出处」；后句白话化为
  // 「登记过它放在」后，识别串两个都认——旧回放数据不至于整批掉进错分支。
  const texLines = (insp.missing || []).filter((s) => s.startsWith("贴图 "));
  const danglingTex = texLines.length;
  const locatedTex = texLines.filter(
    (s) => s.includes("登记过它放在") || s.includes("已找到原始出处"),
  ).length;

  // 立体模型
  const bodies = mdl && mdl.bodies ? mdl.bodies : [];
  const drawable = bodies.filter((b) => b.mesh && b.mesh.hash).length;
  const meshHit = resolvedOf("mesh");
  if (drawable) out.push(abs("立体模型", "ok", `${drawable} 个网格能定位到，可以画`));
  else if (meshHit) out.push(abs("立体模型", "unknown", `有 ${meshHit} 个网格文件，但这组没有模型定义把它们串起来，暂时画不出`));
  else if (ofRole("mesh").length) out.push(abs("立体模型", "missing", `记了 ${ofRole("mesh").length} 个网格，但客户端未含这些文件`));
  else out.push(abs("立体模型", "missing", "这组里没有网格文件，画不出形状"));

  // 材质
  const mtlHit = resolvedOf("material");
  if (mtlHit) out.push(abs("材质", "ok", `${mtlHit} 个材质能读到，展开看它引用了什么`));
  else if (ofRole("material").length) out.push(abs("材质", "missing", `记了 ${ofRole("material").length} 个材质，但客户端未含这些文件`));
  else out.push(abs("材质", "missing", "这组里没有材质文件"));

  // 贴图：以真解出像素为准；没解出来要分清"没引用"还是"引用了但没路径"
  const pv = insp.previews;
  const realPv = pv && pv.items ? pv.items.filter((p) => p.ok).length : 0;
  const texHit = resolvedOf("texture");
  if (realPv) {
    const tail = danglingTex
      ? `；引用的贴图里还有 ${danglingTex} 张没对上文件（下面「缺什么」逐条说）`
      : "";
    out.push(abs("贴图", "ok", `解出了 ${realPv} 张能看的图${tail}`));
  } else if (danglingTex && locatedTex)
    out.push(abs(
      "贴图",
      "missing",
      `材质引用了 ${danglingTex} 张贴图：${locatedTex} 张在 ResourcePath.cfg 里登记过存放位置，但包里没有那文件；其余 ${danglingTex - locatedTex} 张连存放位置都没记（逐条见下面「缺什么」）`
    ));
  else if (danglingTex)
    out.push(abs("贴图", "missing", `材质引用了 ${danglingTex} 张贴图：客户端只存了名字，没存路径（逐条见下面「缺什么」）`));
  else if (texHit) out.push(abs("贴图", "unknown", `有 ${texHit} 张贴图文件，但没有材质引用它们，不知道用在哪`));
  else out.push(abs("贴图", "missing", "这组里没有贴图文件，也没被谁引用"));

  // 骨骼：文件在不在 + 权重能不能读，是两件事。骨骼文件可能只挂在模型定义上
  // （mdl.skeletons），成员清单没把它归成骨骼——只看清单，就会出现上面说「缺」、
  // 下面组成树里摆着同一个文件的自相矛盾。两边按名字并起来数。
  const skeNames = new Set(
    ofRole("skeleton")
      .filter((m) => m.resolved || m.path)
      .map((m) => m.name)
      .concat(
        ((mdl && mdl.skeletons) || [])
          .filter((s) => s.resolved || s.path)
          .map((s) => s.name),
      ),
  );
  if (skeNames.size)
    out.push(abs("骨骼", "unknown", `找到 ${skeNames.size} 个骨骼文件；但顶点权重还没解出来，现在只能看形状、不能摆姿势`));
  else if (ofRole("skeleton").length) out.push(abs("骨骼", "missing", `记了 ${ofRole("skeleton").length} 个骨骼，但客户端未含这些文件`));
  else out.push(abs("骨骼", "missing", "这组里没有骨骼文件（清单里也没给它记过骨骼）"));

  // 动画
  const animNames = (insp.anims || []).length;
  if (animNames) out.push(abs("动画", "unknown", `读到 ${animNames} 个动作名字；关键帧格式还没解出来，所以放不了`));
  else if (ofRole("animation").length) out.push(abs("动画", "missing", `记了 ${ofRole("animation").length} 个动作，但清单里读不出名字`));
  else out.push(abs("动画", "missing", "这组里没有动作文件"));

  return out;
}

/// 把 card_detail + asset_inspect 两个回包合成一个界面状态。
/// d = card_detail（卡片本体在 d.card 里），insp = asset_inspect。
export function loaded(gid, d, insp) {
  const s = empty();
  const card = d.card || {};
  s.gid = gid;
  s.phase = "ready";
  s.named = card.named !== false;
  s.title = s.named ? card.name || "" : "未命名资源";
  const cn = (insp.names || []).find((n) => /[一-鿿]/.test(n.name));
  s.cn = cn ? cn.name : ""; // cls（unique/shared）是数据层分类，不摆给人看
  s.grade = card.grade || "";
  s.gradeWord = card.gradeWord || "";
  s.gradeNote = card.gradeNote || "";

  // 分母只有贴图引用（骨架/网格/材质不在里面），标签必须写清；
  // 一组压根没提到贴图时不说这句，0/0 只会让人以为全断了。
  const tex = Number(card.refTotal) > 0 ? ` · ${texPair(card.locatedTotal, card.refTotal)}` : "";
  s.sum = `${insp.what} · ${num(insp.parts)} 个文件${tex}` + (insp.dir ? ` · ${insp.dir}` : "");

  s.tree = { html: treeHtml(insp.mdl, insp.members || []), count: `${num(insp.parts)} 个文件` };
  const gaps = [...new Set([...(insp.missing || []), ...(d.gaps || [])])];
  s.gaps = {
    items: gaps,
    count: gaps.length ? `${gaps.length} 处` : "0 处",
    html: gaps.length
      ? gaps.map((g) => `<li class="miss">${esc(g)}</li>`).join("")
      : `<li class="ok">没有发现明显缺失</li>`,
  };
  const absences = absencesOf(insp, card);
  s.absences = {
    items: absences,
    html: absences
      .map(
        (a) => `<li class="a-${a.state}"><span class="kd">${esc(a.label)}</span><em>${
          a.state === "ok" ? "有" : a.state === "missing" ? "缺" : "还没解出"
        }</em><span>${esc(a.why)}</span></li>`,
      )
      .join(""),
  };
  const can = insp.canDo || [];
  s.canDo = {
    items: can,
    visible: can.length > 0,
    html: can.map((c) => `<i class="${/没对上|未解/.test(c) ? "todo" : ""}">${esc(c)}</i>`).join(""),
  };
  const rows = techRows(d, insp);
  s.tech = {
    rows,
    html: rows.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join(""),
  };
  s.previews = previewsOf(insp.previews);

  // 立体预览：只有定位到实体的网格才许诺；多网格时默认画第一个。
  const meshes = (insp.mdl && insp.mdl.bodies ? insp.mdl.bodies : [])
    .filter((b) => b.mesh && b.mesh.hash)
    .map((b) => ({ name: b.mesh.path || b.mesh.name, hash: b.mesh.hash, label: b.mesh.name }));
  // 面板常驻：画不出时最忌讳整块隐藏——用户看到的是"工具坏了"。原因不在这儿另编
  // 一套，直接复用 absencesOf 里那条「立体模型」，两边说的必须是同一处判断。
  const meshRow = absences.find((a) => a.label === "立体模型") || null;
  s.mesh = {
    visible: true,
    hasView: meshes.length > 0,
    meshes,
    active: meshes.length ? 0 : -1,
    why: meshRow ? meshRow.why : "",
    meta: "",
    tech: "",
    state: "",
  };
  return s;
}
