const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (js, ms = 40000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await ev(`(() => { try { return Boolean(${js}); } catch (e) { return false; } })()`)) return true; await wait(700); } return false; };
const pick = async (word) => {
  await ev(`(() => { const q=document.getElementById("q"); q.value=""; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  await wait(1200);
  await ev(`(() => { const q=document.getElementById("q"); q.value="${word}"; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  const found = await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes("${word}"))`);
  await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes("${word}")); r&&r.click(); return 1; })()`);
  await wait(2500);
  return found;
};
await ev(`(() => { const b=[...document.querySelectorAll("button")].find(x=>x.textContent.trim()==="资产"); b&&b.click(); return 1; })()`);
await until(`document.querySelectorAll(".row-item").length > 0`);

console.log("=== 怪物 ===", await pick("xiyuqiezei"));
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="skeleton"]').click(); return 1; })()`);
console.log("骨架：", await until(`document.querySelectorAll("#skelTable tbody tr").length > 0`), await ev(`document.getElementById("skelSum").textContent`));
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="animation"]').click(); return 1; })()`);
console.log("动作取到：", await until(`document.getElementById("animSum").textContent.includes("根骨")`), await ev(`document.getElementById("animSum").textContent`));
await ev(`(() => { const s=document.getElementById("animFrame"); s.value="10"; s.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await until(`document.getElementById("animSum").textContent.includes("第 11")`);
console.log("  拖到 11 帧：", await ev(`document.getElementById("animSum").textContent`), "行数", await ev(`document.querySelectorAll("#animTable tbody tr").length`));

console.log("\n=== 特效 ===", await pick("tuxiaoyao"));
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="effect"]').click(); return 1; })()`);
console.log("特效取到：", await until(`document.querySelectorAll("#fxTable tbody tr").length > 0`));
console.log("  摘要：", await ev(`document.getElementById("fxSum").textContent`));
console.log("  类别：", await ev(`[...document.querySelectorAll("#fxTable tbody tr")].map(t=>t.children[0].textContent+"("+t.children[1].textContent+")").join(" ")`));
console.log("  未解：", await ev(`[...document.querySelectorAll("#fxMissing li")].map(li=>li.textContent.slice(0,20)).join(" ／ ")`));
ws.close();
