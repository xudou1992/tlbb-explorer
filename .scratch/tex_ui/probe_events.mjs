// 谁在改详情页？挂一层捕获监听，把真事件（isTrusted）与选中行变化录 25 秒。
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
console.log('挂监听：', await ev(`(()=>{
  window.__ev=[]; window.__sel=[];
  ['click','pointerdown','keydown','input','change'].forEach((t)=>
    document.addEventListener(t,(e)=>{
      if(window.__ev.length<40) window.__ev.push({t, trusted:e.isTrusted,
        tag:(e.target&&e.target.tagName)||'', cls:(e.target&&e.target.className)||'',
        gid:(e.target&&e.target.closest&&e.target.closest('.row-item')?.dataset?.gid)||'',
        x:Math.round(e.clientX||0), y:Math.round(e.clientY||0)});
    },true));
  const rows=document.getElementById('rows');
  const snap=()=>window.__sel.push([Date.now()%100000,(document.querySelector('.row-item.on')?.dataset?.gid)||'无',
    (document.getElementById('meshMeta')?.textContent||'').slice(0,30)]);
  snap(); window.__t=setInterval(snap,2000);
  return '已挂';})()`));
await sleep(26000);
console.log('事件（真点击才有）：', await ev(`JSON.stringify(window.__ev)`));
console.log('选中行/详情每 2 秒：', await ev(`JSON.stringify(window.__sel)`));
await ev(`clearInterval(window.__t)`);
ws.close();
