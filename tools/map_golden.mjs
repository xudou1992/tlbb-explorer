// 地图金标准闸门：重跑 `tlbb-shell --maps`，把每张图的计数与 contracts/map_golden.json 逐字段比。
//
// 为什么要它：地图链的价值在于「界面说的数就是客户端里的数」。改了解析器、改了清单口径、
// 甚至改了客户端版本，这几张图的数字都会动——动了就必须说得出为什么动。
// 夹具本体（含 base64 几何，合计约 7.6MB）不入库，跑这条命令随时能重生成。
//
// 跑法：node tools/map_golden.mjs [shell 路径]
//   期望末行 `金标准一致`；任何一项对不上就列出来并以退出码 1 结束。
import { readFileSync, existsSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url)); // D:/TLGL/
const SHELL =
  process.argv[2] ||
  `${ROOT}tlbb-explorer/app/src-tauri/target/debug/tlbb-shell.exe`;
const DIR = `${ROOT}.scratch/ui_check`;
const GOLDEN = JSON.parse(readFileSync(`${ROOT}tlbb-explorer/contracts/map_golden.json`, "utf8"));

if (!existsSync(SHELL)) {
  console.error(`找不到 shell：${SHELL}\n先在 tlbb-explorer/app/src-tauri 下 cargo build --jobs 1`);
  process.exit(2);
}
const ids = Object.keys(GOLDEN.maps);
execFileSync(SHELL, ["--maps", ...ids], { stdio: "inherit" });

const bad = [];
const cmp = (label, want, got) => {
  const a = JSON.stringify(want), b = JSON.stringify(got);
  if (a !== b) bad.push(`${label}\n    金标准 ${a}\n    这次   ${b}`);
};

const list = JSON.parse(readFileSync(`${DIR}/map_list.json`, "utf8"));
cmp("map_list 目录数", GOLDEN.mapList.目录数, list.length);
cmp("map_list 格子总数", GOLDEN.mapList.格子总数, list.reduce((s, r) => s + r.grids, 0));
cmp("map_list 前三行", GOLDEN.mapList.前三行, list.slice(0, 3).map((r) => `${r.id} × ${r.grids}`));

for (const id of ids) {
  const f = `${DIR}/map_scene_${id}.json`;
  if (!existsSync(f)) {
    bad.push(`${id}\n    没落盘（--maps 没跑到这张？）`);
    continue;
  }
  const d = JSON.parse(readFileSync(f, "utf8"));
  const got = {
    grids: d.grids, emptyGrids: d.emptyGrids, unreadableGrids: d.unreadableGrids,
    records: d.records, resolved: d.resolved, missingMeshes: d.missingMeshes,
    unreadableMeshes: d.unreadableMeshes, notMesh: d.notMesh, oddNames: d.oddNames,
    emptyNamed: d.emptyNamed, uniqueMeshes: d.uniqueMeshes, instances: d.instances.length,
    vertices: d.meshes.reduce((s, m) => s + m.vertexCount, 0),
    faces: d.meshes.reduce((s, m) => s + m.faceCount, 0),
    bufferBytes: d.meshes.reduce((s, m) => s + m.buffer.length, 0),
    gridReasons: d.gridReasons.map((r) => `${r.reason} × ${r.grids}`),
    otherExt: d.otherExt.map((x) => `.${x.ext} × ${x.records}`),
    missingSample: d.missingSample,
  };
  for (const k of Object.keys(GOLDEN.maps[id])) cmp(`${id} · ${k}`, GOLDEN.maps[id][k], got[k]);
  console.log(
    `  ${id} 格子 ${got.grids} · 记录 ${got.records} · 画得出 ${got.resolved} · 网格 ${got.uniqueMeshes}`
  );
}

if (bad.length) {
  console.error(`\n金标准不一致 ${bad.length} 处：`);
  for (const b of bad) console.error("  - " + b);
  process.exit(1);
}
console.log(`\n金标准一致：${ids.length} 张图逐字段对上（清单 ${list.length} 个目录）`);
