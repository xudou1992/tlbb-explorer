// 只问一件事：刚确认过的那格槽位，后端 mesh_override_png 认不认、给不给图。
// 上一次把中文前缀截进 name 里了，所以「got:false」不算结论。
const CDP = process.env.CDP_PORT ?? '9222';
const WANT = 'w1351_monster_xiyuqiezei';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (pages.length !== 1) { console.log('页面数不是 1，停手：', pages.length); process.exit(2); }
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return `ERR ${JSON.stringify(r.exceptionDetails).slice(0, 220)}`;
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Runtime.enable', {});
await ev(`(()=>{const t=[...document.querySelectorAll('button,[role=tab],.tab,a')].find(e=>(e.textContent||'').trim().startsWith('资产'));t&&t.click();})()`);
await sleep(2000);
await ev(`(async()=>{const b=document.getElementById('q'); b.focus(); b.value="${WANT}";
  b.dispatchEvent(new Event('input',{bubbles:true})); await new Promise(r=>setTimeout(r,4000));})()`);
await sleep(1500);
console.log('点行：', await ev(`(()=>{const rs=[...document.querySelectorAll('.row-item')];
  const hit=rs.find(r=>(r.textContent||'').includes("${WANT}")); if(!hit) return '没找到行'; hit.click();
  return hit.textContent.trim().slice(0,30);})()`));
await sleep(11000);
console.log('榜 0 的网格与槽位：', await ev(`(()=>{const g=document.querySelector('#texCand .tex-group');
  const mesh=((g.querySelector('p.dim')?.textContent||'').match(/网格\\s+(\\S+?\\.mesh)/)||[0,''])[1];
  return JSON.stringify({mesh:mesh, slot:g.querySelector('.tex-slot-pick')?.selectedOptions[0]?.value||''});})()`));
console.log('确认：', await ev(`(()=>{const b=document.querySelector('#texCand .tex-group button[data-act="confirm"][data-idx="0"]');
  if(!b) return '没有按钮'; b.click(); return '点了';})()`));
await sleep(4000);
console.log('表里现在：', await ev(`'见本机文件'`));
const probe = await ev(`(async()=>{
  const I=window.__TAURI_INTERNALS__; if(!I||!I.invoke) return JSON.stringify({err:'没有 invoke'});
  const g=document.querySelector('#texCand .tex-group');
  const mesh=((g.querySelector('p.dim')?.textContent||'').match(/网格\\s+(\\S+?\\.mesh)/)||[0,''])[1];
  const out={};
  for (const nm of [mesh, mesh.replace(/\\.mesh$/,'.mesh'), 'w1351_monster_xiyuqiezei_shoutao_001.mesh']) {
    if (!nm || out['k_'+nm]) continue;
    try {
      const r=await I.invoke('mesh_override_png',{name:nm});
      out['k_'+nm]= r? {hash:r.hash, slot:r.slot, png:(r.png||'').length} : null;
    } catch(e){ out['k_'+nm]='报错 '+String(e&&e.message||e); }
  }
  return JSON.stringify(out);})()`);
console.log('后端按各种名字要确认图：', probe);
console.log('标题行：', await ev(`document.getElementById('meshMeta')?.textContent||''`));
console.log('撤销：', await ev(`(()=>{const b=document.querySelector('#texSlots button[data-act="clear"]');
  if(!b) return '没有撤销按钮'; b.click(); return '撤了 '+b.dataset.slot;})()`));
await sleep(12000);
ws.close();
