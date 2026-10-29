// 把特效页铺好（默认那份），停在画面上等 PrintWindow 截图
const BASE = "http://127.0.0.1:9222";
const STEMS = ["w1351_other_jh_hwpx", "w1351_scene_gmd_yjsm04"];
const list = await (await fetch(`${BASE}/json/list`)).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const Q = (s) => JSON.stringify(s);
await wait(1500);
for (const stem of STEMS) {
  await ev(`(() => { const q=document.getElementById("q"); q.value=${Q(stem)}; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  await wait(2500);
  const hit = await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes(${Q(stem)})); if(!r) return "没点到"; r.click(); return "点了"; })()`);
  if (hit !== "点了") continue;
  await wait(2500);
  await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="effect"]'); t&&t.click(); return 1; })()`);
  await wait(4000);
  const rows = await ev(`document.querySelectorAll("#fxTable tbody tr").length`);
  if (rows > 0) { console.log("停在这组的特效页：", stem, "行数", rows); break; }
}
console.log("摘要：", await ev(`document.getElementById("fxSum").textContent`));
ws.close();
