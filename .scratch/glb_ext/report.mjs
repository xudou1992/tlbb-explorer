// 逐顶点/逐骨报告：这一帧是谁把皮肤拉走的。
// 用法：NO_PROXY=... node report.mjs <glb> <动作名> <秒>
const CDP = process.env.CDP_PORT ?? '9227';
const PAGE = 'http://127.0.0.1:8765/.scratch/glb_ext/view.html';
const [glb, clip, tRaw] = process.argv.slice(2);
const t = parseFloat(tRaw ?? '0.5');

const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((x) => x.type === 'page' && x.webSocketDebuggerUrl);
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
const ev = async (expr) => (await send('Runtime.evaluate', {expression: expr, returnByValue: true}))?.result?.value;

await send('Page.navigate', {url: `${PAGE}?asset=${encodeURIComponent('/.scratch/glb_ext/model/' + glb)}&view=front&quiet=1`});
for (let i = 0; i < 160 && !(await ev(`!!(window.__info&&window.__info.asset.endsWith(${JSON.stringify(glb)}))`)); i++) {
  await new Promise((r) => setTimeout(r, 250));
}
console.log('bind 盒 =', await ev('JSON.stringify(window.__info.box)'));
console.log('\n== 逐顶点 ==');
console.log(await ev(`JSON.stringify(window.__vertexReport(${JSON.stringify(clip)}, ${t}), null, 1)`));
console.log('\n== 逐骨（这一帧的蒙皮矩阵）==');
console.log(await ev(`JSON.stringify(window.__boneReport(${JSON.stringify(clip)}, ${t}), null, 1)`));
console.log('\n== 静止对照 t=0 ==');
console.log(await ev(`JSON.stringify(window.__vertexReport(${JSON.stringify(clip)}, 0))`));
ws.close();
