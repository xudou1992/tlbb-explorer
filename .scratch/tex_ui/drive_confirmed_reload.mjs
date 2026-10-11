// 把「确认优先」这条承诺验到底：
// A) 直接问后端 mesh_override_png 拿不拿得到刚确认的那张；
// B) 强制一次真正的模型重载（点另一只资产再点回来），看标题行有没有「已套用人工确认的贴图」。
// 跑完撤销并核覆盖表回基线。
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = process.argv[2] ?? 'w1351_monster_xiyuqiezei';
const OTHER = process.argv[3] ?? 'w1351_monster_meiyingyanshi';
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
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 220)}`;
  if (r && r.closed) return 'CDP 断了';
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});
const META = `document.getElementById('meshMeta')?.textContent||'（没文字）'`;

async function openAsset(term) {
  await ev(`(async()=>{const b=document.getElementById('q'); if(!b) return;
    b.focus(); b.value=${JSON.stringify(term)}; b.dispatchEvent(new Event('input',{bubbles:true}));
    await new Promise(r=>setTimeout(r,4000));})()`);
  await sleep(1500);
  return ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
    const hit=rs.find(r=>(r.textContent||'').includes(${JSON.stringify('')}+${JSON.stringify(term.slice(0, 24))}));
    if(!hit) return '★列表里没有「'+${JSON.stringify(term)}+'」'; hit.click(); return hit.textContent.trim().slice(0,30);})()`);
}

console.log('打开目标资产：', await openAsset(WANT));
await sleep(12000);
console.log('① 初始标题：', await ev(META));
console.log('② 确认第 1 张（槽位=', await ev(`document.querySelector('#texCand .tex-group .tex-slot-pick')?.selectedOptions[0]?.value||''`), '）：',
  await ev(`(()=>{const b=document.querySelector('#texCand .tex-group button[data-act="confirm"][data-idx="0"]');
    if(!b) return '没有确认按钮'; b.click(); return '点了';})()`));
await sleep(4000);
// A) 直接问后端
console.log('③ 后端 mesh_override_png 回包：', await ev(`(async()=>{
  const I=window.__TAURI_INTERNALS__; if(!I||!I.invoke) return '没有 invoke 通道';
  const name=(document.getElementById('meshMeta')?.textContent.match(/(\\S+\\.mesh)/)||[])[1]||'w1351_monster_xiyuqiezei_shoutao_001.mesh';
  try{ const r=await I.invoke('mesh_override_png',{name:name});
    return JSON.stringify({name:name, got:!!r, keys:r?Object.keys(r):null, hash:r&&r.hash, slot:r&&r.slot,
      pngLen:r&&r.png?r.png.length:0});
  }catch(e){ return '调用报错：'+String(e && e.message || e); } })()`));
// B) 换一只资产再回来，逼一次真正的 loadMesh
console.log('④ 先点别的资产：', await openAsset(OTHER));
await sleep(11000);
console.log('   另一只的标题：', await ev(META));
console.log('⑤ 再点回目标：', await openAsset(WANT));
await sleep(13000);
console.log('   ★回来后标题：', await ev(META));
const s = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync('D:/TLGL/.scratch/ui_check/confirmed_reload.png', Buffer.from(s.data, 'base64'));
console.log('⑥ 撤销：', await ev(`(()=>{const b=document.querySelector('#texSlots button[data-act="clear"]');
  if(!b) return '没有撤销按钮'; b.click(); return '撤了 '+b.dataset.slot;})()`));
await sleep(12000);
ws.close();
