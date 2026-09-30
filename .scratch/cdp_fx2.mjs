const BASE = "http://127.0.0.1:9222";
const STEMS = ["w1351_other_jh_hwpx", "w1351_scene_gmd_yjsm04", "w1351_system_zuobiaoxi_001"];
const list = await (await fetch(`${BASE}/json/list`)).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r?.result?.value; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (js, ms = 25000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { const ok = await ev(`(() => { try { return Boolean(${js}); } catch (e) { return false; } })()`); if (ok === true) return true; await wait(600); } return false; };
const Q = (s) => JSON.stringify(s);

// 界面初始化：等列表出第一行
console.log("列表就绪：", await until(`document.querySelectorAll(".row-item").length > 0`, 40000));

let picked = null;
for (const stem of STEMS) {
  await ev(`(() => { const q=document.getElementById("q"); q.value=${Q(stem)}; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
  const found = await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes(${Q(stem)}))`, 15000);
  console.log(`搜「${stem}」→ ${found}`);
  if (!found) continue;
  await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes(${Q(stem)})); r&&r.click(); return 1; })()`);
  await wait(2500);
  await ev(`(() => { const t=document.querySelector('#dTabs .tab[data-tab="effect"]'); t&&t.click(); return 1; })()`);
  const got = await until(`document.querySelectorAll("#fxTable tbody tr").length > 0`, 25000);
  console.log("  特效表出得来：", got);
  if (!got) { console.log("  摘要：", await ev(`document.getElementById("fxSum").textContent`)); continue; }
  picked = stem;
  console.log("  摘要：", await ev(`document.getElementById("fxSum").textContent`));
  console.log("  行数与类别：", await ev(`[...document.querySelectorAll("#fxTable tbody tr")].map(t=>t.children[0].textContent+" ×"+t.children[1].textContent).join(" / ")`));
  console.log("  贴图样例行：", await ev(`(() => { const t=[...document.querySelectorAll("#fxTable tbody tr")].find(r=>/贴图|材质|网格/.test(r.children[0].textContent)); return t? t.children[2].textContent.slice(0,140) : "无"; })()`));
  console.log("  未解项：", await ev(`[...document.querySelectorAll("#fxMissing li")].map(li=>li.textContent).join(" ／ ")`));
  console.log("  页签计数：", await ev(`document.getElementById("tabFxCount").textContent`));
  break;
}

// 点选择条换一份：表头文件名必须跟着换
console.log("  筹码颗数：", await ev(`document.querySelectorAll("#fxPick button.chip").length`));
console.log("  点下去的是：", await ev(`(() => { const b=document.querySelectorAll("#fxPick button.chip")[1]; if(!b) return "没有第二颗"; b.click(); return b.textContent; })()`));
const switched = await until(`!document.getElementById("fxSum").textContent.startsWith(${Q("")}) && document.getElementById("fxSum").textContent.length > 0`, 20000);
console.log("  换开后摘要：", await ev(`document.getElementById("fxSum").textContent`), "（等到：", switched, "）");
console.log("  高亮的那颗：", await ev(`(() => { const b=[...document.querySelectorAll("#fxPick button.chip.on")][0]; return b? b.textContent : "没有高亮"; })()`));
console.log("选中组：", picked);
// 切到别的组再切回来，确认不残留
await ev(`(() => { const q=document.getElementById("q"); q.value=""; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(1200);
await ev(`(() => { const r=document.querySelector(".row-item"); r&&r.click(); return 1; })()`);
await wait(2000);
console.log("换组后特效表（应清空或重新出表）行数：", await ev(`document.querySelectorAll("#fxTable tbody tr").length`));
console.log("换组后摘要：", await ev(`document.getElementById("fxSum").textContent`));
ws.close();
