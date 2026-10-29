const expr = process.argv[2] || "document.title";
const list = await (await fetch("http://127.0.0.1:9223/json/list")).json();
const page = list.find(p => p.type === "page");
if (!page) { console.error("没有页面"); process.exit(2); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
};
await new Promise(r => ws.onopen = r);
function call(method, params) {
  return new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
}
const r = await call("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
const v = r.result?.result?.value;
console.log(typeof v === "string" ? v : JSON.stringify(v, null, 2));
ws.close();
