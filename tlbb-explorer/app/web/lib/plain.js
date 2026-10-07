/// 人话导语——每个详情标签的第一句话。
///
/// 用户 2026-10-05 的原话：「描述的东西密密麻麻的 我又看不懂」。诊断：界面把
/// 研究笔记当成了文案，术语（绑定位移/影响顶点表/驻留字符串/参数块）一句话
/// 里连击，数字没有主语也没有用途。这一层的职责就一件事：第一句话回答
/// 「这是什么、我能看到什么、还差什么」，术语和研究注记让位给折叠区。
///
/// 纪律与全库一致：只说回包里真有的数字，一个不许编；这里全是纯函数
/// （回包进，一句话出），node --test 盯着措辞——导语里出现术语就算失败。

export function skeletonLead(v) {
  const nodes = v.nodes || [];
  const anims = v.animations || [];
  const declared = v.declared ?? nodes.length;
  const withPos = nodes.filter((n) => n.pos).length;
  let s = `这具骨架有 ${declared} 根骨头，相当于这只模型全身的关节。`;
  if (withPos === 0) s += "每根骨头的位置还没读出来。";
  else if (withPos < declared)
    s += `${withPos} 根的位置已经读出来，另外 ${declared - withPos} 根只登记了名字。`;
  else s += "每根骨头的位置都读出来了。";
  if (v.skin_bones) s += `其中 ${v.skin_bones} 根记着哪些皮肤顶点跟着它动。`;
  if (anims.length) s += `它登记了 ${anims.length} 条动作，到「动作」页可以逐帧看。`;
  if (v.chain === true) s += "骨头谁挨着谁也读出来了。";
  return s;
}

export function animationLead(rep) {
  if (!rep || !rep.tracks || !rep.tracks.length) return "这条动作没读到关键帧数据。";
  const bones = rep.bones ?? rep.tracks.length;
  return (
    `这条动作有 ${rep.frames} 帧、${bones} 根骨头参加。拖动滑杆可以一帧一帧看每根骨头摆在哪，` +
    `画布把顶点按这条动作摆出来；静止形状仍是网格的绑定姿态。`
  );
}

export function effectLead(rep) {
  if (!rep) return "";
  const head = rep.name ? `这份特效叫「${rep.name}」` : "这份特效脚本";
  return (
    `${head}，登记了自己要用的贴图、材质和零件，名字清单在下面。` +
    "每个粒子怎么飞的参数还没破译完，破译完特效就能真正播出来。"
  );
}

export function materialLead(rep) {
  if (!rep) return "";
  if (rep.kind === "模型定义") {
    const n = (rep.skeletons || []).length + (rep.bodies || []).length;
    return `这是模型的说明书：写清它用哪副骨架、哪些网格配哪些材质，一共 ${n} 条。`;
  }
  const slots = (rep.slots || []).length;
  const miss = rep.unresolved || 0;
  let s = "这是材质清单：模型表面每个部位贴哪张图、用什么方式渲染。";
  if (slots) {
    s += `一共 ${slots} 条，${slots - miss} 条对上了实际文件`;
    s += miss ? `，${miss} 条是客户端本来就没带的。` : "。";
  }
  return s;
}
