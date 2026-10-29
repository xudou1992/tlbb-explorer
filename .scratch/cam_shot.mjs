import { writeFileSync } from "node:fs";
const [clip, frame, out] = process.argv.slice(2);
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id=0; const pending=new Map();
ws.onmessage=e=>{const m=JSON.parse(e.data); if(m.id&&pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id);}};
await new Promise(r=>ws.onopen=r);
const call=(method,params={})=>new Promise(res=>{const i=++id;pending.set(i,res);ws.send(JSON.stringify({id:i,method,params}));});
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const ev=async e=>(await call("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true})).result?.result?.value;
// 选动作
await ev(`(() => { const b=[...document.querySelectorAll("#animPick .chip")].find(x=>x.dataset.value.includes(${JSON.stringify(clip)})); if(b) b.click(); return !!b; })()`);
await wait(2500);
// 拖帧
await ev(`(() => { const s=document.getElementById("animFrame"); s&&s.scrollIntoView({block:"center"}); return 1; })()`);
await wait(700);
const box=await ev(`(() => { const s=document.getElementById("animFrame"); const r=s.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height,min:+s.min,max:+s.max,val:+s.value}; })()`);
if (box && box.w>0) {
  const y=box.y+box.h/2, gx=box.x+(Math.min(+frame,box.max)-box.min)/(box.max-box.min)*box.w;
  const sx=box.x+(box.val-box.min)/(box.max-box.min)*box.w;
  await call("Input.dispatchMouseEvent",{type:"mousePressed",x:sx,y,button:"left",clickCount:1});
  for(let k=1;k<=8;k++){await call("Input.dispatchMouseEvent",{type:"mouseMoved",x:sx+(gx-sx)*k/8,y,button:"left"});await wait(50);}
  await call("Input.dispatchMouseEvent",{type:"mouseReleased",x:gx,y,button:"left",clickCount:1});
  await wait(1800);
}
// 先把最大 canvas 滚进视口再双击复位
await ev(`(() => { const list=[...document.querySelectorAll("canvas")].map(cv=>{const r=cv.getBoundingClientRect();return {el:cv,x:r.x,y:r.y,w:r.width,h:r.height};}).filter(r=>r.w>200&&r.h>150); list.sort((a,b)=>b.w*b.h-a.w*a.h); if(list[0]) list[0].el.scrollIntoView({block:"center"}); return !!list[0]; })()`);
await wait(900);
const c=await ev(`(() => { const list=[...document.querySelectorAll("canvas")].map(cv=>{const r=cv.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};}).filter(r=>r.w>200&&r.h>150); list.sort((a,b)=>b.w*b.h-a.w*a.h); return list[0]||null; })()`);
console.log("canvas", JSON.stringify(c), "frame", await ev(`document.getElementById("animFrame")?.value`));
if (c) {
  const x=c.x+c.w/2, y=c.y+c.h/2;
  for (const n of [1,2]) {
    await call("Input.dispatchMouseEvent",{type:"mousePressed",x,y,button:"left",clickCount:n});
    await call("Input.dispatchMouseEvent",{type:"mouseReleased",x,y,button:"left",clickCount:n});
    await wait(120);
  }
  await wait(1500);
}
const shot=await call("Page.captureScreenshot",{format:"png"});
writeFileSync(out, Buffer.from(shot.result.data,"base64"));
console.log("saved", out);
ws.close();
