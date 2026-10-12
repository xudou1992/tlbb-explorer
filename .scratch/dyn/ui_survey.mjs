// 先看真实 DOM 长什么样，再决定点什么——上一版探针按 .card / img 猜，结果点到了空状态。
const targets = await (await fetch('http://127.0.0.1:9222/json')).json();
const page = targets.find(t => t.type === 'page' && (t.url || '').startsWith('http://tauri.localhost'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0;
const pend = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
const send = (method, params = {}) => new Promise(res => { const k = ++id; pend.set(k, res); ws.send(JSON.stringify({ id: k, method, params })); });
const expr = `
(() => {
  const cls = e => (typeof e.className === 'string' ? e.className : (e.getAttribute && e.getAttribute('class')) || '');
  const groups = {};
  for (const e of document.querySelectorAll('*')) {
    const c = cls(e).trim();
    if (!c || c.length > 40) continue;
    for (const one of c.split(/\\s+/)) {
      if (!one || one.length > 26) continue;
      const n = document.querySelectorAll('.' + CSS.escape(one)).length;
      if (n >= 6) groups[one] = (groups[one] || 0) + n;
    }
  }
  const uniq = {};
  for (const e of document.querySelectorAll('*')) {
    for (const one of cls(e).split(/\\s+/)) {
      if (!one) continue;
      const n = document.querySelectorAll('.' + CSS.escape(one)).length;
      if (n >= 6 && !uniq[one]) uniq[one] = n;
    }
  }
  const counts = [...document.querySelectorAll('*')]
    .filter(e => e.children.length === 0 && /条|个|资产|结果|显示/.test(e.textContent || '') && (e.textContent || '').length < 70)
    .map(e => cls(e) + ' :: ' + e.textContent.trim());
  const canvas = document.querySelectorAll('canvas').length;
  const bg = [...document.querySelectorAll('*')].filter(e => /url\\(/.test(getComputedStyle(e).backgroundImage || '')).length;
  return {
    重复类名: Object.entries(uniq).sort((a, b) => b[1] - a[1]).slice(0, 14),
    计数文案: [...new Set(counts)].slice(0, 10),
    canvas数: canvas,
    背景图元素数: bg,
    标题: document.title,
    主体子树: [...document.body.children].map(e => e.tagName + '.' + cls(e)).slice(0, 8),
  };
})()
`;
const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
console.log(JSON.stringify(r.result && r.result.value ? r.result.value : r, null, 1));
ws.close();
