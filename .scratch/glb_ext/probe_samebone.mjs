// 单骨三角形检验的驱动：同一根骨带住的三角形，边长比必须 1.00（刚体保距）。
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
    'for (var c=0;c<Math.min(2,(i.clips||[]).length);c++){' +
    '  var nm=i.clips[c].name;var ts=(window.__times(nm).times||[]);var pick=[ts[Math.floor(ts.length/3)],ts[ts.length-2]];' +
    '  out.push({clip:nm,frames:pick.map(function(t){return window.__sameBoneTear(nm,t,true);})});' +
    '}return JSON.stringify({asset:i.asset,out:out});})()';
  const r = await ev(expr);
  if (String(r).startsWith('ERR')) { console.log(job.name + ': ' + String(r)); continue; }
  const j = JSON.parse(String(r));
  console.log('### ' + job.name + '  ' + j.asset);
  for (const c of j.out) {
    console.log('  [' + c.clip + ']');
    for (const f of c.frames) {
      console.log('    t=' + f.t + ' 同主骨三角形 ' + f.同主骨三角形 + ' 个 · 撕(>1.5倍) ' + f.同骨撕的 + ' · 最大 ' + f.最大倍数);
      console.log('      纯净(主权重≥0.99) ' + f.纯净同骨三角形 + ' 个 · 撕 ' + f.纯净撕的 + ' · 最大 ' + f.纯净最大倍数 + ' · 集中在 ' + JSON.stringify(f.撕集中的骨));
    }
  }
}
ws.close();
