const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true }); if (r?.exceptionDetails) return "抛错:" + r.exceptionDetails.text; return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
for (let i = 0; i < 10; i++) {
  console.log(`第 ${i * 5} 秒 · 行数 ${await ev(`document.querySelectorAll(".row-item").length`)} · #rows 子 ${await ev(`(document.getElementById("rows")||{children:{length:-1}}).children.length`)} · 底部计数 ${await ev(`(() => { const t=[...document.querySelectorAll("p,div,span,em")].map(e=>e.textContent).filter(x=>x&&/条资产/.test(x)&&x.length<50)[0]; return t? t.trim().replace(/\s+/g," ") : "无"; })()`)}`);
  await wait(5000);
}
ws.close();
