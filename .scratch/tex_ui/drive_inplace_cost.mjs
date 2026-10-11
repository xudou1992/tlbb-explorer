// 验「确认不再整页重画」：点确认时缩略图一张都不许消失，🟢 要在几百毫秒内出现；
// 撤销仍走整页重刷（图会掉下去再回来），两条路的差别就是这次要的量。
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

// 点一颗按钮，同时按 120ms 采样「图还在不在 / 🟢 出没出」
const CLICK_AND_WATCH = (sel, kind) => `(async()=>{
  const q=()=>document.querySelectorAll('#texCand img[src]').length;
  const u=()=>document.querySelectorAll('#texCand .tex-uvmap img').length;
  const g=()=>[...document.querySelectorAll('#texSlots li')].filter(li=>li.textContent.includes('🟢')).length;
  const before={imgs:q(),uv:u(),green:g()};
  const b=document.querySelector(${JSON.stringify(sel)}); if(!b) return JSON.stringify({err:'没找到按钮 '+${JSON.stringify(sel)}});
  const t0=Date.now(); b.click();
  let minImgs=before.imgs, maxGap=0, greenAt=-1, noteAt=-1;
  for(let i=0;i<260;i++){
    await new Promise(r=>setTimeout(r,120));
    const n=q(); if(n<minImgs) minImgs=n;
    if(greenAt<0 && g()>before.green){ greenAt=Date.now()-t0; noteAt=greenAt; }
    if(greenAt>=0 && n>=before.imgs && u()>=1) { maxGap=Date.now()-t0; break; }
  }
  return JSON.stringify({before, minImgs, greenMs:greenAt, totalMs:maxGap,
    note:(document.getElementById('texNote')?.textContent||'').slice(0,72)});})()`;

await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(3000);
await ev(`(async()=>{const b=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!b) return; b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,3500));})()`);
await sleep(2500);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}))||rs[0]; hit.click(); return hit.textContent.trim().slice(0,34);})()`));
await sleep(9000);
console.log('下拉值：', await ev(`document.querySelector('#texCand .tex-slot-pick')?.value||'（没有下拉）'`));
console.log('确认这一枪：', await ev(CLICK_AND_WATCH('#texCand .tex-group button[data-act="confirm"][data-idx="0"]', 'confirm')));
const s = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('D:/TLGL/.scratch/ui_check/inplace_confirm.png', Buffer.from(s.data, 'base64'));
console.log('再标第二条（连着标的感觉）：', await ev(CLICK_AND_WATCH('#texCand .tex-group button[data-act="confirm"][data-idx="1"]', 'confirm2')));
console.log('撤销这一枪（该整页重刷）：', await ev(CLICK_AND_WATCH('#texSlots button[data-act="clear"]', 'clear')));
await sleep(9000);
console.log('收口清单：', await ev(`[...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().replace(/\\s+/g,' ').slice(0,44)).join(' || ')`));
ws.close();
