const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
for (const stem of ["w1351_fire_z010", "w1351_ring_c022", "w1351_model_h016", "w1351_smeh_shandongkou"]) {
  await ev(`(() => { const q=document.getElementById("q"); q.value=${JSON.stringify(stem)}; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  await wait(4000);
  const n = await ev(`document.querySelectorAll(".row-item").length`);
  const first = await ev(`[...document.querySelectorAll(".row-item")].slice(0,3).map(r=>r.textContent.replace(/\s+/g," ").slice(0,44)).join(" ⏎ ")`);
  console.log(`「${stem}」行数 ${n} · ${first}`);
}
ws.close();
