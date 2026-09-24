// 把三个真实 .scene 夹具的旋转块导成 CSV，供与客户端真机比对朝向。
// 只读；产物落 .scratch/。跑法：node tools/scene-rotation-samples.mjs为什么需要它：`.scene` 记录的平移已在字节上钉死
// （floor(x/32) 与格子号 6,119/6,119 吻合），但旋转那 9 个数到底是 R 还是 Rᵀ
// 没有证据——实测 257 个实例里 0 个旋转块对称，所以这个歧义对每个实例都活着，
// 只能靠"同一批物件在客户端里朝哪边"来定，不能靠看图顺眼。
import fs from "node:fs";

const DIR = "D:/TLGL/tlbb-explorer/crates/core/tests/scene_samples";
const OUT = "D:/TLGL/.scratch/scene_rotation_samples.csv";
const rows = ["sample,grid_index,name,r00,r01,r02,r10,r11,r12,r20,r21,r22,sx,sy,sz,symmetric,uniform"];

let n = 0,
  sym = 0,
  uni = 0;
for (const f of fs.readdirSync(DIR).filter((x) => x.endsWith(".scene"))) {
  const b = fs.readFileSync(`${DIR}/${f}`);
  const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
  const declared = dv.getUint32(0, true);
  const stride = dv.getUint32(4, true) + 8;
  for (let i = 0; i < declared; i++) {
    const off = 12 + i * stride;
    if (off + 64 > b.length) break;
    const m = [];
    for (let k = 0; k < 16; k++) m.push(dv.getFloat32(off + 4 * k, true));
    if (!(m[3] === 0 && m[7] === 0 && m[11] === 0 && m[15] === 1)) break;
    let s = b.subarray(off + 64, off + stride).toString("latin1").split("\0")[0].replace(/[^\x20-\x7e]/g, "");
    // GL 布局下第 r 行 = flat[r], flat[4+r], flat[8+r]
    const R = [m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]];
    const sc = [0, 1, 2].map((r) => Math.hypot(R[r * 3], R[r * 3 + 1], R[r * 3 + 2]));
    const eq = (a, c) => Math.abs(a - c) < 1e-4;
    const isSym = eq(R[1], R[3]) && eq(R[2], R[6]) && eq(R[7], R[8]);
    const isUni = eq(sc[0], sc[1]) && eq(sc[1], sc[2]);
    n++;
    if (isSym) sym++;
    if (isUni) uni++;
    rows.push(
      [
        f,
        i,
        JSON.stringify(s),
        ...R.map((v) => +v.toFixed(6)),
        ...sc.map((v) => +v.toFixed(4)),
        isSym ? 1 : 0,
        isUni ? 1 : 0,
      ].join(","),
    );
  }
}
fs.writeFileSync(OUT, rows.join("\n") + "\n");
console.log(`实例 ${n} 条 → ${OUT}`);
console.log(`旋转块对称（R==Rᵀ，转置与否无差别）: ${sym} 条 = ${(sym / n) * 100}%`);
console.log(`等比缩放（法线矩阵那套假设成立）  : ${uni} 条 = ${(uni / n) * 100}%`);
