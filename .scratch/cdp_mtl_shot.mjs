import { writeFileSync } from "node:fs";
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + r.exceptionDetails.text; return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
await send("Emulation.setDeviceMetricsOverride", { width: 1500, height: 950, deviceScaleFactor: 1, mobile: false });
await wait(1200);
// 先把主视图切回「资产」，再搜、再点行、再开材质页
await ev(`(() => { const b=[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="资产"); if(b) b.click(); return b?1:0; })()`);
await wait(4000);
await ev(`(() => { const q=document.getElementById("q"); q.value="zq_qszd"; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(6000);
console.log("行数：", await ev(`document.querySelectorAll(".row-item").length`));
console.log(await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes("zq_qszd")); if(!r) return "没找到行"; r.click(); return "点了"; })()`));
await wait(4000);
await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="material"]'); t&&t.click(); return 1; })()`);
await wait(5000);
await ev(`(() => { const el=document.getElementById("mtlSum"); if(el) el.scrollIntoView({block:"start"}); return 1; })()`);
console.log("材质表行数：", await ev(`document.querySelectorAll("#mtlTable tbody tr").length`));
console.log("表内容：", await ev(`[...document.querySelectorAll("#mtlTable tbody tr")].map(r=>[...r.children].map(c=>c.textContent).join("|")).join(" ~~ ")`));
console.log("其他名字：", await ev(`(() => { const p=[...document.querySelectorAll("#mtlTable p")].map(x=>x.textContent)[0]; return p? p.slice(0,120) : "无"; })()`));
console.log("摘要：", await ev(`document.getElementById("mtlSum").textContent`));
const shot = await send("Page.captureScreenshot", { format: "png" });
if (shot?.data) { writeFileSync("D:/TLGL/.scratch/ui_check/mtl_view.png", Buffer.from(shot.data, "base64")); console.log("截图写了 mtl_view.png"); }
ws.close();
