// 整组每件网格的分层计划体检：多件组合里只要有一件取不到贴图，画面上就是一块灰，
// 而之前的抽样只看每组第一件。这里逐件跑，报「有件失败 / 有件没颜色 / 有件缺层」的组。
//
// 用法：node .scratch/dyn/audit_parts_20261027.mjs [每组组数] [每类条数]
const GROUPS = Number(process.argv[2] || 6);
const PER = Number(process.argv[3] || 5);
const QUERIES = ["w1351_monster", "w1351_boss", "w1351_npc", "w1351_pets", "w1351_zuoqi", "w1351_nan_s_yifu"];
const fs = await import("node:fs");

const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((p) => p.type === "page");
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
async function evalJs(expr) {
  const r = await call("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 200));
  return r.result?.result?.value;
}

const rows = [];
for (const q of QUERIES) {
  const groups = await evalJs(
    `import('/api.js').then(m=>m.listGroups({query:${JSON.stringify(q)},limit:${PER}})).then(r=>(r.items||[]).map(x=>({gid:x.gid,name:x.name})))`,
  );
  for (const g of (groups || []).slice(0, GROUPS)) {
    const rec = await evalJs(
      `import('/api.js').then(async m=>{
         const i=await m.assetInspect(${g.gid});
         const ms=(i.members||[]).filter(x=>/\\.mesh$/i.test(x.name||'')).map(x=>({name:x.name,hash:x.hash||null}));
         const out=[];
         for(const mm of ms){
           try{
             const p=await m.meshTexturePlan(${g.gid}, mm.name, mm.hash);
             out.push({mesh:mm.name,layers:(p.layers||[]).length,aligned:!!(p.evidence&&p.evidence.aligned),note:(p.note||'').slice(0,60)});
           }catch(e){ out.push({mesh:mm.name,err:String(e).slice(0,80)}); }
         }
         return {gid:${g.gid},name:${JSON.stringify(g.name)},meshes:out};
       })`,
    );
    rows.push(rec);
    const bad = rec.meshes.filter((x) => x.err);
    const nocolor = rec.meshes.filter((x) => !x.err && !x.layers);
    console.error(`  ${rec.gid} ${rec.name}：${rec.meshes.length} 件，失败 ${bad.length}，无颜色 ${nocolor.length}`);
  }
}

const totals = { groups: rows.length, meshes: 0, err: 0, nocolor: 0, unaligned: 0, ok: 0 };
const badGroups = [];
for (const r of rows) {
  let g = { err: 0, nocolor: 0 };
  for (const m of r.meshes) {
    totals.meshes++;
    if (m.err) {
      totals.err++;
      g.err++;
    } else if (!m.layers) {
      totals.nocolor++;
      g.nocolor++;
    } else if (!m.aligned) totals.unaligned++;
    else totals.ok++;
  }
  if (g.err || g.nocolor) badGroups.push({ gid: r.gid, name: r.name, ...g });
}
console.log(JSON.stringify({ totals, badGroups }, null, 1));
fs.writeFileSync(".scratch/dyn/audit_parts_20261027.json", JSON.stringify({ totals, badGroups, rows }, null, 1));
ws.close();