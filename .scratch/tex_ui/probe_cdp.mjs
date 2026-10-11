const CDP = process.env.CDP_PORT ?? '9222';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
console.log('target:', page.url, page.title);
const ws = new WebSocket(page.webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const raw = (method, params) => new Promise((res) => { const mid = ++id; pend.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params })); });
console.log('enable:', JSON.stringify(await raw('Runtime.enable', {})).slice(0, 120));
for (const ex of ['1+1', 'typeof document', 'location.href', 'document.title', 'document.querySelectorAll(".row-item").length']) {
  const r = await raw('Runtime.evaluate', { expression: ex, returnByValue: true });
  console.log(ex, '→', JSON.stringify(r.result ?? r).slice(0, 160));
}
ws.close();
