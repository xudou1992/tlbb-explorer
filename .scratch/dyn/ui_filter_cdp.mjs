// 上一轮「点特效行数不变」是我判据错（一屏上限 300 行、特效 6,473 条）。这轮换成：
// 比**可见行的名字集合** + 读筛选条的 active 类，并且点的是 chip 的可点祖先（上一版可能只点到子 span）。
const t = await (await fetch('http://127.0.0.1:9222/json')).json();
const page = t.find(x => x.type === 'page' && (x.url || '').startsWith('http://tauri.localhost'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0; const pend = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
const send = (met, params = {}) => new Promise(r => { const k = ++id; pend.set(k, r); ws.send(JSON.stringify({ id: k, method: met, params })); });
const expr = `(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const names = () => [...document.querySelectorAll('.row-item .t')].slice(0, 6).map(e => (e.textContent||'').trim());
  const kinds = () => [...document.querySelectorAll('.row-item')].slice(0, 40).map(e => {
    const s = e.querySelector('.s,.c'); return (s ? s.textContent : '').trim().slice(0, 10); });
  const chipState = () => [...document.querySelectorAll('button,.chip,[role=button],.fchip,.active,[class*=active]')]
    .filter(e => /特效|全部|场景物件|玩家角色/.test((e.textContent||'').trim()) && (e.textContent||'').trim().length < 14)
    .slice(0, 8).map(e => ({ 文: (e.textContent||'').trim(), 类: (typeof e.className === 'string' ? e.className : '') }));
  const clickChip = label => {
    const leaf = [...document.querySelectorAll('*')].find(e => e.children.length === 0 && (e.textContent||'').trim().startsWith(label));
    if (!leaf) return false;
    const btn = leaf.closest('button,[role=button],.chip,a,div');
    (btn || leaf).click();
    return true;
  };
  const rep = { 起始名字: names(), 起始种类: [...new Set(kinds())], 起始chip: chipState() };
  rep.点了特效 = clickChip('特效');
  await sleep(1800);
  rep.特效后名字 = names(); rep.特效后种类 = [...new Set(kinds())]; rep.特效后chip = chipState();
  rep.名字集合变了 = rep.特效后名字.join('|') !== rep.起始名字.join('|');
  rep.种类集合变了 = rep.特效后种类.join('|') !== rep.起始种类.join('|');
  rep.点了全部 = clickChip('全部');
  await sleep(1800);
  rep.回全部名字 = names(); rep.回全部种类 = [...new Set(kinds())];
  rep.回到起始 = rep.回全部名字.join('|') === rep.起始名字.join('|');
  return rep;
})()`;
const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
console.log(JSON.stringify(r.result && r.result.value ? r.result.value : r, null, 1));
ws.close();
