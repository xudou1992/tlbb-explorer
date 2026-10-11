// 详情区自己换资产：每秒记一行（dName / 选中行 gid / 条数 / 顶栏进度），看跳变跟谁同步发生。
const CDP = process.env.CDP_PORT ?? '9222';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Runtime.enable', {});
console.log('采样器：', await ev(`(()=>{
  window.__j=[];
  const snap=()=>window.__j.push([Date.now()%100000,
    (document.getElementById('dName')?.textContent||'').trim().slice(0,26),
    'on='+(document.querySelector('.row-item.on')?.dataset?.gid||'-'),
    (document.getElementById('count')?.textContent||'').trim().slice(0,18),
    (document.getElementById('meshMeta')?.textContent||'').slice(0,20)]);
  snap(); window.__jt=setInterval(snap,1500); return ' started';})()`));
console.log('localStorage：', await ev(`Object.keys(localStorage).map(k=>k+'='+localStorage.getItem(k).slice(0,180)).join(' | ')`));
await sleep(48000);
const j = await ev(`JSON.stringify(window.__j)`);
await ev(`clearInterval(window.__jt)`);
const rows = JSON.parse(j);
let prev = '';
for (const r of rows) { const key = r[1] + '|' + r[2]; const mark = key !== prev ? '  ← 跳' : ''; prev = key; console.log(r.join(' | '), mark); }
ws.close();
