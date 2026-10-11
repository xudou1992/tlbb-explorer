const CDP = process.env.CDP_PORT ?? '9222';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (pages.length !== 1) { console.log('页面数不是 1，停手：' + pages.length); process.exit(2); }
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Runtime.enable', {});
console.log('撤销：', await ev(`(()=>{const b=[...document.querySelectorAll('#texSlots button[data-act="clear"]')];
  if(!b.length) return '没有撤销按钮'; b[0].click(); return '点了 '+b[0].dataset.slot+'（共 '+b.length+' 颗）';})()`));
await sleep(14000);
console.log('槽位现状：', await ev(`[...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().replace(/\s+/g,' ').slice(0,58)).join(' || ')`));
ws.close();
