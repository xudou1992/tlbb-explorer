const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
for (const w of ["xiyuqiezei", "w1351_nan_", "w1351_other_jh_hwpx"]) {
  await ev(`(() => { const q=document.getElementById("q"); q.value=${JSON.stringify(w)}; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  await wait(4500);
  console.log(`「${w}」行数 ${await ev(`document.querySelectorAll(".row-item").length`)} · 计数条 ${await ev(`[...document.querySelectorAll("button,span,p,div")].map(e=>e.textContent.trim()).filter(t=>/^\d[\d,]* 条/.test(t)&&t.length<40)[0]||"无"`)}`);
}
console.log("未命名按钮文案：", await ev(`(() => { const b=[...document.querySelectorAll("button")].find(x=>/未命名/.test(x.textContent)); return b? b.textContent.trim() : "无"; })()`));
ws.close();
