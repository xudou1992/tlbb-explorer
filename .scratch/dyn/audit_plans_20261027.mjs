// 分层计划横向体检：抽样若干资产组，逐只网格要一次 mesh_texture_plan，
// 把「解不出 / 没有颜色图 / 对齐未验证 / 有层但没贴图」分类计数，落盘 JSON。
//
// 用法：node .scratch/dyn/audit_plans_20261027.mjs [每组条数] [品类用逗号分隔]
// 品类走 listGroups 的 query：默认抽样这几类有网格的资产。
const PER = Number(process.argv[2] || 12);
const QUERIES = (process.argv[3] || "w1351_monster,w1351_npc,w1351_pets,w1351_zuoqi,w1351_nan_s_yifu,w1351_boss,w1351_an_model")
  .split(",")
  .filter(Boolean);
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
  const r = await call("Runtime.evaluate", {
    expression: expr,
    returnByValue: true,
    awaitPromise: true,
  });
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 200));
  return r.result?.result?.value;
}

const out = [];
let scanned = 0;
for (const q of QUERIES) {
  const items = await evalJs(
    `import('/api.js').then(m=>m.listGroups({query:${JSON.stringify(q)},limit:${PER}})).then(r=>(r.items||[]).map(x=>({gid:x.gid,name:x.name})))`,
  );
  if (!items || !items.length) {
    console.error(`  [${q}] 没有条目`);
    continue;
  }
  for (const g of items) {
    const rec = await evalJs(
      `import('/api.js').then(async m=>{
         const i=await m.assetInspect(${g.gid});
         const meshes=(i.members||[]).filter(x=>/\\.mesh$/i.test(x.name||'')).map(x=>({name:x.name,hash:x.hash||null}));
         if(!meshes.length) return {gid:${g.gid},name:${JSON.stringify(g.name)},mesh:null};
         const m0=meshes[0];
         try{
           const p=await m.meshTexturePlan(${g.gid}, m0.name, m0.hash);
           const noTex=(p.layers||[]).filter(l=>!l.color||!l.color.png).length;
           return {gid:${g.gid},name:${JSON.stringify(g.name)},mesh:m0.name,layers:(p.layers||[]).length,
                   fx:p.effectLayers||0,op:p.opaqueLayers||0,aligned:!!(p.evidence&&p.evidence.aligned),
                   ev:p.evidence||null,noTex,note:(p.note||'').slice(0,90)};
         }catch(e){
           return {gid:${g.gid},name:${JSON.stringify(g.name)},mesh:m0.name,err:String(e).slice(0,120)};
         }
       })`,
    );
    out.push(rec);
    scanned++;
    if (scanned % 10 === 0) console.error(`  …${scanned}`);
  }
}

const kinds = { 无网格: 0, 解不出: 0, 没有颜色图: 0, 有层缺贴图: 0, 对齐未验证: 0, 正常: 0 };
for (const r of out) {
  if (!r.mesh) kinds["无网格"]++;
  else if (r.err) kinds["解不出"]++;
  else if (!r.layers) kinds["没有颜色图"]++;
  else if (r.noTex) kinds["有层缺贴图"]++;
  else if (!r.aligned) kinds["对齐未验证"]++;
  else kinds["正常"]++;
}
console.log(JSON.stringify({ scanned, kinds }, null, 1));
fs.writeFileSync(".scratch/dyn/audit_plans_20261027.json", JSON.stringify({ scanned, kinds, out }, null, 1));
console.error("落盘 .scratch/dyn/audit_plans_20261027.json");
ws.close();