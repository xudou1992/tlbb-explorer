// 贴图候选区「多份榜」渲染检查：真浏览器里跑 textureState.texBlock，截图 + 断言 DOM。
// 用法：先起 http://127.0.0.1:8765/ （根 = D:/TLGL）和带 --remote-debugging-port=9227 的 Chrome。
const CDP = process.env.CDP_PORT ?? '9227';
const PAGE = 'http://127.0.0.1:8765/.scratch/tex_ui/view.html';
const OUT = 'D:/TLGL/.scratch/tex_ui';

import { writeFileSync, mkdirSync } from 'node:fs';
mkdirSync(`${OUT}/shots`, { recursive: true });

const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
let page = list.find((t) => t.type === 'page' && t.url.includes('tex_ui'));
if (!page) page = await (await fetch(`http://127.0.0.1:${CDP}/json/new?${encodeURIComponent(PAGE)}`)).json();
const target = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
page = target.find((t) => t.type === 'page' && t.webSocketDebuggerUrl && t.url.includes('tex_ui')) ?? page;

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

await send('Page.enable', {});
await send('Page.navigate', { url: PAGE });
await new Promise((r) => setTimeout(r, 1800));

const ev = async (expr) => (await send('Runtime.evaluate', { expression: expr, returnByValue: true })).result?.value;
let ready = null;
for (let i = 0; i < 20 && !ready; i++) {
  ready = await ev('JSON.stringify(window.__ready ?? null)');
  if (!ready) await new Promise((r) => setTimeout(r, 400));
}
const info = ready ? JSON.parse(ready) : null;
const note = await ev('document.getElementById("texNote").textContent');
const heads = await ev('Array.from(document.querySelectorAll("#texCand .tex-group p")).map(p=>p.textContent).join(" | ")');
const overflow = await ev('JSON.stringify((()=>{const r=document.getElementById("secTex").getBoundingClientRect();' +
  'const bad=[...document.querySelectorAll("#texCand .tex-cand")].filter(c=>c.getBoundingClientRect().right>r.right+1).length;' +
  `return {cards:document.querySelectorAll('#texCand .tex-cand').length, overflow:bad, pageW:document.documentElement.scrollWidth, winW:innerWidth};})())`);
const shot = await send('Page.captureScreenshot', { format: 'png' });
writeFileSync(`${OUT}/shots/tex_multi.png`, Buffer.from(shot.data, 'base64'));
console.log('DOM 断言：', JSON.stringify(info));
console.log('说明行：', note);
console.log('每份榜的抬头：', heads);
console.log('溢出检查：', overflow);
console.log('截图：', `${OUT}/shots/tex_multi.png`);
ws.close();
