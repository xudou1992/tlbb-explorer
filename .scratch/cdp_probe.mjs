const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (ev) => { const x = JSON.parse(ev.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); return r?.result?.value ?? JSON.stringify(r).slice(0, 300); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
console.log(await ev(`JSON.stringify({
  views: [...document.querySelectorAll("#views button, .views button, header button")].map(b=>b.textContent.trim().slice(0,6)+(b.className.includes("on")?"*":"")).join(","),
  rows: document.querySelectorAll(".row-item").length,
  listIds: [...document.querySelectorAll("[id]")].map(n=>n.id).filter(i=>/list|rows|cards|items/i.test(i)).join(",")
})`));
console.log(await ev(`(() => { const b=[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="资产"); b&&b.click(); return b? b.className : "none"; })()`));
await wait(4000);
console.log(await ev(`JSON.stringify({rows: document.querySelectorAll(".row-item").length, anyRowClass: [...new Set([...document.querySelectorAll("[class]")].map(n=>n.className).filter(c=>/row|item/i.test(String(c))))].slice(0,6).join("|")})`));
ws.close();
