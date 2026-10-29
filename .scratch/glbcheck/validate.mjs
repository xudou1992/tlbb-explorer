// 官方 Khronos glTF 校验器（Dart 编译成 JS 的那份）跑一份 .glb，输出 issues 全文。
// 用法：node validate.mjs <path.glb> [more.glb ...]
import fs from 'node:fs';
import { validateBytes, version } from './node_modules/gltf-validator/module.mjs';

console.log('validator', version());

for (const p of process.argv.slice(2)) {
  const bytes = new Uint8Array(fs.readFileSync(p));
  const report = await validateBytes(bytes, { uri: p, maxIssues: 0 });
  const info = report.issues;
  console.log('==== ' + p);
  console.log('counts:', JSON.stringify(info.counts));
  for (const k of ['errors', 'warnings', 'infos', 'hints']) {
    for (const it of info[k] || []) {
      console.log(`[${k}] ${it.code} @ ${(it.path || []).join('.')}: ${it.message}`);
    }
  }
}
