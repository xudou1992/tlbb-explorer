// 真窗口验收（第二版，选择器按 index.html 的真实 DOM）：
// #q 搜索 → 点第一条 .row-item → button.tab[data-tab=animation] → 读 #animCanvas 像素 + 面板文案 → 截屏。
const out = process.argv[2] || "D:/TLGL/.scratch/min3_play_20261027.png";
const kw = process.argv[3] || "xinmurongfu";
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) pending.get(m.id)(m); };
const call = (method, params) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const run = async expr => {
  const r = await call("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) return "异常：" + JSON.stringify(r.result.exceptionDetails).slice(0, 400);
  return r.result?.result?.value;
};
console.log(await run(`(async()=>{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const rep={};
  const inp=document.querySelector('#q');
  rep.搜索框=!!inp;
  if(inp){
    inp.focus();
    const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    set.call(inp, ${JSON.stringify(kw)});
    inp.dispatchEvent(new Event('input',{bubbles:true}));
    await sleep(2500);
  }
  const rows=[...document.querySelectorAll('.row-item')];
  rep.行数=rows.length;
  rep.首行文案=(rows[0]&&(rows[0].innerText||'')).replace(/\\s+/g,' ').slice(0,60);
  if(rows.length){ rows[0].click(); await sleep(3000); }
  const tab=document.querySelector('button.tab[data-tab=animation]');
  rep.找到动作页=!!tab;
  if(tab){ tab.click(); await sleep(4000); }
  const cv=document.querySelector('#animCanvas');
  rep.画布=cv?cv.width+'x'+cv.height:'没有 #animCanvas';
  if(cv){
    try{
      const g=cv.getContext('webgl2')||cv.getContext('webgl');
      const px=new Uint8Array(cv.width*cv.height*4);
      g.readPixels(0,0,cv.width,cv.height,g.RGBA,g.UNSIGNED_BYTE,px);
      let nz=0,mx=0;
      for(let i=0;i<px.length;i+=4){if(px[i+3]>8&&px[i]+px[i+1]+px[i+2]>24)nz++;const s=px[i]+px[i+1]+px[i+2];if(s>mx)mx=s;}
      rep.画布非空像素占比=+(100*nz/(cv.width*cv.height)).toFixed(2);
      rep.画布最亮=mx;
    }catch(e){rep.画布读数=String(e);}
  }
  const panel=document.querySelector('[data-panel=animation]')||document;
  const txt=(panel.innerText||'');
  rep.含解不出=txt.includes('解不出')||txt.includes('不按已知的');
  rep.面板片段=txt.split('\\n').map(s=>s.trim()).filter(s=>s&&(s.includes('骨')||s.includes('帧')||s.includes('未命名')||s.includes('轨道'))).slice(0,10);
  return JSON.stringify(rep,null,1);
})()`));
const r = await call("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
const fs = await import("node:fs");
fs.writeFileSync(out, Buffer.from(r.result.data, "base64"));
console.log("截图：", out);
ws.close();
