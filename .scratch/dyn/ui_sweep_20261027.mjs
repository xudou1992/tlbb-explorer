// 逐资产 × 逐页签扫一遍：点开每页、读页面文案与画布状态，把「失败/解不出/没找到」这类
// 话术和空面板挑出来。全部用真事件（CDP Input）。
const assets = process.argv.slice(2);
if (!assets.length) { console.log("要给资产关键词"); process.exit(1); }
const tabs = ["preview", "resource", "skeleton", "animation", "effect", "material", "relations"];
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) pending.get(m.id)(m); };
const call = (method, params) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async x => (await call("Runtime.evaluate", { expression: x, returnByValue: true, awaitPromise: true })).result?.result?.value;
const nap = ms => new Promise(r => setTimeout(r, ms));

const BAD = ["解不出", "失败", "没找到", "起不来", "读不出", "出错", "错误", "无法"];
for (const kw of assets) {
  await ev(`(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));
    const inp=document.querySelector('#q');inp.focus();
    const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    set.call(inp,${JSON.stringify(kw)});inp.dispatchEvent(new Event('input',{bubbles:true}));
    await s(2200);const rows=[...document.querySelectorAll('.row-item')];if(rows.length)rows[0].click();await s(2600);return 1})()`);
  for (const tab of tabs) {
    const ok = await ev(`(()=>{const t=document.querySelector('button.tab[data-tab="${tab}"]');if(!t)return 0;t.click();return 1})()`);
    if (!ok) { console.log(`${kw} · ${tab}: 没有这个页签`); continue; }
    await nap(2600);
    const info = JSON.parse(await ev(`(()=>{
      const pane=document.getElementById('detailPane');
      const txt=(pane?pane.innerText:'').split(String.fromCharCode(10)).join(' ').split('  ').join(' ').trim();
      const cv=[...document.querySelectorAll('canvas')].filter(c=>c.offsetParent!==null);
      return JSON.stringify({len:txt.length, head:txt.slice(0,110), canvas:cv.map(c=>c.width+'x'+c.height), imgs:[...document.querySelectorAll('#detailPane img')].filter(i=>i.offsetParent!==null).length});
    })()`));
    const bad = BAD.filter(w => info.head.includes(w) || info.len < 20);
    console.log(`${kw} · ${tab}: ${info.len} 字 · 画布[${info.canvas.join(",")}] · 图 ${info.imgs}${bad.length ? "  ⚠ " + bad.join("/") : ""}  「${info.head}」`);
  }
}
ws.close();
