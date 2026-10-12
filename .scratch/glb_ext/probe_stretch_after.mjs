// 权重活了以后复判撕裂：拿 __stretch（逐三角形三条边的 bind 长度 vs 这一帧长度）
// 按**真实关键帧时刻**逐帧量，报倍数。10-09 那批边长账是拿旧导出量的，
// 那时这批文件整张挂根骨、边长恒等 1.0，「不撕」是空话。
const CDP = process.env.CDP_PORT ?? '9227';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
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
      const ts = (window.__times(c.name).times || []).slice(0, 10);
      const per = ts.map((x) => { const s = window.__stretch(c.name, x);
        return { t: x, edges: s.edges, over1_5: s.over1_5, over2: s.over2, max: s.maxRatio, split: s.split }; });
      const mx = Math.max(...per.map((x) => x.max || 0));
      rows.push({ clip: c.name, 帧数: ts.length, 最大边长倍数: mx,
        超2倍最多的时刻: per.slice().sort((a, b) => b.over2 - a.over2).slice(0, 3),
        逐帧: per.map((x) => x.t + '→' + x.max + '(过1.5:' + x.over1_5 + ' 过2:' + x.over2 + ')') });
    }
    return JSON.stringify({ asset: i.asset, skinned: i.skinnedMeshes, verts: i.verts, rows: rows });
  })()`);
  const j = JSON.parse(String(out));
  console.log(`\n### ${t.name}  ${j.asset} · SkinnedMesh ${j.skinned} · 顶点 ${j.verts}`);
  for (const r of j.rows || []) {
    console.log(`  [${r.clip}] 量了 ${r.帧数} 帧 · 最大边长倍数 ${r.最大边长倍数}`);
    console.log(`     ${r.逐帧.join('  ')}`);
    for (const x of r.超2倍最多的时刻) {
      console.log(`     t=${x.t}s 过 2 倍边 ${x.over2} 条 / ${x.edges} · 分裂分布 ${JSON.stringify(x.split)}`);
    }
  }
}
ws.close();
