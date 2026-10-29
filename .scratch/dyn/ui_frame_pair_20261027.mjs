// 钉帧对照（全部用真事件）：搜资产 → 开动作页 → 真拖游标到 15% / 50% → 各截一张
// 用法：node ui_frame_pair_20261027.mjs <关键词> <前缀>
import fs from "node:fs";
import crypto from "node:crypto";
const kw = process.argv[2] || "xinmurongfu";
const tag = process.argv[3] || kw;
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) pending.get(m.id)(m); };
const call = (method, params) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async e => (await call("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true })).result?.result?.value;
const nap = ms => new Promise(r => setTimeout(r, ms));
const shot = async f => { const r = await call("Page.captureScreenshot", { format: "png" }); fs.writeFileSync(f, Buffer.from(r.result.data, "base64")); return crypto.createHash("md5").update(fs.readFileSync(f)).digest("hex").slice(0, 10); };

await ev(`(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));
 const inp=document.querySelector('#q');inp.focus();
 const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
 set.call(inp,${JSON.stringify(kw)});inp.dispatchEvent(new Event('input',{bubbles:true}));
 await s(2500);const rows=[...document.querySelectorAll('.row-item')];if(rows.length)rows[0].click();
 await s(3000);const t=document.querySelector('button.tab[data-tab=animation]');if(t)t.click();await s(4000);
 return 1})()`);
await ev(`document.getElementById('animCanvas').scrollIntoView({block:'center'})`);
await nap(800);
const box = JSON.parse(await ev(`(()=>{const e=document.getElementById('animFrame');const r=e.getBoundingClientRect();return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height,max:e.max})})()`));
const y = box.y + box.h / 2;
const drag = async f => {
  const x = box.x + box.w * f;
  await call("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await call("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
  await nap(2600);
  return await ev(`document.getElementById('animFrame').value`);
};
const out = [];
for (const f of [0.15, 0.5]) {
  const v = await drag(f);
  const h = await shot(`D:/TLGL/.scratch/dyn/frame_${tag}_${String(f).replace('.', '')}.png`);
  const meta = await ev(`(document.getElementById('animPoseMeta')||{}).innerText||''`);
  out.push({ 比例: f, 帧: v, 哈希: h, 说明: (meta || "").replace(/\s+/g, " ").slice(0, 60) });
}
console.log(kw, "max=" + box.max, JSON.stringify(out, null, 1));
ws.close();
