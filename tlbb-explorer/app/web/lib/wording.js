// 所有"带口径的数字文案"集中在这里。
//
// 这个项目被数字坑过两次：卡片上的「引用对上 0/2」分母其实只数贴图引用，
// 而库状态里的 62% 数的是全部引用；同一句「对上文件」摆两个口径，
// 用户只会觉得整页不可信。所以措辞和分母绑死在这里，一处定义。

import { num } from "../ui.js";

/// 25/30,585 取整是 0%，看着像"一条都没对上"，其实对上了 25 条。
export function pctText(pct, resolved) {
  const p = Number(pct) || 0;
  if (p === 0 && Number(resolved) > 0) return "不足 1%";
  return `${p}%`;
}

/// 贴图引用：分母只有贴图，必须写"贴图"两个字；「对上」说的是对到了文件。
export const texPair = (located, total) => `贴图引用 ${num(located)}/${num(total)} 对上了文件`;

/// 列表条数。没读完时必须让人知道这是中途值。
export function listCount(total, shown, ready) {
  const more = Number(total) > Number(shown) ? `（先列 ${num(shown)} 条）` : "";
  return `${num(total)} 条${more}` + (ready ? "" : " · 还在读取");
}

/// 顶栏进度一行字（文字 + 悬停说明 + 条宽比例）。懒预热之后这是两套口径：
///   assets —— 「正在读取」就是当前页面的读取进度，数字带分母就够；
///   browse —— 必须说清「这只影响资产标签」，不然 35% 摆在那儿，用户会以为
///             开个 data 也要等读完。第一屏不付预热成本，这句话就是凭据。
/// 比例在这里算死（分母 0 时是 0% 不是 NaN），条宽和文字永不打架。
export function progressLine(view, ready, scanned, total) {
  const pct = total ? Math.round((scanned / total) * 100) : 0;
  if (view === "assets") {
    if (ready) return { pct, text: `已读完 ${num(total)} 组`, tip: "" };
    // 分母还没读到（刚触发预热的第一瞬）就不摆「0/0」：那既不是进度也不是
    // 失败，只是还没有话可说。
    if (!total) return { pct: 0, text: "正在读取…", tip: "" };
    return {
      pct,
      text: `正在读取 ${pct}% · ${num(scanned)}/${num(total)}`,
      tip: "",
    };
  }
  if (ready) return { pct, text: `资产库已读完 · ${num(total)} 组`, tip: "" };
  // 分母还没出来时别挂「后台读取 0%」——把「还没读到数字」说成「正在读 0%」，
  // 和把「没读到」说成「失败」是同一种谎。
  if (!total)
    return {
      pct: 0,
      text: "资产库后台读取准备中…",
      tip: "这只影响「资产」标签；浏览、预览、导出现在就能用。",
    };
  return {
    pct,
    text: `资产库后台读取 ${pct}% · ${num(scanned)}/${num(total)}`,
    tip: "这只影响「资产」标签；浏览、预览、导出现在就能用。",
  };
}

/// 左栏底部的一行总数。分母写在文案里，不靠用户猜。
/// 曾经这里列过三行明细（含「贴图引用对上 N/M」）；那三行的分母口径不一，
/// 摆在一起只会让人以为整页不可信——口径该在证据页说清，不在筛选栏里堆数字。
export function railCount(s) {
  return {
    total: num(s.totalGroups),
    withImage: num(s.imageCandidates),
  };
}

/// 详情大标题的断行处理。
///
/// 资产名是 `w1351_nan_s_shukuanganxiang_001` 这种长无空格串，浏览器找不到
/// 断点就只能硬折，读者看到的是「…shukuanganxiang_」+「001」两截。下划线是
/// 名字里天然的分节符，在它后面插零宽断点（<wbr>），让换行优先发生在分节处。
/// 只在真的长（>24 字符）时才插：短名字本来就不会折，插了反而多此一举。
export function titleHtml(name) {
  const s = String(name == null ? "" : name);
  const safe = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  if (safe.length <= 24) return safe;
  return safe.replace(/_/g, "_<wbr>");
}

/// 一行「N 个文件提到它」。数的是去重后的文件路径，不是引用边数。
export const citedVerdict = (files) => (files ? `${num(files)} 个文件提到了它` : "没有文件提到它");

