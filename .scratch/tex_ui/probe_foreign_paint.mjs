// 抓「详情区自己换资产」的元凶：把 Tauri 的 invoke 包住，记下每一次 card_detail/asset_inspect
// 的 gid 与调用栈；然后**什么都不点**，静置 60 秒看有没有外来的一次铺详情。
// 有栈就有名字，没栈就证明静置时不会自己换——两头都是结论。
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'w1351_monster_xiyuqiezei';
import { writeFileSync } from 'node:fs';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
console.log('页面目标数：', pages.length);
if (pages.length !== 1) { console.log('不止一个窗口，停手'); process.exit(2); }
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 200)}`;
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});

console.log('包 invoke：', await ev(`(()=>{
  const I = window.__TAURI_INTERNALS__;
  if(!I || typeof I.invoke !== 'function') return '没有 __TAURI_INTERNALS__.invoke：' + Object.keys(window).join(',').slice(0,120);
  if(I.__wrapped) return '已经包过了';
  window.__calls = [];
  const raw = I.invoke.bind(I);
  I.invoke = function(cmd, payload){
    try{
      if(/card_detail|asset_inspect/.test(cmd)){
        window.__calls.push({cmd, gid: payload && payload.gid, t: Date.now()%100000,
          资产:(document.getElementById('dName')?.textContent||'').trim().slice(0,24),
          栈:(new Error()).stack.split('\\n').slice(1,7).map(s=>s.trim()).join(' <- ')});
      }
    }catch(e){}
    return raw(cmd, payload);
  };
  I.__wrapped = true;
  return '已包住';})()`));

await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(3000);
await ev(`(async()=>{const b=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!b) return; b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,3500));})()`);
await sleep(2500);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}))||rs[0]; hit.click(); return hit.textContent.trim().slice(0,30);})()`));
await sleep(8000);
const g0 = await ev(`JSON.stringify({gid:(document.querySelector('.row-item.on')||{}).dataset?.gid, 资产:document.getElementById('dName')?.textContent.trim().slice(0,26)})`);
console.log('锚点（点了之后）：', g0);
await ev(`window.__calls.length=0`); // 只看静置期间的
console.log('静置 70 秒，期间不点任何东西…');
const seen = [];
for (let i = 0; i < 14; i++) {
  await sleep(5000);
  seen.push(await ev(`JSON.stringify({t:${i * 5 + 5}, 资产:(document.getElementById('dName')?.textContent||'').trim().slice(0,26), 调用数:window.__calls.length})`));
}
console.log(seen.join('\n'));
const calls = await ev(`JSON.stringify(window.__calls.slice(0,6))`);
console.log('静置期间的外来取数：', calls);
writeFileSync('D:/TLGL/.scratch/foreign_paint.json', String(calls) + '\n' + seen.join('\n'), 'utf8');
ws.close();
