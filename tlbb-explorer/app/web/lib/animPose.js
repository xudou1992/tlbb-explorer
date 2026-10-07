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

// ---------------------------------------------------------------------------
// 整组部件一起摆（多件套网格）：勾选 → 请求参数 → 回包对号 → 逐件降级。
// 与单件那组函数同一容错风格：脏数据丢掉、不抛、不编。
// ---------------------------------------------------------------------------

/// 尾名：部件名单与回包里的 mesh 可能一个是文件名一个是完整路径，
/// 统一按 `/` 切尾对号（与后端 mesh 参数的匹配规则同一条）。
export function meshTail(path) {
  return typeof path === "string" ? path.split("/").pop() || "" : "";
}

/// 勾选 → 请求参数：开着的部件按清单原顺序带回，一件没开就是空表
/// （调用方据此清画布、不发请求——关掉的不画不请求）。
export function checkedPartList(names, isEnabled) {
  if (!Array.isArray(names)) return [];
  return names.filter((n) => typeof n === "string" && n && isEnabled(n));
}

/// 逐件取几何的结果聚合（Promise.allSettled 的产出）。成功的按请求顺序留下，
/// 失败的点出件名聚成一句人话——错误行要「点名哪件」，不能只说「失败了」。
/// @returns {{ ok: Array<{name, data}>, failed: string[], message: string|null }}
export function partLoadSummary(names, results) {
  const ok = [];
  const failed = [];
  const list = Array.isArray(results) ? results : [];
  (Array.isArray(names) ? names : []).forEach((name, i) => {
    const r = list[i];
    if (r && r.status === "fulfilled" && r.value) ok.push({ name, data: r.value });
    else failed.push(name);
  });
  const message = failed.length
    ? `这几件没取到几何，先摆其余的：${failed.join("、")}`
    : null;
  return { ok, failed, message };
}

/// 回包的 parts 按件名对号到已加载部件的下标（`parts[i].mesh` 对号，不按位置
/// 硬配——后端回了本地没勾的件、或名单顺序变过，都对不上号，丢掉不硬画）。
/// @returns {Array<{index: number, name: string, positions: Array}>}
export function matchPartPoses(parts, loadedNames) {
  const out = [];
  if (!Array.isArray(parts) || !Array.isArray(loadedNames)) return out;
  for (const p of parts) {
    if (!p || !Array.isArray(p.positions)) continue;
    const i = loadedNames.indexOf(meshTail(p.mesh));
    if (i < 0) continue;
    out.push({ index: i, name: loadedNames[i], positions: p.positions });
  }
  return out;
}

/// 整组路径的注记行：后端把「这件不变形」这类部件实况追加在固定三条后面，
/// 一段话全带上才叫如实。去重口径与 poseNote 同一家法（与屏幕上已有的整段
/// 一样就回 null，不刷屏）。
/// @returns {string|null} 要写上屏的整段；null = 屏幕上的不用动。
export function poseNotesLine(notes, shown) {
  const all = (Array.isArray(notes) ? notes : []).filter(
    (n) => typeof n === "string" && n.length,
  );
  if (!all.length) return null;
  const line = all.join("；");
  return line === shown ? null : line;
}

/// fresh 守卫用的名单比较：发出请求时的部件名单与现在的逐位相等才算新鲜
/// （勾选刚变过 = 旧回包的顶点对不上现在的缓冲，丢）。
export function sameNameList(a, b) {
  return Array.isArray(a) && Array.isArray(b) && a.length === b.length &&
    a.every((n, i) => n === b[i]);
}
