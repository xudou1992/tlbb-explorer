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
const r = await ev(`(async()=>{const inv=window.__TAURI__.core.invoke;const out=[];for(const s of ${JSON.stringify(sample)}){try{const o=await inv('group_mesh_outline',{gid:s.gid});out.push({gid:s.gid,stem:s.stem,got:o?String(o.path).split('/').pop():null,face:o?o.face:null,n:o?o.vertexCount:0})}catch(e){out.push({gid:s.gid,stem:s.stem,got:'ERR'})}}return JSON.stringify(out)})()`);
const out = JSON.parse(r);
let ok = 0, bad = [];
for (const x of out) {
  const same = x.got && x.got.replace(/\.mesh$/i, "").startsWith(x.stem);
  if (same) ok++; else bad.push(x);
}
console.log(`抽样 ${out.length} 组：属于本组 ${ok} · 不符 ${bad.length}`);
for (const b of bad.slice(0, 6)) console.log("  不符", JSON.stringify(b));
ws.close();
