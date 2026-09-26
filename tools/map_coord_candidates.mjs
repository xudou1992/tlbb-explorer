// 选 M1（坐标证据闭环）的对照对象：从 --maps 真回包里挑两类实例。
//
// 为什么必须分两类：
//   ① 位置——挑又大又好认的建筑（城楼/神庙/王府/城墙），在客户端里一眼能找到那个。
//   ② 朝向——只有**旋转块不是轴对齐**的实例才能判 R / Rᵀ；对角矩阵两种解释一模一样，
//      拿它去"验朝向"是验了个寂寞。所以这一类要专门筛，还要物件本身不对称才有意义。
//
// 跑法：node tools/map_coord_candidates.mjs [地图ID]
// 产物：.scratch/map_coord_candidates.md（表格）+ .scratch/map_coord_candidates.json（原样矩阵）
import fs from "node:fs";

const ID = process.argv[2] || "w1351_ll_dl_002";
const FIX = `D:/TLGL/.scratch/ui_check/map_scene_${ID}.json`;
if (!fs.existsSync(FIX)) {
  console.error(`没有 ${FIX}\n先跑：tlbb-shell --maps ${ID}`);
  process.exit(2);
}
const d = JSON.parse(fs.readFileSync(FIX, "utf8"));
const eq = (a, b) => Math.abs(a - b) < 1e-4;

// 矩阵是 .scene 原样那 16 个 f32（GL 布局：平移在 [12..14]，行 r = [r,4+r,8+r]）。
const rows = d.instances.map((inst, k) => {
  const m = inst.matrix;
  const R = [m[0], m[4], m[8], m[1], m[5], m[9], m[2], m[6], m[10]];
  const s = [0, 1, 2].map((r) => Math.hypot(R[r * 3], R[r * 3 + 1], R[r * 3 + 2]));
  const mesh = d.meshes[inst.meshIndex];
  const ext = [0, 1, 2].map((a) => mesh.bboxMax[a] - mesh.bboxMin[a]);
  const world = ext.map((e, i) => e * s[i]);
  // 轴对齐 = 除了主对角以外全是 0；这种情况 R 与 Rᵀ 给同一个结果。
  const axisAligned = eq(R[1], 0) && eq(R[2], 0) && eq(R[3], 0) && eq(R[5], 0) && eq(R[6], 0) && eq(R[7], 0);
  const sym = eq(R[1], R[3]) && eq(R[2], R[6]) && eq(R[7], R[8]);
  // 绕 Y 的偏航角：直读 R[2] 与按 Rᵀ 解释取负，两者差多少就是要判的东西。
  const yaw = Math.atan2(R[2], R[0]) * 180 / Math.PI;
  return {
    k,
    name: mesh.path.split("/").pop(),
    grid: d.gridFiles[inst.gridIndex],
    record: inst.recordIndex,
    x: m[12], y: m[13], z: m[14],
    s,
    world,
    verts: mesh.vertexCount,
    faces: mesh.faceCount,
    axisAligned,
    sym,
    yaw,
    yawT: -yaw,
    matrix: m,
  };
});

const BIG = /cheng|si|wangfu|fangwu|dangpu|lou|qiao|men|ta|ting|yizhan|shufang/;

// 来源证据自证：登记的格子文件名应当等于用这条实例自己的平移算出来的格子号
// （floor(x/32) 对第 2 段、floor(z/32) 对第 3 段）。对不上就说明 grid_files 挂错了行，
// 那后面所有"回查那一条"的话都白说。
let cellHit = 0, cellMiss = [];
for (const r of rows) {
  const seg = r.grid.replace(/\.scene$/, "").split("_");
  const ok = Math.floor(r.x / 32) === +seg[1] && Math.floor(r.z / 32) === +seg[2];
  if (ok) cellHit++;
  else if (cellMiss.length < 3) cellMiss.push(`${r.grid} 第 ${r.record} 条 (${r.x.toFixed(1)},${r.z.toFixed(1)}) → ${Math.floor(r.x / 32)},${Math.floor(r.z / 32)}`);
}
const place = rows
  .filter((r) => BIG.test(r.name) && !r.axisAligned)
  .sort((a, b) => b.world[1] - a.world[1])
  .slice(0, 14);
