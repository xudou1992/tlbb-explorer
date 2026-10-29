import fs from 'fs';
import zlib from 'zlib';

const p = process.argv[2];
const outPrefix = process.argv[3] || '.scratch/uvcmp';
const b = fs.readFileSync(p);
const vc = b.readUInt32LE(0x8C), fc = b.readUInt32LE(0x90), smf = b.readUInt32LE(0x94), sm = smf || 1;
const posEnd = 0x118 + vc * 12;
let idxAt = -1;
const at0 = posEnd + vc * 20 + fc * 2;
const order = [at0];
for (let at = posEnd; at < b.length - 4 * sm; at += 2) order.push(at);
for (const at of order) {
  let s = 0, ok = true;
  for (let k = 0; k < sm; k++) { const v = b.readUInt32LE(at + k * 4); if (v > fc) { ok = false; break; } s += v; }
  if (!ok || s !== fc) continue;
  const ip = at + 4 * sm;
  let good = true;
  for (let i = 0; i < Math.min(fc * 3, 60); i++) if (b.readUInt16LE(ip + i * 2) >= vc) { good = false; break; }
  if (good) { idxAt = at; break; }
}
if (idxAt < 0) { console.error('no idx'); process.exit(1); }
const uvAt = posEnd + vc * 12, ip = idxAt + 4 * sm;
const decoders = {
  f32: (k) => [b.readFloatLE(uvAt + k * 8), b.readFloatLE(uvAt + k * 8 + 4)],
  u16_0: (k) => [b.readUInt16LE(uvAt + k * 8) / 65535, b.readUInt16LE(uvAt + k * 8 + 2) / 65535],
  u16_1: (k) => [b.readUInt16LE(uvAt + k * 8 + 4) / 65535, b.readUInt16LE(uvAt + k * 8 + 6) / 65535],
  u16_l1l3: (k) => [b.readUInt16LE(uvAt + k * 8 + 2) / 65535, b.readUInt16LE(uvAt + k * 8 + 6) / 65535],
};
function png(w, h, rgb) {
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 3 + 1)] = 0; rgb.copy(raw, y * (w * 3 + 1) + 1, y * w * 3, (y + 1) * w * 3); }
  const crcTable = new Int32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; return c; });
  const crc = (buf) => { let c = 0xFFFFFFFF; for (const x of buf) c = crcTable[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
  const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const cb = Buffer.alloc(4); cb.writeUInt32BE(crc(td)); return Buffer.concat([len, td, cb]); };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
}
for (const [name, uv] of Object.entries(decoders)) {
  const W = 512, H = 512, img = Buffer.alloc(W * H * 3);
  // dark background
  for (let i = 0; i < W * H; i++) { img[i * 3] = 20; img[i * 3 + 1] = 24; img[i * 3 + 2] = 30; }
  let drawn = 0;
  for (let f = 0; f < fc; f++) {
    const t = [b.readUInt16LE(ip + f * 6), b.readUInt16LE(ip + f * 6 + 2), b.readUInt16LE(ip + f * 6 + 4)];
    const P = t.map((k) => uv(k));
    if (!P.every((q) => Number.isFinite(q[0]) && Number.isFinite(q[1]))) continue;
    if (!P.every((q) => Math.abs(q[0]) < 4 && Math.abs(q[1]) < 4)) continue;
    drawn++;
    const X = P.map((q) => Math.round((q[0] % 1 + 1) % 1 * (W - 1)));
    const Y = P.map((q) => Math.round((1 - ((q[1] % 1 + 1) % 1)) * (H - 1)));
    const minx = Math.min(...X), maxx = Math.max(...X), miny = Math.min(...Y), maxy = Math.max(...Y);
    if (maxx - minx > 200 || maxy - miny > 200) continue;
    for (let y = miny; y <= maxy; y++) for (let x = minx; x <= maxx; x++) {
      const d = (Y[1] - Y[2]) * (X[0] - X[2]) + (X[2] - X[1]) * (Y[0] - Y[2]);
      if (!d) continue;
      const a = ((Y[1] - Y[2]) * (x - X[2]) + (X[2] - X[1]) * (y - Y[2])) / d;
      const bb = ((Y[2] - Y[0]) * (x - X[2]) + (X[0] - X[2]) * (y - Y[2])) / d;
      const c = 1 - a - bb;
      if (a < -0.02 || bb < -0.02 || c < -0.02) continue;
      const o = (y * W + x) * 3;
      const v = 120 + Math.round(120 * Math.abs(Math.sin(f * 12.9898) * 43758.5453 % 1));
      img[o] = v; img[o + 1] = 60 + (f % 180); img[o + 2] = 255 - (f % 200);
    }
  }
  fs.writeFileSync(`${outPrefix}_${name}.png`, png(W, H, img));
  console.log(name, 'triangles drawn', drawn, '/', fc);
}
