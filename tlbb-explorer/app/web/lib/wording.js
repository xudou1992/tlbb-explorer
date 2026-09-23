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
