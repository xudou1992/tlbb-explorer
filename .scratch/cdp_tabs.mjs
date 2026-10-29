const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0; const pending = new Map(); const errors = [];
ws.onmessage = (e) => { const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === "Runtime.exceptionThrown") errors.push(m.params?.exceptionDetails?.text || "exception");
  if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push((m.params.args||[]).map(a=>a.value||a.description).join(" ").slice(0,120));
};
await new Promise(r => ws.onopen = r);
const call = (method, params = {}) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const wait = ms => new Promise(r => setTimeout(r, ms));
await call("Runtime.enable");
const ev = async (expr) => (await call("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;
const tabs = await ev(`[...document.querySelectorAll("#dTabs .tab")].map(t=>t.dataset.tab)`);
for (const t of tabs) {
  await ev(`(() => { const b=document.querySelector('#dTabs .tab[data-tab="${t}"]'); b&&b.click(); return 1; })()`);
  await wait(1200);
  const info = await ev(`(() => { const p=document.querySelector('#dBody')||document.querySelector('.detail')||document.body; const txt=(p.innerText||"").replace(/\s+/g," "); return {len: txt.length, head: txt.slice(0,80)}; })()`);
  console.log(t, JSON.stringify(info));
}
console.log("errors:", errors.length ? errors.slice(0,5) : "无");
ws.close();
