// 只读勘察：把一个真实地图目录下的全部 .scene 摆位记录画成俯视散布图。
// 不吃 db、不吃 pak，直接读解包树里的明文文件；不改任何游戏文件。
import fs from 'node:fs';
import path from 'node:path';

const TREE = 'D:/TLGL/.scratch/out/tree';
const MAP = process.argv[2] || 'w1351_ll_dl_002';
const OUT = process.argv[3] || 'D:/TLGL/.scratch/scene_preview.svg';

const mapDir = path.join(TREE, 'mobile_maps', MAP);
const srcDir = path.join(TREE, 'mobile_maps_source');

// 几何池：一次性列出。格子里的名字带 `.mesh` 后缀，池按整名建。
const pool = new Set(fs.readdirSync(srcDir).filter((f) => f.endsWith('.mesh')).map((f) => f.toLowerCase()));
const hasMesh = (s) => pool.has(s.toLowerCase());

const floor = (v, g) => Math.floor(v / g);
const trunc = (v, g) => Math.trunc(v / g);

const inst = [];
const grids = [];
let emptyGrids = 0, decodeErr = 0, badMatrix = 0;

for (const f of fs.readdirSync(mapDir).filter((f) => f.endsWith('.scene')).sort()) {
  const stem = f.slice(0, -6).split('_');
  const gb = Number(stem[1]), gc = Number(stem[2]);
  const b = fs.readFileSync(path.join(mapDir, f));
  if (b.length < 12) { emptyGrids++; continue; }
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const declared = dv.getUint32(0, true);
  const tag = dv.getUint32(4, true);
  const stride = tag + 8;
  if (!(tag > 100 && tag < 5000) || 12 + stride > b.length + stride) { decodeErr++; continue; }
  let got = 0;
  for (let i = 0; Math.abs(i) < declared + 4; i++) {
    const off = 12 + i * stride;
    if (off + 64 > b.length) break;
    const m = [];
    for (let k = 0; k < 16; k++) m.push(dv.getFloat32(off + 4 * k, true));
    const okHom = m[3] === 0 && m[7] === 0 && m[11] === 0 && m[15] === 1;
    const okFin = m.slice(0, 14).every(Number.isFinite);
    if (!okHom || !okFin) { badMatrix++; break; }
    let ne = off + stride;
    if (ne > b.length) ne = b.length;
    let s = b.subarray(off + 64, ne).toString('latin1');
    const z = s.indexOf('\0');
    if (z >= 0) s = s.slice(0, z);
    s = s.replace(/[^\x20-\x7e]/g, '');
    inst.push({ x: m[12], y: m[13], z: m[14], name: s, gb, gc, tag });
    got++;
  }
  grids.push({ gb, gc, n: got, declared });
}

// —— 格子号判据：floor 还是 trunc ——
let floorHit = 0, truncHit = 0, neg = 0, negFloor = 0, negTrunc = 0;
for (const it of inst) {
  const f = floor(it.x, 32) === it.gb && floor(it.z, 32) === it.gc;
  const t = trunc(it.x, 32) === it.gb && trunc(it.z, 32) === it.gc;
  if (f) floorHit++;
  if (t) truncHit++;
  if (it.x < 0 || it.z < 0) { neg++; if (f) negFloor++; if (t) negTrunc++; }
}

// —— join 几何池 ——
let joined = 0, emptyName = 0;
const uniqMiss = new Set();
for (const it of inst) {
  if (!it.name) { emptyName++; continue; }
  if (hasMesh(it.name)) joined++;
  else uniqMiss.add(it.name);
}

// —— 出图 ——
const xs = inst.map((i) => i.x), zs = inst.map((i) => i.z), ys = inst.map((i) => i.y);
const min = (a) => Math.min(...a), max = (a) => Math.max(...a);
const [x0, x1, z0, z1, y0, y1] = [min(xs), max(xs), min(zs), max(zs), min(ys), max(ys)];
const W = 1400, PAD = 34;
const span = Math.max(x1 - x0, 1e-3);
const sc = (W - 2 * PAD) / span;
const H = Math.round((z1 - z0) * sc + 2 * PAD);
const px = (x) => PAD + (x - x0) * sc;
const py = (z) => H - PAD - (z - z0) * sc;

