// 定性用：点一个会滤空的类别，读**列表容器与空状态**到底写了什么，
// 以及 chip 上带的属性（看它把什么值当筛选条件传出去）。
const t = await (await fetch('http://127.0.0.1:9222/json')).json();
const page = t.find(x => x.type === 'page' && (x.url || '').startsWith('http://tauri.localhost'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0; const pend = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
const send = (met, params = {}) => new Promise(r => { const k = ++id; pend.set(k, r); ws.send(JSON.stringify({ id: k, method: met, params })); });
const expr = `(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const chips = [...document.querySelectorAll('.chip')].map(e => ({
    文: (e.textContent || '').trim().slice(0, 14),
    属性: [...e.attributes].map(a => a.name + '=' + a.value).filter(s => s !== 'class=chip').join(' ')
  }));
  const target = [...document.querySelectorAll('.chip')].find(e => (e.textContent || '').trim().startsWith('界面资源'));
  const before = document.body.innerText.length;
  if (target) target.click();
  await sleep(2500);
  const list = document.querySelector('.rows,.list,#rows,.browse,.result') || document.body;
  const empty = [...document.querySelectorAll('*')].filter(e => e.children.length === 0
    && /没有|无匹配|未找到|空|打开一个|条结果|显示/.test((e.textContent || '').trim())
    && (e.textContent || '').trim().length < 60).map(e => (e.textContent || '').trim());
  const after = { 行数: document.querySelectorAll('.row-item').length, 空状态文案: [...new Set(empty)].slice(0, 6),
    列表容器文本头: (list.innerText || '').slice(0, 160), 页面字数变化: document.body.innerText.length - before };
  const all = [...document.querySelectorAll('.chip')].find(e => (e.textContent || '').trim().startsWith('全部'));
  if (all) all.click();
  await sleep(1500);
  return { chip清单: chips.slice(0, 10), 滤空后: after, 回全部行数: document.querySelectorAll('.row-item').length };
})()`;
const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
console.log(JSON.stringify(r.result && r.result.value ? r.result.value : r, null, 1));
ws.close();
