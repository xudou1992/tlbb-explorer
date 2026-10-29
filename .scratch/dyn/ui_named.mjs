const t = await (await fetch('http://127.0.0.1:9222/json/list')).json();
const pg = t.find(x => x.type === 'page' && (x.url || '').includes('tauri.localhost'));
if (!pg) { console.log('没找到页面'); process.exit(1); }
const ws = new WebSocket(pg.webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
const send = (met, params = {}) => new Promise(res => { const k = ++id; pend.set(k, r => res(r.result ?? r)); ws.send(JSON.stringify({ id: k, method: met, params })); });
const ev = async x => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true }); return r && 'value' in r ? r.value : r; };
for (let i = 0; i < 20; i++) { if (await ev('document.querySelectorAll(".chip").length>3')) break; await new Promise(r => setTimeout(r, 800)); }
console.log(await ev(`JSON.stringify({
  计数行: (document.body.innerText.split('\n').find(l=>l.includes('条资产'))||'').trim(),
  未命名条: [...document.querySelectorAll('button,.chip')].map(e=>(e.textContent||'').trim()).filter(s=>s.includes('未命名')),
  组数文案: [...document.querySelectorAll('*')].filter(e=>e.children.length===0&&/未命名/.test(e.textContent||'')&&(e.textContent||'').length<40).map(e=>e.textContent.trim()).slice(0,6)
})`) );
ws.close();
