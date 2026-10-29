import fs from "node:fs";
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) pending.get(m.id)(m); };
const call = (m, p) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
const ev = async x => (await call("Runtime.evaluate", { expression: x, returnByValue: true, awaitPromise: true })).result?.result?.value;
const sample = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const r = await ev(`(async()=>{const inv=window.__TAURI__.core.invoke;const out=[];for(const s of ${JSON.stringify(sample)}){try{const a=await inv('asset_inspect',{gid:s.gid});out.push({gid:s.gid,stem:s.stem,auto:a.autoMesh?a.autoMesh.name:null,hash:a.autoMesh?a.autoMesh.hash:null})}catch(e){out.push({gid:s.gid,stem:s.stem,auto:'ERR'})}}return JSON.stringify(out)})()`);
const out = JSON.parse(r);
let ok = 0, missing = [], bad = [];
for (const x of out) {
  if (!x.auto) { missing.push(x); continue; }
  if (x.auto.replace(/\.mesh$/i, "").startsWith(x.stem)) ok++; else bad.push(x);
}
console.log(`抽样 ${out.length}：autoMesh 属本组 ${ok} · 没有 ${missing.length} · 不符 ${bad.length}`);
for (const m of missing.slice(0,5)) console.log("  没有", JSON.stringify(m));
ws.close();
