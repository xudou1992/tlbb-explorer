// 材质页真窗口验法：筹码、槽位表、缺项计数、换一份材质
import { writeFileSync } from "node:fs";
const STEMS = ["gbnan_long", "butterfly_lf001", "hongbaoshi_s001", "w1351_monster_xiyuqiezei"];
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const Q = (s) => JSON.stringify(s);
await wait(1500);
// 空查一次把第一页叫出来（首屏要等一次 input 才列东西）
await ev(`(() => { const q=document.getElementById("q"); q.value=""; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
// 先等列表真长出来（冷启动时行数一直是 0，搜什么都白搜）
for (let i = 0; i < 60; i++) { if (await ev(`document.querySelectorAll(".row-item").length`) > 0) break; await wait(1000); }
console.log("列表就绪，行数：", await ev(`document.querySelectorAll(".row-item").length`));
for (const stem of STEMS) {
  await ev(`(() => { const q=document.getElementById("q"); q.value=${Q(stem)}; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  await wait(6000);
  const hit = await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes(${Q(stem)})); if(!r) return "没找到行"; r.click(); return "点了"; })()`);
  if (hit !== "点了") { console.log(stem, hit); continue; }
  await wait(2500);
  await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="material"]'); t&&t.click(); return 1; })()`);
  await wait(5000);
  const rows = await ev(`document.querySelectorAll("#mtlTable tbody tr").length`);
  console.log(`${stem} → 槽位行数 ${rows}`);
  if (!rows) { console.log("  摘要：", await ev(`document.getElementById("mtlSum").textContent`)); continue; }
  console.log("  摘要：", await ev(`document.getElementById("mtlSum").textContent`));
  console.log("  筹码：", await ev(`[...document.querySelectorAll("#mtlPick button.chip")].map(b=>b.textContent+(b.classList.contains("on")?"[选中]":"")).join(" ")`));
  console.log("  前 4 行：", await ev(`[...document.querySelectorAll("#mtlTable tbody tr")].slice(0,4).map(r=>r.children[0].textContent+"|"+r.children[1].textContent.slice(0,30)+"|"+r.children[2].textContent.slice(0,34)).join(" ⏎ ")`));
  console.log("  写缺的行数：", await ev(`[...document.querySelectorAll("#mtlTable tbody tr")].filter(r=>r.children[2].textContent.trim()==="缺").length`));
  console.log("  未解项：", await ev(`[...document.querySelectorAll("#mtlMissing li")].map(li=>li.textContent.slice(0,52)).join(" ／ ")`));
  await ev(`(() => { const b=[...document.querySelectorAll("#mtlPick button.chip")][1]; if(b) b.click(); return b?1:0; })()`);
  await wait(4000);
  console.log("  换份后：", await ev(`document.getElementById("mtlSum").textContent.slice(0,60)`));
  await send("Emulation.setDeviceMetricsOverride", { width: 1500, height: 950, deviceScaleFactor: 1, mobile: false });
  await ev(`(() => { const el=document.getElementById("mtlSum"); if(el) el.scrollIntoView({block:"start"}); return 1; })()`);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  if (shot?.data) { writeFileSync("D:/TLGL/.scratch/ui_check/mtl_page.png", Buffer.from(shot.data, "base64")); console.log("  截图写了 mtl_page.png"); }
  break;
}
ws.close();
