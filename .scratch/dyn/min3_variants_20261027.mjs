// 对「结构不成立」的 MIN3 逐变量扫描：名表基址 / 名步长 / 静态区步长 / 定长块上限。
// 判据沿用 min3_flags_at：逐骨消耗必须**正好**落在文件尾。打印每个文件命中的组合。
import { readFileSync } from "node:fs";

const u32 = (b, o) => (o + 4 <= b.length ? b.readUInt32LE(o) : undefined);
const u16 = (b, o) => (o + 2 <= b.length ? b.readUInt16LE(o) : undefined);

// 与 min3_walk 同构；返回结束偏移，越界/计数不合法回 null。
function walk(raw, flagsAt, flagsN, frames, useCountPrefix) {
  let cur = flagsAt + flagsN * 4;
  if (cur > raw.length) return null;
  for (let i = 0; i < flagsN; i++) {
    const f = u32(raw, flagsAt + i * 4);
    if (f === undefined) return null;
    const rotB = (f & 0x800) !== 0 ? 6 : 16;
    if (f & 1) {
      if ((f & 0x10) !== 0 && useCountPrefix) {
        const n = u32(raw, cur);
        if (n === undefined || n > frames) return null;
        cur += 4 + n * rotB;
      } else {
        cur += frames * rotB;
      }
    }
    if (f & 2) {
      if ((f & 0x20) !== 0 && useCountPrefix) {
        const n = u32(raw, cur);
        if (n === undefined || n > frames) return null;
        cur += 4 + n * 12 + ((f & 0x80) !== 0 ? n * 2 : n * 4);
      } else {
        cur += frames * 12;
      }
    }
    if (f & 4) {
      if ((f & 0x40) !== 0 && useCountPrefix) {
        const n = u32(raw, cur);
        if (n === undefined || n > frames) return null;
        cur += 4 + n * 4 + ((f & 0x80) !== 0 ? n : n * 2);
      } else {
        cur += frames * 4;
      }
    }
    if (cur > raw.length) return null;
  }
  return cur;
}

function scan(file) {
  const raw = readFileSync(file);
  const bones = u16(raw, 0xba);
  const bones2 = u16(raw, 0xbe);
  const frames = u16(raw, 0xc2);
  const hits = [];
  const nameBases = [0xea, 0xee, 0xf0, 0xf2, 0xf6];
  const nameStrides = [28, 30, 32, 64];
  const staticStrides = [0, 44, 48, 56, 60, 64];
  const flagCounts = [...new Set([bones, bones2])];
  for (const nb of nameBases)
    for (const ns of nameStrides)
      for (const ss of staticStrides)
        for (const fn of flagCounts)
          for (const cp of [true, false]) {
            const base = nb + bones * ns + bones * ss;
            if (base > raw.length) continue;
            const max = Math.min(8192, raw.length - base - fn * 4);
            let n = 0;
            let last = -1;
            for (let off = 0; off <= max; off += 4) {
              const end = walk(raw, base + off, fn, frames, cp);
              if (end === raw.length) {
                n++;
                last = base + off;
              }
            }
            if (n === 1) hits.push({ nb, ns, ss, fn, cp, at: last, exact: true });
            else if (n > 1) hits.push({ nb, ns, ss, fn, cp, count: n, exact: false });
          }
  return { bones, bones2, frames, size: raw.length, hits };
}

for (const f of process.argv.slice(2)) {
  const r = scan(f);
  const uniq = r.hits.filter((h) => h.exact);
  console.log(
    `\n${f.split("/").pop()}  size=${r.size}  bones=${r.bones} bones2=${r.bones2} frames=${r.frames}` +
      `  ⇒ 唯一精确解 ${uniq.length} 组 / 多解 ${r.hits.length - uniq.length} 组`
  );
  for (const h of uniq.slice(0, 8))
    console.log(
      `   名表@0x${h.nb.toString(16)} 名步长=${h.ns} 静态步长=${h.ss} 标志数=${h.fn} 计数前缀=${h.cp ? "有" : "无"} → flags@${h.at}`
    );
}
