// 结掉「骨头在动、盒子不动」这一桩：__whyLie 现在同时报蒙皮属性、权重全零顶点数、
// 关节索引越界数、以及抽样顶点在 t1 相对 bind 真的被搬走多少个。
// 若 moved≈0 且权重全零/索引越界为真，那 grow=1.00 就不是量的错，是这张网格不吃骨架。
const CDP = process.env.CDP_PORT ?? '9333';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (!pages.length) { console.log('没有页面'); process.exit(1); }
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => {
  const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return 'ERR ' + JSON.stringify(r.exceptionDetails).slice(0, 300);
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});

for (const t of JSON.parse(process.env.JOBS ?? '[]')) {
  await send('Page.navigate', {
    url: `http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=${encodeURIComponent(t.asset)}&bones=0&view=three&_=${Date.now()}`,
  });
  await sleep(2600);
  for (let i = 0; i < 25 && !(await ev('!!window.__ready')); i++) await sleep(700);
  const out = await ev(`(()=>{
    const i = window.__info || {};
    const rows = [];
    for (const c of (i.clips || []).slice(0, 3)) {
      const tt = window.__times(c.name);
      const ts = tt.times || [0, c.dur];
      const pick = ts.length > 2 ? ts[ts.length - 1] : ts[ts.length - 1];
      const w = window.__whyLie(c.name, ts[0], pick);
      const h = window.__boneHull(c.name, ts.slice(0, 8));
      rows.push({ clip: c.name, 关键帧: ts.length, 取的末帧: pick,
        骨架盒最大涨缩: +Math.max(...h.rows.map((x) => x.grow)).toFixed(4),
        meshes: w.meshes });
    }
    return JSON.stringify({ asset: i.asset, 动作数: (i.clips || []).length, rows: rows });
  })()`);
  const j = JSON.parse(String(out));
  console.log(`\n### ${t.name}  ${j.asset}  动作 ${j.动作数} 条`);
  for (const r of j.rows) {
    console.log(`  [${r.clip}] 关键帧 ${r.关键帧} 末帧 ${r.取的末帧}s 骨架盒涨缩 ${r.骨架盒最大涨缩}`);
    for (const m of r.meshes) {
      console.log(`     ${m.mesh}: 顶点 ${m.顶点} 蒙皮索引 ${m.蒙皮索引} 权重 ${m.蒙皮权重}` +
        ` | 权重全零 ${m.权重全零顶点} 索引越界 ${m.索引越界} 最大索引 ${m.最大索引}/骨架 ${m.骨架长}` +
        ` | 动过的顶点 ${m.抽样式动过的顶点} | 骨变了 ${m.骨变了} 盒变了 ${m.盒变了}`);
      console.log(`        盒 ${JSON.stringify(m.盒_t0)} → ${JSON.stringify(m.盒_t1)}`);
    }
  }
}
ws.close();
