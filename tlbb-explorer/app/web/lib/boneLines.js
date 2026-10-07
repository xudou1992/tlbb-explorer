// 骨头连线：线段 → 可画的顶点对。
//
// 树在 Rust 里已经算完（父骨链、bind 求逆）。这里不认骨名、不补父子，
// 只丢掉画不了的：空的、坐标不是有限数的、凑不成一对的。
// 查看器拿到的就是一对一对的点，直接灌进线段缓冲。

function finitePoint(p) {
  if (!Array.isArray(p) || p.length !== 3) return null;
  const out = [0, 0, 0];
  for (let i = 0; i < 3; i++) {
    const n = p[i];
    if (typeof n !== "number" || !Number.isFinite(n)) return null;
    out[i] = n;
  }
  return out;
}

function unwrap(input) {
  if (input == null) return null;
  if (Array.isArray(input)) return input;
  if (typeof input === "object" && Array.isArray(input.lines)) return input.lines;
  return null;
}

/// 扁平数字、点列、还是已经成对的线段。看第一个认得出的元素。
function kindOf(src) {
  for (const item of src) {
    if (typeof item === "number") return "floats";
    if (!Array.isArray(item) || item.length === 0) continue;
    if (typeof item[0] === "number") return "points";
    return "segments";
  }
  return "segments";
}

function pushPair(out, a, b) {
  const pa = finitePoint(a);
  const pb = finitePoint(b);
  if (pa && pb) out.push([pa, pb]);
}

/// 每 6 个数一段。尾部凑不满 6 个（含奇数长度）丢掉，不拿剩下的去编一个端点。
function fromFloats(src) {
  const out = [];
  const n = src.length - (src.length % 6);
  for (let i = 0; i < n; i += 6) {
    pushPair(out, src.slice(i, i + 3), src.slice(i + 3, i + 6));
  }
  return out;
}

/// 点两两成对。奇数个点时最后一个没有对家，丢掉，不连到原点或上一段。
function fromPoints(src) {
  const out = [];
  const n = src.length - (src.length % 2);
  for (let i = 0; i < n; i += 2) pushPair(out, src[i], src[i + 1]);
  return out;
}

/// 每一段必须正好两个点。1 个或 3 个端点都不是一条线，整段丢掉。
function fromSegments(src) {
  const out = [];
  for (const seg of src) {
    if (!Array.isArray(seg) || seg.length !== 2) continue;
    pushPair(out, seg[0], seg[1]);
  }
  return out;
}

/// @param {unknown} input 回包 `{ lines }`、线段数组、点列，或扁平的 xyzxyz…
/// @returns {number[][][]} 可画的顶点对 `[[[x,y,z],[x,y,z]], …]`。空输入是 `[]`，不抛。
export function boneLineVertices(input) {
  const src = unwrap(input);
  if (!src || src.length === 0) return [];
  const kind = kindOf(src);
  if (kind === "floats") return fromFloats(src);
  if (kind === "points") return fromPoints(src);
  return fromSegments(src);
}
