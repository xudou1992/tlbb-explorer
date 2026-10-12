// 用 __times + __boneHull 结掉「24/26 有骨在动，2 条零位移」那两条：
// 如果按真实关键帧时刻量之后骨架盒会动，那零位移是取点问题；如果还不动，才是动作本身没数据。
const CDP = process.env.CDP_PORT ?? '9333';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return 'ERR ' + JSON.stringify(r.exceptionDetails).slice(0, 200);
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});

for (const t of JSON.parse(process.env.JOBS ?? '[]')) {
  await send('Page.navigate', { url: `http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=${encodeURIComponent(t.path)}&bones=0&view=three&_=${Date.now()}` });
  await sleep(2500);
  for (let i = 0; i < 25 && !(await ev('!!window.__ready')); i++) await sleep(700);
  const r = await ev(`(()=>{
    const i = window.__info || {};
    const out = [];
    for (const c of (i.clips || [])) {
      const tt = window.__times(c.name);
      const times = (tt.times || []).slice(0, 8);
      const h = window.__boneHull(c.name, times.length ? times : [0, c.dur]);
      const grow = Math.max(...(h.rows || [{ grow: 0 }]).map((x) => x.grow));
      const drift = Math.max(...(h.rows || [{ drift: 0 }]).map((x) => x.drift));
      out.push({ clip: c.name, 帧数: tt.keys, 时长: tt.duration, 骨架骨数: h.bones,
        最大涨缩: +grow.toFixed(3), 最大漂移: +drift.toFixed(4),
        逐时刻: (h.rows || []).map((x) => x.grow + '/' + x.drift).slice(0, 6) });
    }
    return JSON.stringify({ asset: i.asset, clips: out });
  })()`);
  const j = JSON.parse(String(r));
  console.log(`\n${t.name}  ${j.asset || ''}`);
  for (const c of j.clips) {
    const moved = c.最大涨缩 > 1.001 || c.最大漂移 > 0.001;
    console.log(`  ${c.clip}: 真实关键帧 ${c.帧数} 个 · 时长 ${c.时长}s · 骨架 ${c.骨架骨数} 根` +
                ` · 涨缩 ${c.最大涨缩} · 漂移 ${c.最大漂移} → ${moved ? '骨架在动' : '★仍然一动不动'}`);
  }
}
ws.close();