let g = '';
// 32 单位格子线（这是"平地 + 格子线"口径，不是地形）
for (let c = floor(x0, 32); c <= floor(x1, 32); c++)
  g += `<line x1="${px(c * 32)}" y1="${PAD / 2}" x2="${px(c * 32)}" y2="${H - PAD / 2}" stroke="#1d2b26" stroke-width="1"/>`;
for (let r = floor(z0, 32); r <= floor(z1, 32); r++)
  g += `<line x1="${PAD / 2}" y1="${py(r * 32)}" x2="${W - PAD / 2}" y2="${py(r * 32)}" stroke="#1d2b26" stroke-width="1"/>`;

let dots = '';
for (const it of inst) {
  const hit = !!it.name && hasMesh(it.name);
  dots += `<circle cx="${px(it.x).toFixed(1)}" cy="${py(it.z).toFixed(1)}" r="${hit ? 2.1 : 2.6}" fill="${hit ? '#6fb98f' : '#d59b3a'}" fill-opacity="0.75"/>`;
}

const stat = [
  [`格子文件`, `${grids.length} 个（另有 ${emptyGrids} 个只有 4 字节的空格子）`],
  [`摆位记录`, `${inst.length} 条`],
  [`能定位到模型文件`, `${joined} 条 = ${(joined / Math.max(inst.length, 1) * 100).toFixed(2)}%`],
  [`名字对不上`, `${inst.length - joined - emptyName} 条（对不上的裸名 ${uniqMiss.size} 个，没去猜该用哪个）`],
  [`名字为空`, `${emptyName} 条`],
  [`矩阵不成立即停`, `${badMatrix} 条`],
  [`格子号判据 floor(x/32)`, `${floorHit}/${inst.length} 吻合`],
  [`对比截断除法 trunc`, `${truncHit}/${inst.length} 吻合 ← 差 ${floorHit - truncHit} 条全在负半边`],
  [`负坐标实例`, `${neg} 条，其中 floor 判据成立 ${negFloor} 条、trunc 只有 ${negTrunc} 条`],
  [`占地`, `x ${x0.toFixed(0)}…${x1.toFixed(0)}，z ${z0.toFixed(0)}…${z1.toFixed(0)}（${(x1 - x0).toFixed(0)} × ${(z1 - z0).toFixed(0)} 单位）`],
  [`高度 y`, `${y0.toFixed(1)}…${y1.toFixed(1)} ← 只有物件脚印，地形格式未解`],
  [`tag 分布`, [...new Set(inst.map((i) => i.tag))].join(' / ') || '—'],
].map(([k, v]) => `<div><b>${k}</b><span>${v}</span></div>`).join('');

fs.writeFileSync(
  OUT,
  `<!doctype html><meta charset=utf-8>
<style>body{margin:0;background:#12191c;color:#dfe6ec;font:13px/1.7 system-ui,sans-serif}
header{padding:16px 22px 6px}h1{font-size:17px;margin:0 0 4px}
.sub{color:#8b9aa8;font-size:12.5px}
#stat{display:flex;flex-wrap:wrap;gap:4px 26px;padding:10px 22px 14px;border-bottom:1px solid #24333c}
#stat div{min-width:250px}#stat b{color:#8b9aa8;font-weight:400;margin-right:7px}
#legend span{display:inline-block;margin-right:18px}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:-1px}
svg{display:block}</style>
<header><h1>${MAP} · 摆位记录俯视散布（真数据，不是地形）</h1>
<div class="sub" id="legend">
<span><i class="dot" style="background:#6fb98f"></i>名字能在几何池里找到（${joined}）</span>
<span><i class="dot" style="background:#d59b3a"></i>名字对不上文件（${inst.length - joined - emptyName}）</span>
<span style="color:#8b9aa8">方格 = 32 单位，与客户端格子边界同源；高度未画</span>
</div></header>
<div id="stat">${stat}</div>
<svg width="${W}" height="${H}">${g}${dots}</svg>`,
);
console.log(
  JSON.stringify(
    { map: MAP, grids: grids.length, empty: emptyGrids, inst: inst.length, joined, miss: inst.length - joined - emptyName, floorHit, truncHit, neg, badMatrix, out: OUT },
    null,
    1,
  ),
);
