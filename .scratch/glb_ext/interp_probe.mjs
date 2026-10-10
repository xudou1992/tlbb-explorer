// 插值探针：同一条动作，逐关键帧时刻 vs 帧中点各量一次包围盒。
// 用途：分清「导出值本身坏了」和「只在帧之间才坏（插值/四元数反号）」。
// 用法：NO_PROXY=... node interp_probe.mjs <glb 文件名> <动作名>
const CDP = process.env.CDP_PORT ?? '9227';
const PAGE = 'http://127.0.0.1:8765/.scratch/glb_ext/view.html';
const OUT = 'D:/TLGL/.scratch/glb_ext';
const [glb, clip] = process.argv.slice(2);
if (!glb || !clip) { console.log('要带 glb 与动作名'); process.exit(1); }

const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pend = new Map();
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); }
});
await new Promise((r) => ws.addEventListener('open', r, {once: true}));
const send = (method, params = {}) =>
  new Promise((res) => { const mid = ++id; pend.set(mid, res); ws.send(JSON.stringify({id: mid, method, params})); });
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', {width: 1280, height: 860, deviceScaleFactor: 1, mobile: false});
const ev = async (expr) => (await send('Runtime.evaluate', {expression: expr, returnByValue: true}))?.result?.value;

const url = `${PAGE}?asset=${encodeURIComponent('/.scratch/glb_ext/model/' + glb)}&view=side&quiet=1`;
await send('Page.navigate', {url});
for (let i = 0; i < 160 && !(await ev(`!!(window.__info&&window.__info.asset.endsWith(${JSON.stringify(glb)}))`)); i++) {
  await new Promise((r) => setTimeout(r, 250));
}
const times = await ev(`window.__keyTimes(${JSON.stringify(clip)})`);
if (!Array.isArray(times)) { console.log('拿不到时刻', times); process.exit(1); }
const mids = times.slice(0, -1).map((t, i) => +((t + times[i + 1]) / 2).toFixed(4));
const onKey = await ev(`window.__measure(${JSON.stringify(clip)}, ${JSON.stringify(times)})`);
const onMid = await ev(`window.__measure(${JSON.stringify(clip)}, ${JSON.stringify(mids)})`);
const fmt = (m, tag) => m.rows.map((r, i) => `${tag}${r.t}: grow ${r.grow} drift ${r.drift}`).join('\n');
console.log(`clip ${clip} · 关键帧 ${times.length} 个 · 帧距 ${times.length > 1 ? (times[1] - times[0]).toFixed(4) : '-'}`);
console.log('--- 落在关键帧上 ---\n' + fmt(onKey, 'K'));
console.log('--- 落在帧中点 ---\n' + fmt(onMid, 'M'));
const kg = onKey.rows.map((r) => r.grow), mg = onMid.rows.map((r) => r.grow);
console.log(`\n关键帧 grow 最大 ${Math.max(...kg)} · 帧中点 grow 最大 ${Math.max(...mg)}`);
import {writeFileSync} from 'node:fs';
writeFileSync(`${OUT}/interp_${glb}_${clip}.json`, JSON.stringify({glb, clip, times, onKey, onMid}, null, 1));
ws.close();
