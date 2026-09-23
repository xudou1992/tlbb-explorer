// Offline icon generator: no image library, no npm dependency. Writes PNGs by hand
// (zlib deflate + CRC) and an ICO carrying uncompressed 32bpp BMP frames.
import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = join(here, "..", "src-tauri", "icons");
mkdirSync(outDir, { recursive: true });

const crcTable = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(buf) {
  let c = 0xffffffff;
  for (const b of buf) c = crcTable[(c ^ b) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

/// pixel(x, y, size) -> [r, g, b, a]
function writePng(size, pixel) {
  const stride = size * 4 + 1;
  const raw = Buffer.alloc(stride * size);
  for (let y = 0; y < size; y++) {
    raw[y * stride] = 0; // filter: none
    for (let x = 0; x < size; x++) {
      const [r, g, b, a] = pixel(x, y, size);
      const o = y * stride + 1 + x * 4;
      raw[o] = r;
      raw[o + 1] = g;
      raw[o + 2] = b;
      raw[o + 3] = a;
    }
  }
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

/// ICO frames are bottom-up BGRA with a trailing 1-bit AND mask.
function writeBmp(size, pixel) {
  const ihdr = Buffer.alloc(40);
  ihdr.writeUInt32LE(40, 0);
  ihdr.writeInt32LE(size, 4);
  ihdr.writeInt32LE(size * 2, 8); // colour image + mask
  ihdr.writeUInt16LE(1, 12);
  ihdr.writeUInt16LE(32, 14);
  const px = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const [r, g, b, a] = pixel(x, size - 1 - y, size);
      const o = (y * size + x) * 4;
      px[o] = b;
      px[o + 1] = g;
      px[o + 2] = r;
      px[o + 3] = a;
    }
  }
  const mask = Buffer.alloc(Math.ceil(size / 32) * 4 * size);
  return Buffer.concat([ihdr, px, mask]);
}

function writeIco(sizes, pixel) {
  const frames = sizes.map((s) => ({ size: s, bmp: writeBmp(s, pixel) }));
  const head = Buffer.alloc(6);
  head.writeUInt16LE(1, 2);
  head.writeUInt16LE(frames.length, 4);
  const dir = Buffer.alloc(frames.length * 16);
  let at = head.length + dir.length;
  frames.forEach((f, i) => {
    const o = i * 16;
    dir[o] = f.size === 256 ? 0 : f.size;
    dir[o + 1] = f.size === 256 ? 0 : f.size;
    dir.writeUInt16LE(1, o + 2);
    dir.writeUInt16LE(32, o + 6);
    dir.writeUInt32LE(f.bmp.length, o + 8);
    dir.writeUInt32LE(at, o + 12);
    at += f.bmp.length;
  });
  return Buffer.concat([head, dir, ...frames.map((f) => f.bmp)]);
}

// The mark: a dark plate holding a jade ring (an asset still waiting on evidence) with
// a warm core.
function pixel(x, y, s) {
  const c = (s - 1) / 2;
  const dx = x - c;
  const dy = y - c;
  const r = Math.hypot(dx, dy) / (s / 2);
  const corner = Math.max(Math.abs(dx), Math.abs(dy)) / (s / 2);
  if (corner > 0.97) return [0, 0, 0, 0];
  const band = Math.abs(r - 0.62);
  const spoke = ((Math.atan2(dy, dx) + Math.PI) / (2 * Math.PI)) * 12;
  const ring = band < 0.05;
  const dashed = band < 0.09 && spoke % 1 > 0.2;
  const diamond = (Math.abs(dx) + Math.abs(dy)) / (s / 2);
  if (diamond < 0.24) {
    const t = diamond / 0.24;
    return [236 - Math.round(40 * t), 196 - Math.round(60 * t), 120 - Math.round(50 * t), 255];
  }
  if (ring || dashed) {
    const t = 1 - Math.min(1, band / 0.09);
    return [58 + Math.round(60 * t), 190 + Math.round(30 * t), 150 + Math.round(20 * t), 255];
  }
  const g = 1 - corner;
  return [24 + Math.round(10 * g), 27 + Math.round(14 * g), 33 + Math.round(18 * g), 255];
}

writeFileSync(join(outDir, "32x32.png"), writePng(32, pixel));
writeFileSync(join(outDir, "128x128.png"), writePng(128, pixel));
writeFileSync(join(outDir, "128x128@2x.png"), writePng(256, pixel));
writeFileSync(join(outDir, "icon.png"), writePng(512, pixel));
writeFileSync(join(outDir, "icon.ico"), writeIco([16, 24, 32, 48, 64, 128, 256], pixel));
console.log(`icons -> ${outDir}`);