const bigAny = rows
  .slice()
  .sort((a, b) => Math.max(...b.world) - Math.max(...a.world))
  .filter((r) => !r.name.includes("dz"))
  .slice(0, 10);
const facing = rows.filter((r) => !r.axisAligned && Math.abs(r.yaw) > 20).sort((a, b) => Math.abs(b.yaw) - Math.abs(a.yaw)).slice(0, 12);

const line = (r) =>
  `| \`${r.name}\` | \`${r.grid}\` 第 ${r.record} 条 | ${r.x.toFixed(2)}, ${r.y.toFixed(2)}, ${r.z.toFixed(2)} | ` +
  `${r.s.map((v) => v.toFixed(2)).join(" / ")} | ${r.world.map((v) => v.toFixed(1)).join(" × ")} | ` +
  `${r.yaw.toFixed(1)}° vs ${r.yawT.toFixed(1)}° | ${r.verts} / ${r.faces} |`;

const md = `# ${ID} 坐标与朝向对照候选 · 由 tools/map_coord_candidates.mjs 从真回包生成

矩阵是 \`.scene\` 记录原样直读的 16 个 f32（GL 布局：平移在 \`[12..14]\`，全程不转置）。
世界尺寸 = 网格包围盒 × 该实例三轴缩放。格子文件与第几条可直接回查原文件。

## A. 位置对照：全图占地最大的物件（先在客户端里认出它）

| 网格（客户端原文） | 出处 | 世界坐标 x, y, z | 三轴缩放 | 世界尺寸 x × y × z | 偏航 直读 vs 转置 | 顶点 / 面 |
|---|---|---|---|---|---|---|
${bigAny.map(line).join("\n")}

## B. 位置对照：名字就是建筑、且带旋转的

| 网格（客户端原文） | 出处 | 世界坐标 x, y, z | 三轴缩放 | 世界尺寸 x × y × z | 偏航 直读 vs 转置 | 顶点 / 面 |
|---|---|---|---|---|---|---|
${place.map(line).join("\n")}

## C. 朝向判定专用：偏航超过 20°（轴对齐的那些 R 与 Rᵀ 完全同解，判不了）

| 网格（客户端原文） | 出处 | 世界坐标 x, y, z | 三轴缩放 | 世界尺寸 x × y × z | 偏航 直读 vs 转置 | 顶点 / 面 |
|---|---|---|---|---|---|---|
${facing.map(line).join("\n")}

统计：实例 ${rows.length} 条 · 轴对齐（判不了朝向）${rows.filter((r) => r.axisAligned).length} 条 · ` +
`非对称旋转块 ${rows.filter((r) => !r.sym).length} 条 · 偏航>20° 且非轴对齐 ${rows.filter((r) => !r.axisAligned && Math.abs(r.yaw) > 20).length} 条

## D. 来源证据自证

用每条实例**自己的平移**算格子号（\`floor(x/32)\` 对文件名下标 1、\`floor(z/32)\` 对下标 2），
与 \`map_scene\` 登记的 \`gridFiles[gridIndex]\` 比：**${cellHit} / ${rows.length} 条吻合**${
  cellMiss.length ? `，不吻合的例：\n${cellMiss.map((m) => `- ${m}`).join("\n")}` : "，无一例外"
}
`;

fs.writeFileSync("D:/TLGL/.scratch/map_coord_candidates.md", md);
fs.writeFileSync(
  "D:/TLGL/.scratch/map_coord_candidates.json",
  JSON.stringify({ id: ID, picks: [...new Set([...bigAny, ...place, ...facing].map((r) => r.k))].map((k) => rows[k]) }, null, 1)
);
console.log(`写入 .scratch/map_coord_candidates.md 与 .json`);
console.log(`实例 ${rows.length} · 轴对齐 ${rows.filter((r) => r.axisAligned).length} · 偏航>20°非轴对齐 ${rows.filter((r) => !r.axisAligned && Math.abs(r.yaw) > 20).length} · 格子号自证 ${cellHit}/${rows.length}`);
