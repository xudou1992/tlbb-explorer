const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + r.exceptionDetails.text; return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
await wait(1200);
await ev(`(() => { const b=[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="资产"); b&&b.click(); return 1; })()`);
await wait(3000);
await ev(`(() => { const q=document.getElementById("q"); q.value="zq_qszd"; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(6000);
await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes("zq_qszd")); r&&r.click(); return 1; })()`);
await wait(4000);
// 文件清单：这一栏是不是真能看全 3,405 个成员
await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="files"]'); t&&t.click(); return 1; })()`);
await wait(3000);
console.log("文件清单条数：", await ev(`document.querySelectorAll("#fileList > div, #fileList > dt, #fileList > dd, #fileList > a").length`), "· 标注", await ev(`(document.getElementById("fileCount")||{}).textContent`));
// 材质页：说明点一下要多出 100 颗
await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="material"]'); t&&t.click(); return 1; })()`);
await wait(5000);
console.log("筹码：", await ev(`document.querySelectorAll("#mtlPick button.chip").length`), "· 说明：", await ev(`(document.querySelector("#mtlPick .chip-more")||{}).textContent`));
await ev(`(() => { const b=document.querySelector("#mtlPick .chip-more"); b&&b.click(); return 1; })()`);
await wait(1500);
console.log("点一次之后筹码：", await ev(`document.querySelectorAll("#mtlPick button.chip").length`), "· 说明：", await ev(`(document.querySelector("#mtlPick .chip-more")||{}).textContent`));
console.log("表还在不在：", await ev(`document.querySelectorAll("#mtlTable tbody tr").length`));
ws.close();
