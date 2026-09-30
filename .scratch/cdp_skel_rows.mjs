// 从真窗口里把骨架页的 36 个节点（名字 + 绑定位移）抠出来，交给 python 做前缀链假设检验
import { writeFileSync } from "node:fs";
const STEMS = ["w1351_monster_xiyuqiezei"];
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const Q = (s) => JSON.stringify(s);
for (const stem of STEMS) {
  await ev(`(() => { const q=document.getElementById("q"); q.value=${Q(stem)}; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  await wait(2500);
  const clicked = await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes(${Q(stem)})); if(!r) return "没找到行"; r.click(); return "点了"; })()`);
  console.log(stem, clicked);
  await wait(2500);
  await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="skeleton"]'); t&&t.click(); return 1; })()`);
  await wait(4000);
  const rows = await ev(`JSON.stringify([...document.querySelectorAll("#skelTable tbody tr")].map(r=>[...r.children].map(c=>c.textContent.trim())))`);
  console.log("骨架表行数：", JSON.parse(rows).length);
  writeFileSync("D:/TLGL/.scratch/skel_rows.json", rows);
  console.log("摘要：", await ev(`document.getElementById("skelSum").textContent`));
}
ws.close();
