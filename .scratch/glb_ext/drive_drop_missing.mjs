// 因果实验的驱动：同一份 machao、同一把尺，先把无记录骨留在蒙皮里量一次，
// 再把它们的权重挪给最近的有记录祖先量第二次。两组数并排打出来。
const CDP = process.env.CDP_PORT || '9227';
const MISSING = JSON.parse(process.env.MISSING || '[]');
const ASSET = process.env.ASSET || '/.scratch/glb_after_gate/m_f8e9433000036a9c.glb';
const CLIP = process.env.CLIP || 'machao_behit01';
const list = await (await fetch('http://127.0.0.1:' + CDP + '/json/list')).json();
const pages = list.filter(t => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise(res => { const mid = ++id; pend.set(mid, x => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async x => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return 'ERR ' + JSON.stringify(r.exceptionDetails).slice(0, 260);
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});
await send('Page.navigate', { url: 'http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=' + encodeURIComponent(ASSET) + '&bones=0&view=three&_=' + Date.now() });
await sleep(2600);
for (let i = 0; i < 25 && !(await ev('!!window.__ready')); i++) await sleep(700);
const miss = JSON.stringify(MISSING);
const out = await ev('(function(){var ts=(window.__times(' + JSON.stringify(CLIP) + ').times||[]).slice(0,8);' +
  'var base=ts.map(function(t){var s=window.__stretch(' + JSON.stringify(CLIP) + ',t);return {t:t,edges:s.edges,over15:s.over1_5,over2:s.over2,max:s.maxRatio};});' +
  'var drop=window.__dropAndMeasure(' + JSON.stringify(CLIP) + ',ts,' + miss + ');' +
  'return JSON.stringify({ts:ts,base:base,drop:drop});})()');
if (String(out).startsWith('ERR')) { console.log(out); ws.close(); process.exit(1); }
const j = JSON.parse(String(out));
const sum = rows => ({ over2: rows.reduce((a, r) => a + r.over2, 0), over15: rows.reduce((a, r) => a + r.over15, 0), max: Math.max(...rows.map(r => r.max)), edges: rows.reduce((a, r) => a + r.edges, 0) });
const A = sum(j.base), B = sum(j.drop.rows);
console.log('clip ' + CLIP + ' · ' + j.ts.length + ' 帧 · 每帧 ' + (A.edges / j.ts.length) + ' 条边');
console.log('剔之前：过2倍 ' + A.over2 + ' · 过1.5倍 ' + A.over15 + ' · 最大 ' + A.max.toFixed(2) + '×');
console.log('剔之后：过2倍 ' + B.over2 + ' · 过1.5倍 ' + B.over15 + ' · 最大 ' + B.max.toFixed(2) + '×  （挪走槽位 ' + B.over2 + '）');
console.log('塌了多少：过2倍 ' + (100 * (1 - B.over2 / A.over2)).toFixed(1) + '% · 最大倍数降到 ' + (B.max / A.max).toFixed(2) + ' 倍于原值');
console.log('\n逐帧（过2倍 前 → 后 @最大倍数 前 → 后）：');
for (let i = 0; i < j.base.length; i++) console.log('  t=' + j.base[i].t + '  ' + j.base[i].over2 + '→' + j.drop.rows[i].over2 + '   ' + j.base[i].max + '→' + j.drop.rows[i].max);
console.log('挪走的关节槽位总数：' + j.drop.挪走的影响槽位);
ws.close();
