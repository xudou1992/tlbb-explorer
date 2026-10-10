// 外部查看器验收驱动：CDP 开着的本机 Chrome，把 HEAD 导出的 rigged .glb 交给
// three.js 自己蒙皮播放（GLTFLoader + AnimationMixer + SkinnedMesh CPU 蒙皮），
// 逐条动作逐帧量包围盒。判据写在 run.txt，画面在 shots/。
// 用法：NO_PROXY=127.0.0.1,localhost node verify.mjs [--only=关键字] [--shots]
const CDP = process.env.CDP_PORT ?? '9227';
const PAGE = 'http://127.0.0.1:8765/.scratch/glb_ext/view.html';
const OUT = 'D:/TLGL/.scratch/glb_ext';

import {readFileSync, writeFileSync, mkdirSync} from 'node:fs';

const manifest = JSON.parse(readFileSync(`${OUT}/model/manifest.json`, 'utf8'));
const only = (process.argv.find((a) => a.startsWith('--only=')) ?? '').slice(7);
let assets = manifest.assets.filter((a) => a.rigged && a.animations?.length);
if (only) assets = assets.filter((a) => (a.name ?? a.path).includes(only));

const PREFER = ['idle01', 'idle', 'fight_idle01', 't_pose', 'walk', 'run', 'dead', 'behit01', 'hit01'];
const pickClips = (names) => {
  const hit = [];
  for (const p of PREFER) {
    const m = names.find((n) => n.includes(p) && !hit.includes(n));
    if (m) hit.push(m);
    if (hit.length === 4) break;
  }
  return hit.length ? hit : names.slice(0, 3);
};

const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (!page) { console.log('没有 page 目标，Chrome 没起来？'); process.exit(1); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pend = new Map();
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
});
await new Promise((r) => ws.addEventListener('open', r, {once: true}));
const send = (method, params = {}) =>
  new Promise((res) => { const mid = ++id; pend.set(mid, (m) => res(m.result ?? m)); ws.send(JSON.stringify({id: mid, method, params})); });
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', {width: 1280, height: 860, deviceScaleFactor: 1, mobile: false});

const ev = async (expr) => {
  const r = await send('Runtime.evaluate', {expression: expr, returnByValue: true});
  if (r?.exceptionDetails) return {__err: JSON.stringify(r.exceptionDetails).slice(0, 200)};
  return r?.result?.value;
};
// 只认「这一份 glb 的就绪标记」：上一份的 window.__ready 在新文档落地前还在，
// 拿布尔值轮询会把上一份的结果当这一份的。
const openAsset = async (glb, qs) => {
  const url = `${PAGE}?asset=${encodeURIComponent('/.scratch/glb_ext/model/' + glb)}&${qs}`;
  await send('Page.navigate', {url});
  for (let i = 0; i < 160; i++) {
    const ready = await ev(`!!(window.__info && window.__info.asset && window.__info.asset.endsWith(${JSON.stringify(glb)}))`);
    if (ready) return true;
    const err = await ev('window.__error||""');
    if (err) { lastError = err; return false; }
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
};
let lastError = '';
const shot = async (file) => {
  const r = await send('Page.captureScreenshot', {format: 'png'});
  if (!r?.data) return `拍失败 ${JSON.stringify(r).slice(0, 100)}`;
  writeFileSync(`${OUT}/shots/${file}`, Buffer.from(r.data, 'base64'));
  return `${OUT}/shots/${file}`;
};
mkdirSync(`${OUT}/shots`, {recursive: true});

const rows = [];
for (const a of assets) {
  if (!await openAsset(a.glb, 'view=three')) {
    rows.push({name: a.name, glb: a.glb, err: lastError || '超时未就绪'});
    console.log(`${a.name}: 没就绪（${lastError || '超时'}）`);
    continue;
  }
  const parsed = JSON.parse(await ev('JSON.stringify(window.__info)'));
  const want = pickClips(parsed.clips.map((c) => c.name));
  const measures = [];
  for (const name of want) {
    const clip = parsed.clips.find((c) => c.name === name);
    if (!clip) continue;
    const times = [0, .25, .5, .75, 1].map((f) => +(f * clip.dur).toFixed(3));
    const m = await ev(`window.__measure(${JSON.stringify(name)}, ${JSON.stringify(times)})`);
    if (m && !m.error) measures.push(m);
  }
  const f0 = measures.map((m) => ({clip: m.clip, grow: m.rows[0].grow, drift: m.rows[0].drift}));
  const rest = measures.flatMap((m) => m.rows.slice(1).map((r) => ({clip: m.clip, t: r.t, grow: r.grow, drift: r.drift})));
  rest.sort((x, y) => y.grow - x.grow);
  rows.push({
    name: a.name, glb: a.glb, verts: parsed.verts, joints: parsed.joints,
    skinnedMeshes: parsed.skinnedMeshes, clips: parsed.clips.length,
    clipNames: parsed.clips.map((c) => c.name), bindBox: parsed.box, bindSpan: measures[0]?.bindSpan,
    measures, f0, worst: rest.slice(0, 3),
  });
  console.log(`${a.name}: 关节 ${parsed.joints} · 动作 ${parsed.clips.length} · 第0帧 grow ${f0.map((x) => x.grow).join('/')} drift ${f0.map((x) => x.drift).join('/')}`);
}

writeFileSync(`${OUT}/measure.json`, JSON.stringify(rows, null, 1));

if (process.argv.includes('--shots')) {
  const main = rows.find((r) => r.glb && r.measures?.length);
  const a = main && manifest.assets.find((x) => x.glb === main.glb);
  if (!a) console.log('没有可截图的成功样本');
  else {
    const byHint = (h) => main.clipNames.find((n) => n.includes(h));
    const plan = [
      ['a_rest', 'view=front&bones=0&quiet=1', 'window.__rest()'],
      ['b_bones', 'view=front&bones=1&quiet=1', `window.__shotFrac(${JSON.stringify(main.measures[0].clip)}, .5)`],
      ['c_idle_mid', 'view=front&bones=0&quiet=1', `window.__shotFrac(${JSON.stringify(main.measures[0].clip)}, .5)`],
      ['d_walk_side', 'view=side&bones=0&quiet=1', `window.__shotFrac(${JSON.stringify(byHint('walk') ?? main.measures[0].clip)}, .5)`],
      ['e_run_peak', 'view=three&bones=0&quiet=1', `window.__shotFrac(${JSON.stringify(byHint('run') ?? main.measures[0].clip)}, .35)`],
      ['f_dead_end', 'view=front&bones=0&quiet=1', `window.__shotFrac(${JSON.stringify(byHint('dead') ?? main.measures[0].clip)}, .9)`],
    ];
    for (const [tag, qs, pose] of plan) {
      if (!pose) continue;
      if (!await openAsset(a.glb, qs)) { console.log(`${tag}: 没就绪`); continue; }
      const ok = await ev(pose);
      const r = await send('Page.captureScreenshot', {format: 'png'});
      if (r?.data) writeFileSync(`${OUT}/shots/${tag}_${main.name}.png`, Buffer.from(r.data, 'base64'));
      console.log('shot', `${tag}_${main.name}.png`, ok === true ? '盒=' + JSON.stringify(await ev('JSON.stringify(window.__lastBox||null)')) : '姿态没吃上:' + JSON.stringify(ok));
    }
  }
}
console.log(`\n共 ${rows.length} 份，明细见 ${OUT}/measure.json`);
ws.close();
