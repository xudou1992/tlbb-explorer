// 撕边按「两端主权重骨有没有 96B 绑定记录」分类，跑在刚认回权重的 machao 上。
const CDP = process.env.CDP_PORT || '9227';
const MISSING = JSON.parse(process.env.MISSING || '[]');
const ASSET = process.env.ASSET || '/.scratch/glb_after_gate/m_f8e9433000036a9c.glb';
const list = await (await fetch('http://127.0.0.1:' + CDP + '/json/list')).json();
const pages = list.filter(t => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise(res => { const mid = ++id; pend.set(mid, x => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async x => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true }); return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});
await send('Page.navigate', { url: 'http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=' + encodeURIComponent(ASSET) + '&bones=0&view=three&_=' + Date.now() });
await sleep(2600);
for (let i = 0; i < 25 && !(await ev('!!window.__ready')); i++) await sleep(700);
const miss = JSON.stringify(MISSING);
const out = await ev('(function(){var ts=(window.__times("machao_behit01").times||[]).slice(0,8);' +
  'var rows=ts.map(function(t){return window.__tearPairs("machao_behit01",t,' + miss + ');});' +
  'return JSON.stringify({n:rows.length,rows:rows});})()');
const j = JSON.parse(String(out));
let tot = 0, byKind = {}, bySub = {};
for (const r of j.rows) { tot += r.over2; for (const [k, v] of Object.entries(r.按记录分类)) byKind[k] = (byKind[k] || 0) + v;
  for (const [k, v] of Object.entries(r.按子树分类 || {})) bySub[k] = (bySub[k] || 0) + v; }
console.log('量了 ' + j.n + ' 帧 · 过 2 倍的边合计 ' + tot);
for (const [k, v] of Object.entries(byKind)) console.log('  按自己有没有记录 — ' + k + ': ' + v + ' (' + (100 * v / tot).toFixed(1) + '%)');
for (const [k, v] of Object.entries(bySub)) console.log('  按整棵子树脏不脏 — ' + k + ': ' + v + ' (' + (100 * v / tot).toFixed(1) + '%)');
console.log('  骨名分类样本：' + JSON.stringify(j.rows[0].骨名分类样本));
const best = j.rows.slice().sort((a, b) => b.over2 - a.over2)[0];
console.log('\n撕得最狠那帧 t=' + best.t + '（' + best.over2 + '/' + best.edges + '）里涉及无记录骨的骨对 top：');
for (const [p, n] of best.涉及无记录的骨对) console.log('  ' + n + ' 条  ' + p);
ws.close();
