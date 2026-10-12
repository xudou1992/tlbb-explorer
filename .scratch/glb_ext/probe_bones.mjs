// 决定性一问：这些救回来的 GLB 里，骨头到底动不动？
// 绕开包围盒缓存，直接读同一根骨在 t0/t1 的世界坐标差（台子的 __boneProbe）。
const CDP = process.env.CDP_PORT ?? '9333';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (!pages.length) { console.log('没有页面'); process.exit(1); }
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

for (const asset of JSON.parse(process.env.ASSETS ?? '[]')) {
  await send('Page.navigate', { url: `http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=${encodeURIComponent(asset.path)}&bones=0&view=three&_=${Date.now()}` });
  await sleep(2500);
  let ready = false;
  for (let i = 0; i < 25 && !ready; i++) { ready = await ev('!!window.__ready'); if (!ready) await sleep(700); }
  const clips = JSON.parse(String(await ev('JSON.stringify((window.__info && window.__info.clips || []).slice(0,3))')));
  console.log(`\n${asset.name}  动作数 ${clips.length}`);
  for (const c of clips) {
    const t1 = +(c.dur / 2).toFixed(3);
    const r = String(await ev(`JSON.stringify(window.__boneProbe(${JSON.stringify(c.name)}, 0, ${t1}, 8))`));
    let j = {}; try { j = JSON.parse(r); } catch { j = { raw: r }; }
    if (j.error) { console.log(`  ${c.name}: ${j.error}`); continue; }
    console.log(`  ${c.name}: 采了 ${j.bones} 根骨 · 动了 ${j.moved} 根 · 最大位移 ${j.maxDelta}` +
                ` · 样例 ${JSON.stringify(j.sample)}`);
  }
}
ws.close();
