// 用 WebView2 自带的远程调试端口做端到端核对：读 DOM、驱动搜索、点卡片、抓图。
// 只在开发核对时使用，不属于应用运行路径。
import { writeFileSync } from "node:fs";
const PORT = process.env.PORT || "9223";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const page = list.find((t) => t.type === "page");
if (!page) {
  console.log("no page target:", list.map((t) => `${t.type}:${t.url}`));
  process.exit(1);
}
console.log("target:", page.url, page.title);

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => {
  ws.onopen = res;
  ws.onerror = rej;
});
let id = 0;
const pending = new Map();
ws.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
};
const send = (method, params = {}) =>
  new Promise((res) => {
    const n = ++id;
    pending.set(n, res);
    ws.send(JSON.stringify({ id: n, method, params }));
  });
const ev = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  if (r.result?.exceptionDetails) return { error: r.result.exceptionDetails.text };
  return { value: r.result?.result?.value };
};

await send("Page.enable");
await send("Runtime.enable");

const dump = async (label, expr) => {
  const { value, error } = await ev(expr);
  console.log(`${label}: ${error ?? JSON.stringify(value)}`);
};

// 初始界面
await dump("标题", "document.title");
await dump("三栏", "[...document.querySelectorAll('.pane')].map(n=>n.className)");
await dump("进度条文案", "document.getElementById('progressText').textContent");
await dump("左栏筛选项", "[...document.querySelectorAll('#scenarios .chip')].map(n=>n.textContent)");
await dump("等级筛选", "[...document.querySelectorAll('#grades .chip')].map(n=>n.textContent)");
await dump("统计", "document.getElementById('stats').textContent");
await dump("卡片数", "document.querySelectorAll('#grid .card').length");
await dump("首张卡片", "document.querySelector('#grid .card')?.innerText.replace(/\n+/g,' | ')");
await dump("占位轮廓数", "document.querySelectorAll('#grid .thumb svg use').length");
await dump("已出图卡片", "document.querySelectorAll('#grid .thumb.has img').length");

// 中文检索：直接键入，走 Rust 侧拼音
await ev(`
  const i = document.getElementById('q');
  i.value = '曹霜';
  i.dispatchEvent(new Event('input', { bubbles: true }));
`);
await sleep(2500);
await dump("搜索后条数", "document.getElementById('count').textContent");
await dump("搜索后卡片", "[...document.querySelectorAll('#grid .card')].map(n=>n.innerText.split('\n')[0])");
await dump("拼法提示", "document.getElementById('words').textContent");

// 点开第一条 → 右栏证据链
await ev(`document.querySelector('#grid .card').click()`);
await sleep(1500);
await dump("证据链", "document.getElementById('detail').innerText.replace(/\n+/g,' | ').slice(0,900)");
await dump("技术折叠区", "document.querySelector('#detail .tech')?.innerText.replace(/\n+/g,' | ')");

// 抓窗口图
const shot = await send("Page.captureScreenshot", { format: "png" });
const buf = Buffer.from(shot.result.data, "base64");
writeFileSync("D:/TLGL/.scratch/app-shot.png", buf);
console.log("screenshot bytes", buf.length);
ws.close();
process.exit(0);
