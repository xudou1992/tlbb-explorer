// 人工确认这条链的完整验法（带页面守卫）：
//   0) 确认只有一个窗口在驱动，避免连到别人的页面；
//   1) 跳变检测：确认前后详情区必须是同一只资产；
//   2) 优先挑「槽名 = 某份榜的网格名」那条槽（这样确认才可能自动回到模型上）；
//   3) 确认 → 看 🟢、看标题行有没有「按人工确认」；4) 撤销 → 退回 🟡。
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'w1351_zuoqi_guchengfeisha';
const OUT = 'D:/TLGL/.scratch/ui_check';
import { writeFileSync, mkdirSync } from 'node:fs';
mkdirSync(OUT, { recursive: true });
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
console.log('页面目标数：', pages.length, pages.map((p) => p.title.slice(0, 24)));
if (pages.length !== 1) { console.log('不止一个窗口，停手——先弄清谁在驱动'); process.exit(2); }
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
console.log('标题：', await ev('document.title'));
await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(3000);
await ev(`(async()=>{const b=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!b) return; b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,3500));})()`);
await sleep(2500);
console.log('列表：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}))||rs[0];
  if(!hit) return '没有行'; hit.click(); return hit.textContent.trim().slice(0,46)+'（共 '+rs.length+' 行）';})()`));
await sleep(12000);
const READ = `JSON.stringify({
  资产: (document.getElementById('dName')?.textContent||'').trim().slice(0,40),
  槽位: [...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().replace(/\s+/g,' ').slice(0,64)),
  榜: [...document.querySelectorAll('#texCand .tex-group')].map(g=>(g.querySelector('p.dim')?.textContent||'').trim().slice(0,40)),
  分布图: document.querySelectorAll('#texCand .tex-uvmap img').length,
  标题行: (document.getElementById('meshMeta')?.textContent||'').slice(0,72),
})`;
console.log('确认前：', await ev(READ));
console.log('挑槽位：', await ev(`(()=>{
  const gs=[...document.querySelectorAll('#texCand .tex-group')]; if(!gs.length) return '没有榜';
  const meshes=gs.map(g=>((g.querySelector('p.dim')?.textContent||'').match(/网格\s+(\S+?)\.mesh/)||[])[1]).filter(Boolean);
  const sel=gs[0].querySelector('.tex-slot-pick'); if(!sel) return '没有槽位下拉';
  const stem=(s)=>s.replace(/\.(tga|dds|png|jpg|bmp|webp)$/i,'').replace(/_pbr$/i,'');
  const hit=[...sel.options].map(o=>o.value).find(v=>meshes.includes(stem(v)))
        || [...sel.options].map(o=>o.value).find(v=>meshes.includes(stem(v)+'_pbr'))
        || [...sel.options].pop();
  sel.value=hit; sel.dispatchEvent(new Event('change',{bubbles:true})); window.__want=hit;
  return '榜 0 网格 ['+meshes.join(',')+'] → 槽位 '+hit;})()`));
console.log('点确认：', await ev(`(()=>{const g=document.querySelector('#texCand .tex-group');
  const b=g&&g.querySelector('button[data-act="confirm"][data-idx="0"]'); if(!b) return '没有确认按钮';
  b.click(); return '已点（榜 0 第 1 张，槽位 '+window.__want+'）';})()`));
await sleep(16000);
console.log('确认后：', await ev(READ));
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/label_on.png`, Buffer.from(shot.data, 'base64'));
console.log('点撤销：', await ev(`(()=>{const w=window.__want||'';
  const b=[...document.querySelectorAll('#texSlots button[data-act="clear"]')].find(x=>!w||x.dataset.slot===w);
  if(!b) return '没有对应撤销按钮'; b.click(); return '已撤销 '+b.dataset.slot;})()`));
await sleep(14000);
console.log('撤销后：', await ev(READ));
const s2 = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/label_off.png`, Buffer.from(s2.data, 'base64'));
ws.close();
