// 真实窗口里依次验：骨架页 → 动作页（拖游标）→ 特效页。
// 前置：WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222 起应用。
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
if (!page) {
  console.log("没有可调试页面");
  process.exit(1);
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) =>
  new Promise((res) => {
    const mid = ++id;
    const on = (ev) => {
      const x = JSON.parse(ev.data);
      if (x.id === mid) {
        ws.removeEventListener("message", on);
        res(x.result);
      }
    };
    ws.addEventListener("message", on);
    ws.send(JSON.stringify({ id: mid, method: m, params: p }));
  });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => {
  const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true });
  return r?.result?.value ?? JSON.stringify(r).slice(0, 200);
};
const until = async (js, ms = 45000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (await ev(`(() => { try { return Boolean(${js}); } catch (e) { return false; } })()`)) return true;
    await wait(1000);
  }
  return false;
};
const tab = async (name) => {
  await ev(`(() => { const b = document.querySelector('#dTabs .tab[data-tab="${name}"]'); b && b.click(); return 1; })()`);
  await wait(2500);
};

console.log("切到资产：", await ev(`(() => { const b = [...document.querySelectorAll("button")].find(x => x.textContent.trim() === "资产"); b && b.click(); return !!b; })()`));
console.log("等到有行：", await until(`document.querySelectorAll(".row-item").length > 0`));
await ev(`(() => { const q = document.getElementById("q"); q.value = "xiyuqiezei"; q.dispatchEvent(new Event("input", { bubbles: true })); return 1; })()`);
console.log("搜到怪：", await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes("xiyuqiezei"))`, 25000));
await ev(`(() => { const r = document.querySelector(".row-item"); r && r.click(); return 1; })()`);
await wait(4000);

console.log("\n【骨架】", await ev(`document.getElementById("skelSum").textContent`));
console.log("  骨名行数：", await ev(`document.querySelectorAll("#skelTable tbody tr").length`));

await tab("animation");
console.log("\n【动作】", await ev(`document.getElementById("animSum").textContent`));
console.log("  表行数：", await ev(`document.querySelectorAll("#animTable tbody tr").length`), "（第 1 帧相对自己没变化，应为 0）");
console.log("  滑块上限：", await ev(`document.getElementById("animFrame").max`));
await ev(`(() => { const s = document.getElementById("animFrame"); s.value = "10"; s.dispatchEvent(new Event("input", { bubbles: true })); return 1; })()`);
await wait(1500);
console.log("  拖到第 11 帧：", await ev(`document.getElementById("animSum").textContent`));
console.log("  表行数：", await ev(`document.querySelectorAll("#animTable tbody tr").length`));
console.log("  第一行：", await ev(`(() => { const t = document.querySelector("#animTable tbody tr"); return t ? [...t.children].map(c=>c.textContent).join(" | ") : "无"; })()`));
console.log("  未解项：", await ev(`[...document.querySelectorAll("#animMissing li")].map(li=>li.textContent.slice(0,22)).join(" ／ ")`));

// 特效页：换一只特效资产再验
await ev(`(() => { const q = document.getElementById("q"); q.value = "tuxiaoyao_b7_hit02"; q.dispatchEvent(new Event("input", { bubbles: true })); return 1; })()`);
await wait(2500);
console.log("\n搜到特效：", await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes("tuxiaoyao"))`, 25000));
await ev(`(() => { const r = document.querySelector(".row-item"); r && r.click(); return 1; })()`);
await wait(4000);
await tab("effect");
console.log("【特效】", await ev(`document.getElementById("fxSum").textContent`));
console.log("  类别行数：", await ev(`document.querySelectorAll("#fxTable tbody tr").length`));
console.log("  表内容：", await ev(`[...document.querySelectorAll("#fxTable tbody tr")].slice(0,4).map(t=>t.children[0].textContent+"="+t.children[1].textContent).join(" | ")`));
console.log("  未解项：", await ev(`[...document.querySelectorAll("#fxMissing li")].map(li=>li.textContent.slice(0,26)).join(" ／ ")`));
console.log("  当前高亮：", await ev(`(document.querySelector("#dTabs .tab.on")||{}).dataset ? document.querySelector("#dTabs .tab.on").dataset.tab : "无"`));
ws.close();
