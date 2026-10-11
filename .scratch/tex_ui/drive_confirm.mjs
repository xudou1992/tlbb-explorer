// 驱动真窗口验证「人工确认」这一条链能不能走通：
//   选槽位（故意选下拉里最后一条，不是默认第一条）→ 点「确认这张」→ 看槽位清单变 🟢
//   → 撤销 → 看它退回 🟡。全程只碰覆盖表，不动原资源。
// 用法：NO_PROXY=127.0.0.1,localhost node drive_confirm.mjs [要搜的资产名]
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'w1351_monster_xiyuqiezei';
const OUT = 'D:/TLGL/.scratch/ui_check';

import { writeFileSync, mkdirSync } from 'node:fs';
mkdirSync(`${OUT}`, { recursive: true });

const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (!page) { console.log('没有 page 目标'); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
const pend = new Map();
let id = 0;
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pend.has(m.id)) { const f = pend.get(m.id); pend.delete(m.id); f(m.result ?? m); }
});
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (method, params) =>
  new Promise((res) => { const mid = ++id; pend.set(mid, (m) => res(m.result ?? m)); ws.send(JSON.stringify({ id: mid, method, params })); });
const ev = async (expr) => {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 240)}`;
  // send() 已经解过一层 {id,result:{result}}，再解一次就永远是 undefined（本机踩过三回）。
  const v = r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value
    : r && r.result ? r.result.value : undefined;
  if (v === undefined) console.log('  [原始回包]', JSON.stringify(r).slice(0, 240));
  return v;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {});
await send('Runtime.enable', {});

console.log('页面：', await ev('document.title'));
console.log('切页：', await ev(`(()=>{
  const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));
  if(!t) return '没有资产标签'; t.click(); return '已点「'+(t.textContent||'').trim().slice(0,8)+'」';})()`));
await sleep(2500);
console.log('搜：', await ev(`(async()=>{
  const box=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!box) return '没有资产搜索框';
  box.focus(); box.value=${JSON.stringify(WANT)};
  box.dispatchEvent(new Event('input',{bubbles:true}));
  await new Promise(r=>setTimeout(r,3000));
  return '列表行数 '+document.querySelectorAll('.row-item').length;})()`));
await sleep(1200);
console.log('点击：', await ev(`(()=>{const r=document.querySelector('.row-item');
  if(!r) return '没有可点的行'; r.click(); return (r.textContent||'').trim().slice(0,40);})()`));
await sleep(9000);

const READ = `JSON.stringify({
  slotLis: [...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().replace(/\\s+/g,' ').slice(0,90)),
  picks: [...document.querySelectorAll('#texCand .tex-group')].map(g=>({
    gi: g.dataset.gi,
    head: (g.querySelector('p.dim')?.textContent||'').trim().slice(0,44),
    opts: [...g.querySelectorAll('.tex-slot-pick option')].map(o=>o.value),
  })),
  uvImgs: document.querySelectorAll('#texCand .tex-uvmap img').length,
})`;
console.log('确认前：', await ev(READ));

// 选第 2 份榜（没有就第 1 份），把它的下拉指到清单里**最后**一条未确认槽位——
// 若后端/前端把键写错，落库的就不是这一条，事后核 JSON 能立刻看出来。
console.log('指槽位：', await ev(`(()=>{
  const gs=[...document.querySelectorAll('#texCand .tex-group')];
  const g=gs[1]||gs[0]; if(!g) return '没有榜';
  const sel=g.querySelector('.tex-slot-pick'); if(!sel) return '这份榜没有槽位下拉';
  const want=sel.options[sel.options.length-1].value;
  sel.value=want; sel.dispatchEvent(new Event('change',{bubbles:true}));
  window.__want=want;
  return '榜 '+g.dataset.gi+' → 槽位 '+want;})()`));

console.log('点确认：', await ev(`(()=>{
  const gs=[...document.querySelectorAll('#texCand .tex-group')];
  const g=gs[1]||gs[0]; if(!g) return '没有榜';
  const b=g.querySelector('button[data-act="confirm"][data-idx="0"]');
  if(!b) return '这份榜没有确认按钮';
  window.__before=document.querySelectorAll('#texSlots li').length;
  b.click(); return '已点「'+b.textContent.trim()+'」（榜 '+g.dataset.gi+' 的第 1 张）';})()`));
await sleep(14000);

const after = await ev(READ);
console.log('确认后：', after);
console.log('标题行：', await ev(`document.getElementById('meshMeta')?.textContent||'（立体预览没开）'`));
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/confirm_on.png`, Buffer.from(shot.data, 'base64'));
console.log('截图：', `${OUT}/confirm_on.png`);

console.log('点撤销：', await ev(`(()=>{
  const want=window.__want||'';
  const b=[...document.querySelectorAll('#texSlots button[data-act="clear"]')]
    .find(x=>!want||x.dataset.slot===want);
  if(!b) return '没有撤销按钮'; b.click(); return '已撤销 '+(b.dataset.slot||'');})()`));
await sleep(12000);
console.log('撤销后：', await ev(READ));
const shot2 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/confirm_cleared.png`, Buffer.from(shot2.data, 'base64'));
console.log('截图：', `${OUT}/confirm_cleared.png`);
ws.close();
