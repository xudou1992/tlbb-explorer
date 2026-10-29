// 逐段核 MIN3：不猜布局，直接找「标志区长什么样」，再算当前模型的字节账差多少。
// 差值（delta）才是线索：0=对上了；正的=还有东西没算；负的=模型超了。
import { readFileSync } from "node:fs";

const u32 = (b, o) => (o + 4 <= b.length ? b.readUInt32LE(o) : undefined);

function flagsLike(raw, at, n) {
  // 和 min3_flags_at 一致：只看头 8 条（后面的骨可能整条不动、标志为 0）
  const probe = Math.min(n, 8);
  let ok = 0;
  for (let i = 0; i < probe; i++) {
    const f = u32(raw, at + i * 4);
    if (f === undefined) return null;
    if ((f & 1) !== 0 && f < 0x10000) ok++;
  }
  return ok * 5 >= probe * 4 ? ok : null;
}

// 当前 MIN3 模型的字节账（与 min3_walk 一致），sparse=允许计数前缀
function spend(raw, flagsAt, n, frames, sparse) {
  let cur = flagsAt + n * 4;
  const per = [];
  for (let i = 0; i < n; i++) {
    const f = u32(raw, flagsAt + i * 4);
    const rotB = (f & 0x800) !== 0 ? 6 : 16;
    const before = cur;
    if (f & 1) cur += ((f & 0x10) !== 0 && sparse) ? 4 + (u32(raw, cur) || 0) * rotB : frames * rotB;
    if (f & 2)
      cur +=
        ((f & 0x20) !== 0 && sparse)
          ? 4 + (u32(raw, cur) || 0) * (12 + ((f & 0x80) !== 0 ? 2 : 4))
          : frames * 12;
    if (f & 4)
      cur +=
        ((f & 0x40) !== 0 && sparse)
          ? 4 + (u32(raw, cur) || 0) * (4 + ((f & 0x80) !== 0 ? 1 : 2))
          : frames * 4;
    per.push(cur - before);
  }
  return { end: cur, per };
}

for (const file of process.argv.slice(2)) {
  const raw = readFileSync(file);
  const bones = raw.readUInt16LE(0xba);
  const bones2 = raw.readUInt16LE(0xbe);
  const frames = raw.readUInt16LE(0xc2);
  const tick = raw.readFloatLE(0xc6);
  const tag = raw.subarray(0x8c, 0x90).toString("latin1");
  console.log(
    `\n=== ${file.split("/").pop()} tag=${tag} size=${raw.length} 骨=${bones}/${bones2} 帧=${frames} 帧率=${tick.toFixed(0)}`
  );
  // 名表长什么样（0xEE 起 30B）
  const nameAt = 0xee;
  let printable = 0;
  for (let i = 0; i < Math.min(bones, 8); i++) {
    const s = raw.subarray(nameAt + i * 30, nameAt + i * 30 + 30);
    const end = s.indexOf(0);
    const txt = s.subarray(0, end < 0 ? 30 : end).toString("latin1");
    if (/^[\x20-\x7e]+$/.test(txt) && txt.length > 0) printable++;
    if (i < 3) console.log(`   名[${i}] = ${JSON.stringify(txt)}`);
  }
  console.log(`   前 8 条名可读：${printable}/8`);
  // 全体 4 字节对齐候选标志区
  const cands = [];
  for (let n of [bones, bones2]) {
    if (n === 0) continue;
    for (let at = 0xee; at + n * 4 <= raw.length; at += 2) {
      if (flagsLike(raw, at, n) === null) continue;
      const dense = spend(raw, at, n, frames, false);
      const sparse = spend(raw, at, n, frames, true);
      cands.push({
        n,
        at,
        denseDelta: raw.length - dense.end,
        sparseDelta: raw.length - sparse.end,
        sample: [0, 1, 2].map((i) => "0x" + (u32(raw, at + i * 4) || 0).toString(16)),
      });
    }
  }
  const zero = cands.filter((c) => c.denseDelta === 0 || c.sparseDelta === 0);
  console.log(`   合格标志区候选：${cands.length} 个，其中字节账对平：${zero.length} 个`);
  zero.forEach((c) =>
    console.log(
      `     ★ 对平：flags@${c.at}（名表@0xEE 算起的块 = ${c.at - (0xee + bones * 30 + bones * 44)}）标志数=${c.n} 标志 ${c.sample.join(" ")}`
    )
  );
  // 按 |delta| 最小的几个（dense 口径）
  cands
    .filter((c) => c.n === bones)
    .sort((a, b) => Math.abs(a.denseDelta) - Math.abs(b.denseDelta))
    .slice(0, 6)
    .forEach((c) =>
      console.log(
        `     flags@${c.at}（名表后 ${c.at - 0xee - bones * 30} 字节）密存差 ${c.denseDelta} · 稀疏差 ${c.sparseDelta} · 标志 ${c.sample.join(" ")}`
      )
    );
  if (cands.length) {
    const best = cands
      .filter((c) => c.n === bones)
      .sort((a, b) => Math.abs(a.denseDelta) - Math.abs(b.denseDelta))[0];
    if (best) {
      const { per } = spend(raw, best.at, bones, frames, false);
      const hist = {};
      per.forEach((p) => (hist[p] = (hist[p] || 0) + 1));
      console.log(
        `     最平候选 ${best.at} 的逐骨字节分布：` +
          Object.entries(hist)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 8)
            .map(([k, v]) => `${k}B×${v}`)
            .join("  ")
      );
      console.log(
        `     每帧推算：` +
          Object.entries(hist)
            .map(([k, v]) => `(${k}/帧数=${frames}=${(k / frames).toFixed(2)})×${v}`)
            .slice(0, 8)
            .join("  ")
      );
    }
  }
}
