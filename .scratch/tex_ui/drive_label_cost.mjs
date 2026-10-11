// 标一条要等多久：量「点确认 → 榜重画 → 16 张缩略图与 2 张分布图重新解回来」的实测耗时。
// 只测不改：跑完把那条测试标注撤掉。
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'w1351_monster_xiyuqiezei';
import { writeFileSync, mkdirSync } from 'node:fs';
mkdirSync('D:/TLGL/.scratch/ui_check', { recursive: true });
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

// 等到图重新齐了：先允许它被抹掉（n 掉下来），再等它回到 >=floor 连续两次
const WAIT_BACK = (floor, cap = 90) => `(async()=>{
  const t0=Date.now(); let wiped=false, last=-1, same=0;
  while(Date.now()-t0 < ${cap * 1000}){
    const n=document.querySelectorAll('#texCand img[src]').length;
    const u=document.querySelectorAll('#texCand .tex-uvmap img').length;
    if(n<${floor}) wiped=true;
    if(wiped && n>=${floor} && u>=1){ if(n===last) { if(++same>=2) return JSON.stringify({ms:Date.now()-t0, imgs:n, uv:u, wiped}); } else same=0; }
    last=n; await new Promise(r=>setTimeout(r,400));
  }
  return JSON.stringify({ms:-1, note:'超时没等回来', imgs:document.querySelectorAll('#texCand img[src]').length});})()`;

await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(3000);
await ev(`(async()=>{const b=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!b) return; b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,3500));})()`);
await sleep(2500);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}))||rs[0];
  if(!hit) return '没有行'; hit.click(); return hit.textContent.trim().slice(0,36);})()`));
console.log('第一次铺满：', await ev(WAIT_BACK(16)));

console.log('下拉当前值：', await ev(`(()=>{const s=document.querySelector('#texCand .tex-slot-pick'); return s? s.value : '没有下拉';})()`));
console.log('点确认：', await ev(`(()=>{const g=document.querySelector('#texCand .tex-group');
  const b=g.querySelector('button[data-act="confirm"][data-idx="0"]'); b.click(); window.__t=Date.now(); return '点了';})()`));
console.log('确认之后铺满：', await ev(WAIT_BACK(16)));
console.log('槽位清单：', await ev(`[...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().replace(/\\s+/g,' ').slice(0,56)).join(' || ')`));
const s = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('D:/TLGL/.scratch/ui_check/label_cost.png', Buffer.from(s.data, 'base64'));
console.log('撤销：', await ev(`(()=>{const b=document.querySelector('#texSlots button[data-act="clear"]');
  if(!b) return '没有撤销按钮'; b.click(); return '撤了 '+b.dataset.slot;})()`));
console.log('撤销之后铺满：', await ev(WAIT_BACK(16)));
console.log('最终槽位：', await ev(`[...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().replace(/\\s+/g,' ').slice(0,40)).join(' || ')`));
ws.close();
