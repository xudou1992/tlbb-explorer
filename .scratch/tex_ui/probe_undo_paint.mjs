// 一次跑完就问一件事：撤销那一下重刷的到底是哪只资产（card_detail 的 gid），
// 以及是谁调的（栈）。顺带记下标的时候面板锚点 gid，两者不等就是「面板被换掉」。
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'w1351_monster_xiyuqiezei';
import { writeFileSync } from 'node:fs';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (pages.length !== 1) { console.log('页面数不是 1，停手'); process.exit(2); }
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
ws.addEventListener('close', () => { for (const f of pend.values()) f({ closed: true }); pend.clear(); });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 160)}`;
  if (r && r.closed) return 'CDP 连接断了';
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});
console.log('包 invoke：', await ev(`(()=>{const I=window.__TAURI_INTERNALS__;
  if(!I||typeof I.invoke!=='function') return '没有 invoke';
  if(I.__wrapped) return '已包过';
  window.__calls=[]; const raw=I.invoke.bind(I);
  I.invoke=function(cmd,payload){ try{ if(/card_detail|asset_inspect/.test(cmd))
    window.__calls.push({cmd,gid:payload&&payload.gid,t:Date.now()%100000,
      资产:(document.getElementById('dName')?.textContent||'').trim().slice(0,22),
      栈:(new Error()).stack.split(String.fromCharCode(10)).slice(1,6).map(s=>s.trim()).join(' <- ')});
  }catch(e){} return raw(cmd,payload);};
  I.__wrapped=true; return '好了';})()`));
await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(3000);
await ev(`(async()=>{const b=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!b)return; b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,3000));})()`);
await sleep(2000);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}))||rs[0]; hit.click();
  return hit.textContent.trim().slice(0,30);})()`));
await sleep(8000);
console.log('锚点：', await ev(`JSON.stringify({on:(document.querySelector('.row-item.on')||{}).dataset?.gid, 资产:(document.getElementById('dName')?.textContent||'').trim().slice(0,26), 槽位数:document.querySelectorAll('#texSlots li').length})`));
console.log('清空记录，标一条：', await ev(`(window.__calls.length=0, document.querySelector('#texCand .tex-group button[data-act="confirm"][data-idx="0"]') ? '点了' : (document.querySelector('#texCand .tex-group button[data-act="confirm"][data-idx="0"]'), '没有确认按钮'))`));
await sleep(4000);
console.log('标完之后调用：', await ev(`JSON.stringify(window.__calls.map(c=>({cmd:c.cmd,gid:c.gid,资产:c.资产})))`));
console.log('清空记录，撤销：', await ev(`(()=>{window.__calls.length=0;const b=document.querySelector('#texSlots button[data-act="clear"]');
  if(!b) return '没有撤销按钮'; b.click(); return '撤了 '+b.dataset.slot;})()`));
await sleep(9000);
const out = await ev(`JSON.stringify(window.__calls.map(c=>({cmd:c.cmd,gid:c.gid,资产:c.资产,栈:c.栈})).slice(0,5))`);
console.log('撤销期间调用与栈：', out);
console.log('现在面板：', await ev(`JSON.stringify({on:(document.querySelector('.row-item.on')||{}).dataset?.gid, 资产:(document.getElementById('dName')?.textContent||'').trim().slice(0,26), 槽位:(document.querySelector('#texSlots li')?.textContent||'').trim().slice(0,40)})`));
writeFileSync('D:/TLGL/.scratch/foreign_paint.json', String(out), 'utf8');
ws.close();
