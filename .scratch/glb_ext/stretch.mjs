// 逐动作逐帧的「边长拉伸」表：分清正常摆动与真撕裂。
// 用法：NO_PROXY=... node stretch.mjs <glb> [动作名...]
const CDP = process.env.CDP_PORT ?? '9227';
const PAGE = 'http://127.0.0.1:8765/.scratch/glb_ext/view.html';
const [glb, ...want] = process.argv.slice(2);

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
const info = JSON.parse(await ev('JSON.stringify(window.__info)'));
const clips = want.length ? info.clips.filter((c) => want.includes(c.name)) : info.clips;
console.log(`${glb} · ${info.verts} 顶点 · ${info.joints} 关节 · 盒 ${JSON.stringify(info.box)}`);
console.log('动作 · 时刻 · 超 1.5 倍边数 · 超 2 倍 · 最大倍数 · 元凶骨 · 被拉开的边按「两端是否挂根」分类');
for (const c of clips) {
  const times = await ev(`window.__keyTimes(${JSON.stringify(c.name)})`);
  const sample = times.length > 6 ? times.filter((_, i) => i % Math.ceil(times.length / 6) === 0) : times;
  for (const t of sample) {
    const s = await ev(`window.__stretch(${JSON.stringify(c.name)}, ${t})`);
    if (!s || s.error) continue;
    const j = (s.topJoints ?? []).slice(0, 2).map(([n, k]) => n + ':' + k).join(' ');
    const sp = s.split ? ' 拆:' + JSON.stringify(s.split) + ' 挂根顶点:' + s.rootVerts : '';
    console.log(c.name + ' t=' + t + ' 超1.5 ' + s.over1_5 + '/' + s.edges + ' 超2 ' + s.over2 + ' max ' + s.maxRatio + ' ' + j + sp);
  }
}
ws.close();
