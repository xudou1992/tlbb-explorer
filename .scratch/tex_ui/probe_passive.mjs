const CDP = process.env.CDP_PORT ?? '9222';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (method, params) => new Promise((res) => { const mid = ++id; pend.set(mid, (m) => res(m.result ?? m)); ws.send(JSON.stringify({ id: mid, method, params })); });
const ev = async (expr) => { const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Runtime.enable', {});
for (let i = 0; i < 6; i++) {
  console.log(i * 3 + 's', await ev(`JSON.stringify({
    want: window.__want ?? null,
    搜索框: [...document.querySelectorAll('input')].map(x=>x.value).filter(Boolean).slice(0,3),
    详情标题: (document.querySelector('#detail h2,#detailTitle,.detail-title')?.textContent||'').trim().slice(0,50),
    第一行: (document.querySelector('.row-item')?.textContent||'').trim().slice(0,32),
    meshMeta: (document.getElementById('meshMeta')?.textContent||'').slice(0,44),
    选中数: document.querySelectorAll('.row-item.sel,.row-item[aria-selected=true],.row-item.active').length,
  })`));
  await sleep(3000);
}
ws.close();
