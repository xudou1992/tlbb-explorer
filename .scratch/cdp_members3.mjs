const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + r.exceptionDetails.text; return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
for (const t of ["relations", "files"]) {
  await ev(`(() => { const b=document.querySelector('#dTabs .tab[data-tab="${t}"]'); b&&b.click(); return 1; })()`);
  await wait(3500);
  console.log(`${t}：tbody 行 ${await ev(`document.querySelectorAll('[data-pane="${t}"] table tbody tr').length`)} · 列表项 ${await ev(`document.querySelectorAll('[data-pane="${t}"] li, [data-pane="${t}"] .mrow').length`)} · 文本 ${await ev(`(document.querySelector('[data-pane="${t}"]')||{innerText:""}).innerText.replace(/\n+/g," § ").slice(0,110)`)}`);
}
ws.close();
