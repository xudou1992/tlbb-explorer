import { writeFileSync } from "node:fs";
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise((r) => ws.onopen = r);
const call = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const ev = async (e) => { const r = await call("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); return r?.result?.result?.value; };
const until = async (js, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await ev(`(() => { try { return Boolean(${js}); } catch (e) { return false; } })()`)) return true; await wait(800); } return false; };
await wait(2000);
await ev(`(() => { const q=document.getElementById("q"); q.value="xinmurongfu"; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
console.log("搜到：", await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes("xinmurongfu"))`, 40000));
await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes("xinmurongfu")); r&&r.click(); return 1; })()`);
await wait(5000);
await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="animation"]'); t&&t.click(); return 1; })()`);
console.log("动作区就绪：", await until(`document.getElementById("animSum") && document.getElementById("animSum").textContent.length>0`, 30000));
console.log("摘要：", await ev(`document.getElementById("animSum").textContent`));
await ev(`(() => { const s=document.getElementById("animFrame"); s&&s.scrollIntoView({block:"center"}); return 1; })()`);
await wait(1200);
const box = await ev(`(() => { const s=document.getElementById("animFrame"); if (!s) return null; const r=s.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height,min:+s.min,max:+s.max,val:+s.value}; })()`);
console.log("滑杆：", JSON.stringify(box));
if (box) {
  const y = box.y + box.h / 2;
  const startX = box.x + (box.val - box.min) / (box.max - box.min) * box.w;
  const targetX = box.x + (13 - box.min) / (box.max - box.min) * box.w;
  await call("Input.dispatchMouseEvent", { type: "mousePressed", x: startX, y, button: "left", clickCount: 1 });
  for (let k = 1; k <= 8; k++) { await call("Input.dispatchMouseEvent", { type: "mouseMoved", x: startX + (targetX - startX) * k / 8, y, button: "left" }); await wait(60); }
  await call("Input.dispatchMouseEvent", { type: "mouseReleased", x: targetX, y, button: "left", clickCount: 1 });
  await wait(2500);
  console.log("帧号：", await ev(`document.getElementById("animFrame").value`), "摘要尾：", await ev(`document.getElementById("animSum").textContent.slice(0,80)`));
}
const shot = await call("Page.captureScreenshot", { format: "png" });
if (shot?.result?.data) { writeFileSync("D:/TLGL/.scratch/min3_regress_old.png", Buffer.from(shot.result.data, "base64")); console.log("截图已存"); } else console.log("截图失败", JSON.stringify(shot).slice(0,200));
ws.close();
