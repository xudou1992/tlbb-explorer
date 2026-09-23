// 顶点缓冲布局的契约测试。跑法：在 app/ 下 `node --test tests/`。
//
// 这条契约一头是 Rust 的 pack()，另一头是浏览器里的 typed array 视图。
// 偏移算错不会报错，只会把错数据画得像个模型——所以必须在进 WebGL 之前拦住。

import test from "node:test";
import assert from "node:assert/strict";
import { bufferLayout, validateMesh, base64Bytes } from "../web/lib/meshLayout.js";

const b64 = (bytes) => Buffer.from(bytes).toString("base64");

/// 按契约排一段缓冲：位置 → 法线? → UV? → 索引
function makeBuffer({ vc, ic, normals = false, uvs = false }) {
  const parts = [];
  const f32 = (n) => Float32Array.from({ length: n }, (_, i) => i * 0.001);
  parts.push(f32(vc * 3));
  if (normals) parts.push(f32(vc * 3));
  if (uvs) parts.push(f32(vc * 2));
  const idx = Uint16Array.from({ length: ic }, (_, i) => i % Math.max(vc, 1));
  let bytes = new Uint8Array(0);
  for (const p of [...parts, idx]) {
    const view = new Uint8Array(p.buffer);
    const merged = new Uint8Array(bytes.length + view.length);
    merged.set(bytes);
    merged.set(view, bytes.length);
    bytes = merged;
  }
  return b64(bytes);
}

test("静态布局：位置+法线+UV+索引 的偏移与总长", () => {
  const l = bufferLayout({ vertexCount: 781, indexCount: 2538, hasNormals: true, hasUvs: true });
  assert.equal(l.positions.at, 0);
  assert.equal(l.positions.bytes, 781 * 12);
  assert.equal(l.normals.at, 781 * 12);
  assert.equal(l.uvs.at, 781 * 12 * 2);
  assert.equal(l.indices.at, 781 * 32);
  assert.equal(l.total, 781 * 32 + 2538 * 2);
});

test("蒙皮布局：没法线没 UV 时索引紧跟位置", () => {
  const l = bufferLayout({ vertexCount: 10, indexCount: 3, hasNormals: false, hasUvs: false });
  assert.equal(l.normals, null);
  assert.equal(l.uvs, null);
  assert.equal(l.indices.at, 10 * 12);
  assert.equal(l.total, 10 * 12 + 6);
});

test("有 UV 但没法线：UV 偏移不能被算成法线段", () => {
  const l = bufferLayout({ vertexCount: 4, indexCount: 3, hasNormals: false, hasUvs: true });
  assert.equal(l.uvs.at, 4 * 12);
  assert.equal(l.indices.at, 4 * 12 + 4 * 8);
});

test("偏移叠加恒为 4 的倍数：Float32Array 视图才不会构造失败", () => {
  for (const vc of [1, 3, 17, 42, 781, 55864]) {
    for (const n of [true, false]) {
      for (const u of [true, false]) {
        const l = bufferLayout({ vertexCount: vc, indexCount: 3, hasNormals: n, hasUvs: u });
        assert.equal(l.positions.at % 4, 0);
        if (l.normals) assert.equal(l.normals.at % 4, 0, `法线偏移 vc=${vc}`);
        if (l.uvs) assert.equal(l.uvs.at % 4, 0, `UV 偏移 vc=${vc}`);
        assert.equal(l.indices.at % 2, 0, `索引偏移 vc=${vc}`);
      }
    }
  }
});

test("缓冲短了：报错并给出字节数，绝不进 WebGL", () => {
  const data = { vertexCount: 10, indexCount: 3, hasNormals: true, hasUvs: true, buffer: b64(new Uint8Array(20)) };
  assert.throws(() => validateMesh(data), /应有 326 字节，实际 20 字节/);
});

test("缓冲长了：同样拒绝——多出来的字节说明布局理解错了", () => {
  const ok = { vertexCount: 4, indexCount: 3, hasNormals: false, hasUvs: false };
  const long = { ...ok, buffer: b64(new Uint8Array(4 * 12 + 6 + 1)) };
  assert.throws(() => validateMesh(long), /实际 55 字节/);
});

test("长度对得上就通过，并交出字节与各段偏移", () => {
  const data = {
    vertexCount: 6, indexCount: 3, hasNormals: true, hasUvs: true,
    buffer: makeBuffer({ vc: 6, ic: 3, normals: true, uvs: true }),
  };
  const { bytes, layout } = validateMesh(data);
  assert.equal(bytes.byteLength, layout.total);
  assert.equal(layout.total, 6 * 32 + 6);
});

test("索引数不是 3 的倍数：凑不出完整三角面", () => {
  assert.throws(
    () => validateMesh({ vertexCount: 3, indexCount: 4, hasNormals: false, hasUvs: false, buffer: b64(new Uint8Array(36 + 8)) }),
    /不是 3 的倍数/,
  );
});

test("零顶点 / 零索引 / 没有缓冲 都单独说清", () => {
  assert.throws(() => validateMesh({ vertexCount: 0, indexCount: 3, buffer: b64(new Uint8Array(0)) }), /没有读到任何顶点/);
  assert.throws(() => validateMesh({ vertexCount: 3, indexCount: 0, buffer: b64(new Uint8Array(36)) }), /没有读到三角形索引/);
  assert.throws(() => validateMesh({}), /没有顶点缓冲/);
});

test("base64 解码字节级正确（含 = 填充）", () => {
  assert.deepEqual([...base64Bytes(b64([0, 1, 254, 255]))], [0, 1, 254, 255]);
});
