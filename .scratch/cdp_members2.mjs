const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + r.exceptionDetails.text; return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
console.log("标签的 data-tab：", await ev(`[...document.querySelectorAll("#dTabs .tab")].map(t=>t.dataset.tab+"="+t.textContent.trim().replace(/\s+/g," ")).join(" | ")`));
for (const t of ["resource", "files"]) {
  await ev(`(() => { const b=document.querySelector('#dTabs .tab[data-tab="${t}"]'); b&&b.click(); return 1; })()`);
  await wait(2500);
  console.log(`${t} 面板：行数 ${await ev(`(document.querySelector('[data-pane="${t}"]')||{querySelectorAll:()=>[]}).querySelectorAll("tbody tr, .mrow, li").length`)} · 说明 ${await ev(`(() => { const p=document.querySelector('[data-pane="${t}"]'); if(!p) return "无面板"; return [...p.querySelectorAll("p,.dim,small")].map(e=>e.textContent.trim()).filter(x=>x).slice(0,2).join(" ⏎ ").slice(0,120); })()`)}`);
}
ws.close();
