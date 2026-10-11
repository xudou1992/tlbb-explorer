// 验已提交的修法真在跑着的 exe 里：把下拉塞成不在清单上的野值再点确认。
// 旧写法会静默写到「第一条未确认」，新写法必须一句话不写、并把原因显示在说明行。
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'w1351_monster_xiyuqiezei';
import { writeFileSync, mkdirSync } from 'node:fs';
mkdirSync('D:/TLGL/.scratch/ui_check', { recursive: true });
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (pages.length !== 1) { console.log('页面数不是 1，停手：' + pages.length); process.exit(2); }
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
await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(3000);
await ev(`(async()=>{const b=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!b) return; b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,3500));})()`);
await sleep(2500);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}))||rs[0]; hit.click(); return hit.textContent.trim().slice(0,34);})()`));
await sleep(6000);
console.log('塞野值：', await ev(`(()=>{const s=document.querySelector('#texCand .tex-slot-pick');
  if(!s) return '没有下拉'; s.value='一个不存在的槽位.tga'; return '下拉当前值 = '+s.value;})()`));
console.log('点确认：', await ev(`(()=>{const g=document.querySelector('#texCand .tex-group');
  g.querySelector('button[data-act="confirm"][data-idx="0"]').click(); return '点了';})()`));
await sleep(5000);
console.log('说明行：', await ev(`document.getElementById('texNote')?.textContent||''`));
console.log('有没有 🟢：', await ev(`[...document.querySelectorAll('#texSlots li')].filter(li=>li.textContent.includes('🟢')).map(li=>li.textContent.trim().slice(0,50)).join(' | ') || '一条都没有'`));
const s = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('D:/TLGL/.scratch/ui_check/bogus_slot_refused.png', Buffer.from(s.data, 'base64'));
ws.close();
