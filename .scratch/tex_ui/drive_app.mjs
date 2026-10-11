// 驱动真窗口验证「贴图自动上模型」：搜→点→开立体预览→读状态→截图。
// 用法：NO_PROXY=127.0.0.1,localhost node drive_app.mjs [要搜的资产名]
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'chuansong001';
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
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 200)}`;
  // send() 已经把 CDP 的 {id,result:{result:{...}}} 解到 {type,value} 这一层，
  // 再解一次就永远是 undefined（本机第三次踩这条，写死在这里）。
  const v = r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value
    : r && r.result ? r.result.value : undefined;
  if (v === undefined) console.log('  [原始回包]', JSON.stringify(r).slice(0, 240));
  return v;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {});
await send('Runtime.enable', {}); // 不调这条，Runtime.evaluate 一律回 undefined（本机踩过两回）

console.log('页面：', await ev('document.title'));
console.log('搜索框：', await ev(`(()=>{const i=document.querySelector('input[type=search],input#q,input[placeholder]');
  return i? (i.id||i.name||i.placeholder) : '没找到';})()`));

// 1) 先切到「资产」页（默认页是浏览，浏览页那个框筛的是目录树，不是资产）
console.log('切页：', await ev(`(()=>{
  const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));
  if(!t) return '没有资产标签'; t.click(); return '已点「'+(t.textContent||'').trim().slice(0,8)+'」';})()`));
await sleep(2500);
// 2) 搜
console.log('搜：', await ev(`(async()=>{
  const box=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!box) return '没有资产搜索框：'+[...document.querySelectorAll('input')].map(i=>i.placeholder||i.id).join(' / ');
  box.focus(); box.value=${JSON.stringify(WANT)};
  box.dispatchEvent(new Event('input',{bubbles:true}));
  await new Promise(r=>setTimeout(r,3000));
  return '列表行数 '+document.querySelectorAll('.row-item').length;
})()`));
await sleep(1200);

// 2) 点第一行
console.log('点击：', await ev(`(()=>{const r=document.querySelector('.row-item');
  if(!r) return '没有可点的行'; r.click(); return (r.textContent||'').trim().slice(0,40);})()`));
await sleep(4500);

// 3) 打开立体预览（按钮文案含 立体/预览/模型 的都试一次）
console.log('预览按钮：', await ev(`(()=>{
  const bs=[...document.querySelectorAll('button,[role=tab],.tab')];
  const hit=bs.find(b=>/立体|3D|模型预览/.test(b.textContent||''));
  if(!hit) return '没找到预览入口：'+bs.map(b=>(b.textContent||'').trim()).filter(Boolean).slice(0,12).join(' / ');
  hit.click(); return (hit.textContent||'').trim();})()`));
await sleep(9000);

// 4) 读状态
const state = await ev(`JSON.stringify({
  meshHidden: document.getElementById('secMesh')?.hidden,
  meta: document.getElementById('meshMeta')?.textContent,
  texNote: document.getElementById('texNote')?.textContent,
  texHidden: document.getElementById('secTex')?.hidden,
  cards: document.querySelectorAll('#texCand .tex-cand').length,
  withImg: document.querySelectorAll('#texCand img[src]').length,
  ph: [...document.querySelectorAll('#texCand .tex-ph')].map(s=>s.textContent).slice(0,3),
  spread: [...document.querySelectorAll('#texCand .dim')].map(s=>s.textContent).filter(t=>t.includes('榜首出现过')).slice(0,3),
  gl: (()=>{const c=document.querySelector('#meshCv,canvas'); return c? c.width+'x'+c.height : 'no canvas';})(),
})`);
console.log('状态：', state);
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/tex_on_model.png`, Buffer.from(shot.data, 'base64'));
console.log('截图：', `${OUT}/tex_on_model.png`);
ws.close();
