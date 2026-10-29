// 用真实鼠标拖动帧游标，看后端有没有收到 anim_pose 请求（区分「界面坏了」还是「我造的假事件没走通」）
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) pending.get(m.id)(m); };
const call = (method, params) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async e => {
  const r = await call("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true });
  return r.result?.result?.value;
};
// 1) 装个 IPC 记录器
await ev(`(()=>{const inv=window.__TAURI__.core.invoke;window.__calls=[];window.__TAURI__.core.invoke=(c,a)=>{if(String(c).includes('pose'))window.__calls.push(String(c)+' f='+(a&&a.frame));return inv(c,a)};return 1})()`);
// 2) 滚进视野，量位置
await ev(`document.getElementById('animFrame').scrollIntoView({block:'center'})`);
await new Promise(r => setTimeout(r, 800));
const box = JSON.parse(await ev(`(()=>{const r=document.getElementById('animFrame').getBoundingClientRect();return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height,v:document.getElementById('animFrame').value})})()`));
console.log("游标位置", box);
const y = box.y + box.h / 2;
const at = frac => box.x + box.w * frac;
const send = (type, x) => call("Input.dispatchMouseEvent", { type, x, y, button: "left", clickCount: 1 });
// 3) 真拖：按下 20% → 拖到 80% → 抬起
await send("mousePressed", at(0.2));
await send("mouseMoved", at(0.5));
await send("mouseMoved", at(0.8));
await send("mouseReleased", at(0.8));
await new Promise(r => setTimeout(r, 2500));
const v1 = await ev(`document.getElementById('animFrame').value`);
const c1 = await ev(`JSON.stringify(window.__calls)`);
// 4) 再拖回 10%
await send("mousePressed", at(0.1));
await send("mouseReleased", at(0.1));
await new Promise(r => setTimeout(r, 2500));
const v2 = await ev(`document.getElementById('animFrame').value`);
const c2 = await ev(`JSON.stringify(window.__calls)`);
console.log("拖到 80% 后滑杆值:", v1, "  请求:", c1);
console.log("拖到 10% 后滑杆值:", v2, "  请求:", c2);
ws.close();