/// 反查的边界说明：这是「提到」，不是「共用同一份资源」。
export const CITED_NOTE =
  "每一行都是一份客户端文件的原文里写着这个名字。这只是「提到」，不代表它们共用了同一份资源。";

/// 列表里每行的红色「缺」曾经铺满整屏，等于没有信息量——只在详情里强调。
export const rowMissChip = (miss) => (miss > 0 ? `贴图缺 ${miss}` : "");

/// 一张图一条都摆不出来时的那句话。分三种情况，一种都不能含糊：
/// 格子文件根本没交记录、交了记录但摆的本来不是网格、记录指的是网格却取不出文件——
/// 这三件事在客户端里是完全不同的结论，混成一句「没对上模型文件」就是替客户端说谎。
export function mapNoObjects(s) {
  if (!s.records) {
    if (!s.unreadableGrids)
      return `读到了，这张图 ${num(s.grids)} 个格子一个都没摆东西。能转、能缩放，就是看不到物件。`;
    const empt = s.emptyGrids ? `、${num(s.emptyGrids)} 个本来就是空格子` : "";
    return (
      `这 ${num(s.grids)} 个文件里 ${num(s.unreadableGrids)} 个不是物件清单那类东西${empt}` +
      `（逐条原因在下面），一条摆位记录都没交出来——所以这里没有物件可摆。`
    );
  }
  const other = (s.otherExt || [])
    .filter((x) => x.ext)
    .map((x) => `.${x.ext} ${num(x.records)} 条`)
    .join("、");
  const parts = [];
  const miss = s.missingMeshes + s.unreadableMeshes;
  if (miss) parts.push(`${num(miss)} 条记的是网格，可客户端里取不出这个文件`);
  if (s.notMesh)
    parts.push(`${num(s.notMesh)} 条摆的本来就不是网格${other ? `（${other}，文件是存在的）` : ""}`);
  if (s.oddNames) parts.push(`${num(s.oddNames)} 条名字既不像文件名也不像路径，没猜它是什么`);
  if (s.emptyNamed) parts.push(`${num(s.emptyNamed)} 条名字是空的`);
  const why = parts.length ? `：${parts.join("；")}` : "";
  // 「没对上」这个词只留给真缺：客户端里取不出文件才叫没对上，
  // 摆的本来就不是特效/别的类型不叫没对上。
  const lead = miss
    ? `读到了 ${num(s.records)} 条记录，可是一条都没对上能摆出来的模型`
    : `读到了 ${num(s.records)} 条记录，可这一版画得出的是 0 条`;
  return `${lead}${why}。`;
}

/// 列表被筛空时该说什么。把**正开着的筛选条件点名**是这里的全部目的：
/// 这些条件存在 localStorage 里、重启也还在，人回来接着搜就会以为「搜不到」，
/// 而真相是「类型：场景物件」还开着。只说「没有命中」是把锅推给关键词。
export function emptyMessage({ query, state, ready }) {
  const 开着 = [];
  if (state.kind && state.kind !== "全部") 开着.push(`类型：${state.kind}`);
  if (state.scenario && state.scenario !== "全部") 开着.push(`用途：${state.scenario}`);
  if (state.grade && state.grade !== "全部") 开着.push(`完整程度：${state.grade}`);
  if (state.onlyImage) 开着.push("只看有缺失的资源");
  if (state.named === false) 开着.push("只看未命名资产");
  if (!ready) {
    return {
      strong: "后台还在准备资产清单",
      span: "已就绪的会陆续出现，顶栏有进度——这时候搜不到不代表没有。",
    };
  }
  if (query && 开着.length) {
    return {
      strong: `没有命中「${query}」`,
      span: `同时还开着 ${开着.join("、")} —— 这些条件存在本地，重启也还在。点「清空筛选」一次清掉。`,
    };
  }
  if (开着.length) {
    return {
      strong: "这些筛选条件把列表筛空了",
      span: `开着 ${开着.join("、")}。点「清空筛选」一次清掉。`,
    };
  }
  if (query) {
    return { strong: `没有命中「${query}」`, span: "换个关键词，或点上方「清空筛选」清掉全部条件。" };
  }
  return {
    strong: "没有符合条件的资产",
    span: "默认不列没名字的资产；左下有「看未命名资产」。",
  };
}
