// 分清两种可能：poseGate 卡在「在途」，还是 poseCursor 的守卫直接早退。
// 做法：装记录器 → 切走再切回动作页（重新取数）→ 真拖游标 → 看各阶段发了哪些请求。
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) pending.get(m.id)(m); };
const call = (method, params) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async e => (await call("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
const nap = ms => new Promise(r => setTimeout(r, ms));

await ev(`(()=>{const inv=window.__TAURI__.core.invoke;window.__calls=[];window.__TAURI__.core.invoke=(c,a)=>{const s=String(c);if(s.includes('pose')||s.includes('animation'))window.__calls.push(s+' f='+(a&&a.frame!==undefined?a.frame:'-'));return inv(c,a)};return 1})()`);
await ev(`document.querySelector('button.tab[data-tab=preview]').click()`);
await nap(1200);
await ev(`document.querySelector('button.tab[data-tab=animation]').click()`);
await nap(4000);
const afterOpen = JSON.parse(await ev(`JSON.stringify(window.__calls)`));
const box = JSON.parse(await ev(`(()=>{const e=document.getElementById('animFrame');if(!e)return '{}';const r=e.getBoundingClientRect();return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height,v:e.value})})()`));
console.log("切回动作页后的请求：", afterOpen, " 游标:", box.v);
if (box.w) {
  const y = box.y + box.h / 2;
  const at = f => box.x + box.w * f;
  await call("Input.dispatchMouseEvent", { type: "mousePressed", x: at(0.15), y, button: "left", clickCount: 1 });
  await call("Input.dispatchMouseEvent", { type: "mouseReleased", x: at(0.15), y, button: "left", clickCount: 1 });
  await nap(2500);
  const v1 = await ev(`document.getElementById('animFrame').value`);
  const c1 = JSON.parse(await ev(`JSON.stringify(window.__calls)`));
  console.log("真拖到 15% → 滑杆", v1, " 请求数", c1.length, c1.slice(afterOpen.length));
  // 播放一下再看会不会发请求
  await ev(`document.getElementById('animPlay').click()`);
  await nap(2500);
  await ev(`document.getElementById('animPlay').click()`);
  const c2 = JSON.parse(await ev(`JSON.stringify(window.__calls)`));
  console.log("播放 2.5 秒后请求数", c2.length, "（拖完是", c1.length, "）");
}
ws.close();
