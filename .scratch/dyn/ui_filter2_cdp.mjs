// 上一版点「特效 6,473」看不出内容变化——因为「全部」状态下列表前 300 行本来就全是特效（按组排序）。
// 换成点一个**条数小于 300** 的类别（界面资源 22 / 玩家角色 204），滤完行数必然掉，才是干净的判据。
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
  const kinds = () => [...new Set([...document.querySelectorAll('.row-item')].map(e => {
    const s = e.querySelector('.s,.c'); return (s ? s.textContent : '').trim().split(' ')[0]; }))];
  const names = () => [...document.querySelectorAll('.row-item .t')].slice(0, 4).map(e => (e.textContent||'').trim().slice(0, 26));
  const click = label => {
    const leaf = [...document.querySelectorAll('.chip,button,[role=button]')]
      .find(e => (e.textContent||'').trim().startsWith(label));
    if (!leaf) return false;
    leaf.click();
    return true;
  };
  const rep = { 起始: { 行数: rows(), 种类: kinds(), 前4: names() } };
  for (const lab of ['界面资源', '玩家角色']) {
    const ok = click(lab);
    await sleep(2000);
    rep[lab] = { 点到: ok, 行数: rows(), 种类: kinds(), 前4: names() };
  }
  click('全部');
  await sleep(2000);
  rep.回全部 = { 行数: rows(), 种类: kinds() };
  return rep;
})()`;
const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
const v = r.result && r.result.value ? r.result.value : r;
console.log(JSON.stringify(v, null, 1));
ws.close();
