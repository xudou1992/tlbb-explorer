// 顶点缓冲的字节布局。Rust 侧 `mesh_view.rs::pack()` 与这里是一对跨语言契约：
// 小端、紧排，顺序固定为 位置 → 法线(可选) → UV(可选) → 索引。
//
// 单独抽出来是因为偏移全靠 `hasNormals/hasUvs` 推，一旦声明和实际长度不符，
// 直接套 typed array 视图会把错数据画得像个模型——**必须在进 WebGL 之前拦住**。

/// 算出各段字节偏移与总长。不做校验，纯算术。
export function bufferLayout({ vertexCount, indexCount, hasNormals, hasUvs }) {
  const vc = Number(vertexCount) || 0;
  const ic = Number(indexCount) || 0;
  const positions = { at: 0, bytes: vc * 12 };
  let at = positions.bytes;
  const normals = hasNormals ? { at, bytes: vc * 12 } : null;
  if (normals) at += normals.bytes;
  const uvs = hasUvs ? { at, bytes: vc * 8 } : null;
  if (uvs) at += uvs.bytes;
  const indices = { at, bytes: ic * 2 };
  return { positions, normals, uvs, indices, total: indices.at + indices.bytes, vertexCount: vc, indexCount: ic };
}

/// 校验回包。不合规就抛带字节数的中文错，让界面能说清是数据问题而不是显卡问题。
export function validateMesh(data) {
  if (!data || typeof data.buffer !== "string") throw new Error("回包里没有顶点缓冲");
  const vc = Number(data.vertexCount) || 0;
  const ic = Number(data.indexCount) || 0;
  if (vc === 0) throw new Error("这个模型没有读到任何顶点");
  if (ic === 0) throw new Error("这个模型没有读到三角形索引");
  if (ic % 3 !== 0) throw new Error(`索引数 ${ic} 不是 3 的倍数，凑不出完整的三角面`);
  const bytes = base64Bytes(data.buffer);
  const want = bufferLayout(data);
  if (bytes.byteLength !== want.total) {
    throw new Error(
      `缓冲应有 ${want.total} 字节，实际 ${bytes.byteLength} 字节` +
        `（顶点 ${vc}、索引 ${ic}、法线${data.hasNormals ? "有" : "无"}、UV${data.hasUvs ? "有" : "无"}）`,
    );
  }
  return { bytes, layout: want };
}

/// base64 → 字节。1MB 上下的缓冲用查表比逐字符 charCodeAt 快得多。
export function base64Bytes(b64) {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}
