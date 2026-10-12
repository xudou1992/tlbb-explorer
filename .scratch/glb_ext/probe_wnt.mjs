// 「被权重用到但没有轨道」的骨带走了多少权重——驱动。
const CDP = process.env.CDP_PORT || '9227';
const JOBS = JSON.parse(process.env.JOBS || '[]');
const list = await (await fetch('http://127.0.0.1:' + CDP + '/json/list')).json();
const pages = list.filter(t => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise(res => { const mid = ++id; pend.set(mid, x => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async x => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return 'ERR ' + JSON.stringify(r.exceptionDetails).slice(0, 300);
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});
for (const job of JOBS) {
  await send('Page.navigate', { url: 'http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=' + encodeURIComponent(job.asset) + '&bones=0&view=three&_=' + Date.now() });
  await sleep(2600);
  for (let i = 0; i < 25 && !(await ev('!!window.__ready')); i++) await sleep(700);
  const expr = '(function(){var i=window.__info;var out=[];' +
    'for (var c=0;c<Math.min(3,(i.clips||[]).length);c++){out.push(window.__weightNoTrack(i.clips[c].name));}' +
    'return JSON.stringify({asset:i.asset,joints:i.joints,out:out});})()';
  const r = await ev(expr);
  if (String(r).startsWith('ERR')) { console.log(job.name + ': ' + String(r)); continue; }
  const j = JSON.parse(String(r));
  console.log('### ' + job.name + ' · ' + j.asset + ' · 骨架关节 ' + j.joints);
  for (const o of j.out) {
    console.log('  [' + o.clip + '] 轨道 ' + o.轨道数 + ' 条 · 有轨道骨名 ' + o.有轨道的骨名数 +
      ' · 被权重用到的骨 ' + o.被权重用到的骨 + ' · 其中没轨道的 ' + o.其中没轨道的);
    console.log('      权重合计 ' + o.权重合计 + ' · 落在没轨道骨上 ' + o.落在没轨道骨上的权重 + '（' + o.占比 + '%）· ' + JSON.stringify(o.最重的几根));
  }
}
ws.close();
