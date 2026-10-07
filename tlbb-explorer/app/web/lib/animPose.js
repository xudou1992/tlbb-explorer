// 动作页 3D 预览的纯逻辑：能不能发、发哪一帧、注记刷不刷、播放怎么走步。
//
// DOM 与 WebGL 是薄壳（detail.js / mesh-viewer.js 只管摆），判断都收在这里，
// 因为这一层有 node --test 盯着。容错风格与 lib/boneLines.js 一致：
// 脏数据丢掉、不抛、不编——「这一帧没摆出来」由界面层照实说，不假装成功。

import { clampFrame } from "./animView.js";
export { clampFrame };

/// 播放的步进节奏。帧率刻度（.ani 的 tick）的含义未证，这个数只是预览用的
/// 参考速度——它不是游戏帧率，任何文案都不许把它写成「25fps 是真值」。
export const PLAY_STEP_MS = 40; // 1000 / 25

/// 播放的下一步：到尾回卷（预览要一直能转下去，停在最后一帧等于让人每次
/// 都得手动再点一次播放）。frames 非法时原地不动。
export function nextFrame(frame, frames) {
  if (!(frames > 0)) return 0;
  return (clampFrame(frame, frames) + 1) % frames;
}

/// 在途闸门：同一时刻最多一个 pose 请求在外面。游标连动（或播放步进）时
/// 只记住**最新**想看的帧号，回包落地再补发——不是排队：排队的中间帧
/// 摆出来也已经过时了，积压只会让画面越追越旧。
///
/// 用法（与 lib/seq.js 同一家法）：
///   发请求前 `const f = gate.request(frame)`，拿到 null 就说明已有在途，
///   这一帧被记下了；回包落地（成功失败都算）后 `gate.settled()`，
///   返回攒着的最新帧（没有则 null），调用方决定要不要补发。
///   切资产 / 切动作 / 换网格必须 `reset()`：在途与攒帧都作废，
///   迟到的回包由 seq 那边判废，两边各管各的。
export function makePoseGate() {
  let inFlight = false;
  let pending = null;
  return {
    request(frame) {
      if (inFlight) {
        pending = frame;
        return null;
      }
      inFlight = true;
      return frame;
    },
    settled() {
      const f = pending;
      pending = null;
      inFlight = false;
      return f;
    },
    reset() {
      inFlight = false;
      pending = null;
    },
  };
}

/// 回包 notes 取第一条当画布下的注记（后端给的三条里锚定口径排最前）。
/// 与屏幕上已有的那句一样就回 null——拖游标时一帧一个回包，注记其实
/// 没变，一遍一遍重写等于刷屏。没有可用的话就保留屏幕上已有的。
/// @returns {string|null} 要写上屏的那句；null = 屏幕上的不用动。
export function poseNote(notes, shown) {
  const first = (Array.isArray(notes) ? notes : []).find(
    (n) => typeof n === "string" && n.length,
  );
  if (!first) return null;
  return first === shown ? null : first;
}
