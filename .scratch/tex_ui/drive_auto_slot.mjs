// 验「每份榜各自对准同名槽」：读每份榜下拉当前选中值 + 那句提示，再点第二份榜的确认，
// 看落盘的键是不是**那份榜网格同名**的那条槽（旧写法会落到第一条未确认的槽上）。
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
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 200)}`;
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});
await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(3000);
// 上一次会话留下的 kind/scenario 筛选会被 localStorage 恢复，列表里根本没有目标行，
// 于是「找不到就点第一行」把我们带到别的资产上。先点重置把筛子清掉。
console.log('清筛选：', await ev(`(()=>{const r=document.getElementById('reset');
  if(!r) return '没有重置按钮'; r.click(); return '点了重置';})()`));
await sleep(2500);
await ev(`(async()=>{const b=[...document.querySelectorAll('input')].find(i=>/搜|过滤|找/.test(i.placeholder||'')||i.type==='search');
  if(!b)return; b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,3000));})()`);
await sleep(2500);
// 搜索框必须按 id 打：资产页那个是 #q，浏览页还有一个 treeFilter（筛的是目录树）。
// 之前用 placeholder/正则「找第一个像搜索框的」，两次都打到 treeFilter 上——列表根本没筛，
// 于是「找不到目标就点第一行」把我们带到别的资产上，白跑三轮。
console.log('填搜索框：', await ev(`(async()=>{
  const b=document.getElementById('q');
  if(!b) return '没有 #q（资产页没起来？）：现存 input = '+[...document.querySelectorAll('input')].map(i=>i.id||i.type).join(',');
  b.focus(); b.value=${JSON.stringify(WANT)}; b.dispatchEvent(new Event('input',{bubbles:true}));
  await new Promise(r=>setTimeout(r,4500));
  const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.findIndex(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}));
  return '行数 '+rs.length+' · 目标在第 '+hit+' 行 · 第一行='+(rs[0]?.textContent||'').trim().slice(0,26);})()`));
await sleep(1200);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify(WANT)}));
  if(!hit) return '★列表里没有目标行，停手不点第一行'; hit.click(); return hit.textContent.trim().slice(0,34);})()`));
await sleep(9000);
console.log('每份榜：', await ev(`JSON.stringify([...document.querySelectorAll('#texCand .tex-group')].map(g=>({
  榜:g.dataset.gi,
  网格:(g.querySelector('p.dim')?.textContent||'').trim().slice(0,46),
  选中:(g.querySelector('.tex-slot-pick')?.selectedOptions[0]?.value)||'（没下拉）',
  提示:(g.querySelector('label.dim span.dim')?.textContent||g.querySelector('.tex-group label .dim:last-child')?.textContent||'').trim().slice(0,30),
})))`));
console.log('点第二份榜的确认：', await ev(`(()=>{const gs=[...document.querySelectorAll('#texCand .tex-group')];
  const g=gs[1]||gs[0]; const b=g.querySelector('button[data-act="confirm"][data-idx="0"]');
  if(!b) return '没有确认按钮';
  window.__want=(g.querySelector('.tex-slot-pick')?.selectedOptions[0]?.value)||'';
  window.__mesh=((g.querySelector('p.dim')?.textContent||'').match(/(\\S+)\\.mesh/)||[])[1]||'';
  b.click(); return '榜 '+g.dataset.gi+' 网格 '+window.__mesh+' → 选中槽 '+window.__want;})()`));
await sleep(4000);
console.log('说明行：', await ev(`document.getElementById('texNote')?.textContent||''`));
console.log('槽位清单：', await ev(`[...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().replace(/\\s+/g,' ').slice(0,54)).join(' || ')`));
const s = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('D:/TLGL/.scratch/ui_check/auto_slot.png', Buffer.from(s.data, 'base64'));
console.log('撤销：', await ev(`(()=>{const w=window.__want||'';
  const b=[...document.querySelectorAll('#texSlots button[data-act="clear"]')].find(x=>x.dataset.slot===w)||document.querySelector('#texSlots button[data-act="clear"]');
  if(!b) return '没有撤销按钮'; b.click(); return '撤了 '+b.dataset.slot;})()`));
await sleep(12000);
console.log('收口：', await ev(`[...document.querySelectorAll('#texSlots li')].map(li=>li.textContent.trim().slice(0,34)).join(' || ')`));
ws.close();
