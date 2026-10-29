// 把动作画布滚到中间、停在中间那一帧，然后截屏（对比改前/改后）
const out = process.argv[2];
const frame = process.argv[3];
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) pending.get(m.id)(m); };
const call = (method, params) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const r = await call("Runtime.evaluate", {
  expression: `globalThis.__FR=${JSON.stringify(frame??'')};(async()=>{
    const s=ms=>new Promise(r=>setTimeout(r,ms));
    const cv=document.getElementById('animCanvas');
    cv.scrollIntoView({block:'center'});
    await s(1200);
    const sl=document.querySelector('input[type=range]');
    let v=null;
    if(sl){
      const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      v=globalThis.__FR?globalThis.__FR:String(Math.round(Number(sl.max||16)/2));
      set.call(sl,v);
      sl.dispatchEvent(new Event('input',{bubbles:true}));
    }
    const p=document.getElementById('animPlay');
    if(process.env.__FR && p&&/播放/.test(p.textContent||''))p.click();
    await s(1600);
    const meta=document.getElementById('animPoseMeta');
    const sum=document.getElementById('animSum');
    return JSON.stringify({滑杆:v,画布:cv.width+'x'+cv.height,可见:cv.offsetParent!==null,
      摘要:(sum?.innerText||'').replace(/\\s+/g,' ').slice(0,90),
      姿势行:(meta?.innerText||'').replace(/\\s+/g,' ').slice(0,90)});
  })()`,
  returnByValue: true, awaitPromise: true,
});
console.log(r.result?.result?.value ?? JSON.stringify(r).slice(0, 300));
const shot = await call("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
const fs = await import("node:fs");
fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));
console.log("截图：" + out);
ws.close();
