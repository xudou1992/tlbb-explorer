const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 40; i++) {
  const n = await ev(`document.querySelectorAll(".row-item").length`);
  const msg = await ev(`(() => { const r=document.querySelector(".rows,#rows"); const t=r? r.textContent.trim().slice(0,60):"无容器"; return t; })()`);
  console.log(`第 ${i * 6} 秒：行数 ${n} · 容器文本「${msg}」`);
  if (n > 0) break;
  await wait(6000);
}
ws.close();
