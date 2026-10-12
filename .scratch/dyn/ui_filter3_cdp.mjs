// 定性：上一版「滤出 0 行」很可能是我自己留下的筛选状态（两行 chip 都有「全部」，
// 我点的那次只清了类型行的全部，用途行还开着「特效」⇒ 类型:界面资源 ∩ 用途:特效 = 空集）。
// 这版先按文案点「清空筛选」，再**只点一个类别**，看是不是正好 22 行。
const t = await (await fetch('http://127.0.0.1:9222/json')).json();
const page = t.find(x => x.type === 'page' && (x.url || '').startsWith('http://tauri.localhost'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0; const pend = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
const send = (met, params = {}) => new Promise(r => { const k = ++id; pend.set(k, r); ws.send(JSON.stringify({ id: k, method: met, params })); });
const expr = `(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const rows = () => document.querySelectorAll('.row-item').length;
  const kinds = () => [...new Set([...document.querySelectorAll('.row-item')].slice(0, 30)
    .map(e => { const s = e.querySelector('.s,.c'); return (s ? s.textContent : '').trim().split(' ')[0]; }))];
  const rep = { 进来时行数: rows() };
  const clr = [...document.querySelectorAll('button,[role=button]')].find(e => (e.textContent || '').trim().startsWith('清空筛选'));
  rep.找到清空 = !!clr;
  if (clr) { clr.click(); await sleep(2200); }
  rep.清空后行数 = rows();
  const chip = [...document.querySelectorAll('.chip')].filter(e => (e.getAttribute('data-value') || '') === '界面资源')[0];
  rep.找到界面资源chip = !!chip;
  if (chip) { chip.click(); await sleep(2200); }
  rep.只滤界面资源 = { 行数: rows(), 种类: kinds() };
  const clr2 = [...document.querySelectorAll('button,[role=button]')].find(e => (e.textContent || '').trim().startsWith('清空筛选'));
  if (clr2) { clr2.click(); await sleep(2000); }
  rep.再清空后行数 = rows();
  return rep;
})()`;
const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
const v = r.result && r.result.value ? r.result.value : r;
console.log(JSON.stringify(v));
process.exit(0);
