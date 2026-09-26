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

/// 贴图引用：分母只有贴图，必须写"贴图"两个字。
export const texPair = (located, total) => `贴图名对上 ${num(located)}/${num(total)}`;

/// 列表条数。没读完时必须让人知道这是中途值。
export function listCount(total, shown, ready) {
  const more = Number(total) > Number(shown) ? `（先列 ${num(shown)} 条）` : "";
  return `${num(total)} 条${more}` + (ready ? "" : " · 还在读取");
}

/// 左栏库状态三行。每行的分母都写在标签里，不靠用户猜。
export function railStats(s) {
  return [
    ["资产组", num(s.totalGroups)],
    ["贴图名能对上文件的组", num(s.imageCandidates)],
    ["贴图引用对上", `${num(s.locatedRefs)} / ${num(s.totalRefs)}`],
  ];
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
