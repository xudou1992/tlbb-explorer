// 在真实窗口里验「骨架」页：搜一只怪 → 点进详情 → 切到骨架标签 → 把表读出来。
// 前置：应用带 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222 起。
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
if (!page) {
  console.log("没有可调试页面");
  process.exit(1);
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (method, params = {}) =>
  new Promise((res) => {
    const mid = ++id;
    const on = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === mid) {
        ws.removeEventListener("message", on);
        res(m.result);
      }
    };
    ws.addEventListener("message", on);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
await new Promise((res) => ws.addEventListener("open", res, { once: true }));
const ev = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  return r?.result?.value ?? r?.exceptionDetails?.text ?? JSON.stringify(r).slice(0, 200);
};

const until = async (js, ms = 60000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const ok = await ev(`(() => { try { return Boolean(${js}); } catch (e) { return false; } })()`);
    if (ok) return true;
    await wait(1000);
  }
  return false;
};

console.log("页面：", page.title);
// 应用可能开在「浏览」视图，那里没有资产列表——先切到「资产」
const views = await ev(`(() => { const b = [...document.querySelectorAll("button, a")]
    .find(n => n.textContent.trim() === "资产"); if (b) { b.click(); return "已切到资产"; } return "找不到资产入口"; })()`);
console.log("视图：", views);
await wait(2500);
// 资产库要后台读十几万条，读完之前列表是空的——先等它真有行
console.log("等到有行：", await until(`document.querySelectorAll(".row-item").length > 0`));
// 1) 搜一只带骨架的怪
await ev(`(() => { const q = document.getElementById("q");
  q.value = "xiyuqiezei"; q.dispatchEvent(new Event("input", { bubbles: true })); return "typed"; })()`);
console.log("搜索结果里出现这只怪：", await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes("xiyuqiezei"))`, 30000));
console.log("列表首行：", await ev(`(() => { const r = document.querySelector(".row-item");
  return r ? r.textContent.trim().slice(0, 40) : "没有行"; })()`));
// 2) 点进去
await ev(`(() => { const r = document.querySelector(".row-item"); if (r) r.click(); return "clicked"; })()`);
console.log("打开的资产：", await ev(`document.querySelector("#dTitle")?.textContent || document.title`));
await until(`document.querySelectorAll("#skelTable tbody tr").length > 0 || document.getElementById("skelSum").textContent.length > 0`, 30000);
// 3) 切到骨架标签
console.log("标签列表：", await ev(`[...document.querySelectorAll("#dTabs .tab")].map(b=>b.dataset.tab).join(",")`));
await ev(`(() => { const b = document.querySelector('#dTabs .tab[data-tab="skeleton"]'); if (b) b.click(); return "tab"; })()`);
await wait(4000);
console.log("摘要：", await ev(`document.getElementById("skelSum").textContent`));
console.log("骨名行数：", await ev(`document.querySelectorAll("#skelTable tbody tr").length`));
console.log("前四根骨：", await ev(`[...document.querySelectorAll("#skelTable tbody tr")].slice(0,4).map(t=>t.children[0].textContent).join(" | ")`));
console.log("第一行数值：", await ev(`(() => { const t = document.querySelector("#skelTable tbody tr");
  return t ? [...t.children].map(c=>c.textContent).join(" , ") : "无"; })()`));
console.log("动作行数：", await ev(`document.querySelectorAll("#skelAnims tbody tr").length`));
console.log("第一条动作：", await ev(`(() => { const t = document.querySelector("#skelAnims tbody tr");
  return t ? [...t.children].map(c=>c.textContent).join(" , ") : "无"; })()`));
console.log("未解项：", await ev(`[...document.querySelectorAll("#skelMissing li")].map(li=>li.textContent.slice(0,26)).join(" ／ ")`));
console.log("当前高亮标签：", await ev(`(() => { const b = document.querySelector("#dTabs .tab.on"); return b ? b.dataset.tab : "无"; })()`));
console.log("骨架标签上的数字：", await ev(`document.getElementById("tabSkelCount").textContent`));
ws.close();
