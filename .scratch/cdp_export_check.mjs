// 在真实窗口里点「导出」并把回话读出来。
// 用法：先带 WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222 起应用，
// 再 node .scratch/cdp_export_check.mjs [要点的按钮 id]
const btn = process.argv[2] ?? "btnExportOne";
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
if (!page) {
  console.log("没找到可调试的页面目标；当前目标：", list.map((t) => `${t.type}:${t.title}`));
  process.exit(1);
}
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
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
await new Promise((res) => ws.addEventListener("open", res, { once: true }));

const ev = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  return r?.result?.value ?? r?.exceptionDetails?.text ?? r;
};

console.log("页面：", page.title, page.url.slice(0, 60));
console.log("点之前：", await ev(`document.getElementById("dSum").textContent`));
const clicked = await ev(
  `(() => { const b = document.getElementById(${JSON.stringify(btn)});
     if (!b) return "没有这个按钮"; b.click(); return "clicked"; })()`,
);
console.log("点击：", clicked);
for (const ms of [500, 1500, 3000, 6000]) {
  await wait(ms === 500 ? 500 : 1000);
  const t = await ev(`document.getElementById("dSum").textContent`);
  console.log(`  ~${ms}ms 后：`, t);
}
ws.close();
