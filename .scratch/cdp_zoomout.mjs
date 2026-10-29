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
const c = await ev(`(() => { const list=[...document.querySelectorAll("canvas")].map(cv=>{const r=cv.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};}); list.sort((a,b)=>b.w*b.h-a.w*a.h); return list[0]; })()`);
console.log("最大画布:", JSON.stringify(c));
const y = c.y + c.h/2, x = c.x + c.w/2;
for (let k=0;k<6;k++) { await call("Input.dispatchMouseEvent", { type: "mouseWheel", x, y, deltaX: 0, deltaY: 480 }); await wait(120); }
await wait(1500);
const shot = await call("Page.captureScreenshot", { format: "png" });
writeFileSync("D:/TLGL/.scratch/min3_behit01_f13_zoomout.png", Buffer.from(shot.result.data, "base64"));
console.log("图已存");
ws.close();
