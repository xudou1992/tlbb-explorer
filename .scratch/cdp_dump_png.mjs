import fs from "node:fs";

const [hash, out] = process.argv.slice(2);
if (!hash || !out) {
  console.error("usage: node cdp_dump_png.mjs <hash> <out.png>");
  process.exit(2);
}
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((p) => p.type === "page");
if (!page) throw new Error("没有页面");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    pending.get(m.id)(m);
    pending.delete(m.id);
  }
};
await new Promise((r) => (ws.onopen = r));
const call = (method, params) =>
  new Promise((res) => {
    const i = ++id;
    pending.set(i, res);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
const expr = `window.__TAURI__.core.invoke('candidate_png',{hash:${JSON.stringify(hash)}})`;
const r = await call("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
const url = r.result?.result?.value;
if (!url || !url.startsWith("data:image/png;base64,")) throw new Error("不是 png: " + String(url).slice(0, 80));
fs.writeFileSync(out, Buffer.from(url.slice("data:image/png;base64,".length), "base64"));
console.log(out);
ws.close();
