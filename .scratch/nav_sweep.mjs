const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find(p => p.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id=0; const pending=new Map(); const errs=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);
  if(m.id&&pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id);}
  if(m.method==="Runtime.exceptionThrown") errs.push(m.params?.exceptionDetails?.text||"exc");
  if(m.method==="Runtime.consoleAPICalled"&&m.params.type==="error") errs.push((m.params.args||[]).map(a=>a.value||a.description).join(" ").slice(0,100));
};
await new Promise(r=>ws.onopen=r);
const call=(m,p={})=>new Promise(res=>{const i=++id;pending.set(i,res);ws.send(JSON.stringify({id:i,method:m,params:p}));});
const wait=ms=>new Promise(r=>setTimeout(r,ms));
const ev=async e=>(await call("Runtime.evaluate",{expression:e,returnByValue:true,awaitPromise:true})).result?.result?.value;
await call("Runtime.enable");
const names = await ev(`[...document.querySelectorAll("nav a, nav button, header a, header button")].map(x=>x.textContent.trim()).filter(Boolean).slice(0,10)`);
console.log("导航项:", JSON.stringify(names));
for (const n of (names||[])) {
  await ev(`(() => { const t=[...document.querySelectorAll("nav a, nav button, header a, header button")].find(x=>x.textContent.trim()===${JSON.stringify(n)}); if(t) t.click(); return !!t; })()`);
  await wait(1500);
  const info = await ev(`(() => { const txt=document.body.innerText.replace(/\s+/g," "); return {len: txt.length, head: txt.slice(0,60)}; })()`);
  console.log(n, JSON.stringify(info));
}
console.log("errors:", errs.length? errs.slice(0,4): "无");
ws.close();
