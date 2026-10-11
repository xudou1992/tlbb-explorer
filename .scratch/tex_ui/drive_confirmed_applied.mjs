// 验「加载即贴」：人工确认过的槽位，重开模型时应当直接套**确认的那张**，
// 标题行写「已套用人工确认的贴图」，而不是再套一遍未确认的榜首。
// 跑完撤销，核覆盖表回到基线。
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
ws.addEventListener('close', () => { for (const f of pend.values()) f({ closed: true }); pend.clear(); });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 200)}`;
  if (r && r.closed) return 'CDP 断了';
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});

const META = `document.getElementById('meshMeta')?.textContent||'（立体预览没文字）'`;
await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(2500);
await ev(`(()=>{const r=document.getElementById('reset'); r&&r.click();})()`);
await sleep(2500);
await ev(`(async()=>{const b=document.getElementById('q'); if(!b) return;
  b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true}));
  await new Promise(r=>setTimeout(r,4000));})()`);
await sleep(2000);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}));
  if(!hit) return '★列表里没有目标行，停手'; hit.click(); return hit.textContent.trim().slice(0,32);})()`));
await sleep(12000);
console.log('① 刚打开：', await ev(META));
console.log('② 确认榜 0 的第 1 张（槽位=', await ev(`document.querySelector('#texCand .tex-group .tex-slot-pick')?.selectedOptions[0]?.value||'（没下拉）'`), '）：',
  await ev(`(()=>{const g=document.querySelector('#texCand .tex-group');
    const b=g&&g.querySelector('button[data-act="confirm"][data-idx="0"]'); if(!b) return '没有确认按钮';
    b.click(); return '点了';})()`));
await sleep(4000);
console.log('③ 确认后标题：', await ev(META));
// 重开模型：切到别的标签再切回立体预览，逼它走一遍「加载即贴」
console.log('④ 换页再回来：', await ev(`(()=>{
  const bs=[...document.querySelectorAll('[role=tab],.tabs button,.tab')];
  const other=bs.find(b=>/骨架|动作|材质/.test(b.textContent||''));
  const back=bs.find(b=>/立体|预览|模型/.test(b.textContent||''));
  if(!other||!back) return '找不到标签：'+bs.map(b=>(b.textContent||'').trim()).slice(0,8).join('/');
  other.click(); return '切到「'+other.textContent.trim()+'」';})()`));
await sleep(5000);
await ev(`(()=>{const b=[...document.querySelectorAll('[role=tab],.tabs button,.tab')].find(x=>/立体|预览|模型/.test(x.textContent||''));b&&b.click();})()`);
await sleep(12000);
console.log('⑤ 回来后标题：', await ev(META));
const s = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('D:/TLGL/.scratch/ui_check/confirmed_applied.png', Buffer.from(s.data, 'base64'));
console.log('⑥ 撤销：', await ev(`(()=>{const b=document.querySelector('#texSlots button[data-act="clear"]');
  if(!b) return '没有撤销按钮'; b.click(); return '撤了 '+b.dataset.slot;})()`));
await sleep(14000);
console.log('⑦ 撤销后标题：', await ev(META));
ws.close();
