const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错：" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text); return r?.result?.value ?? JSON.stringify(r).slice(0, 200); };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
console.log(await ev(`(() => {
  const s = document.getElementById("animFrame");
  const c = document.getElementById("animOnlyChanged");
  const before = { 存在: !!s, 值: s && s.value, 上限: s && s.max, 勾选: c && c.checked,
                   摘要: document.getElementById("animSum").textContent };
  s.value = "10";
  let fired = 0;
  s.addEventListener("input", () => { fired++; });
  s.dispatchEvent(new Event("input", { bubbles: true }));
  return JSON.stringify({ before, 自己挂的监听触发次数: fired, 摘要之后: document.getElementById("animSum").textContent,
                          行数之后: document.querySelectorAll("#animTable tbody tr").length });
})()`));
await wait(500);
console.log(await ev(`JSON.stringify({ 摘要500ms后: document.getElementById("animSum").textContent, 行数: document.querySelectorAll("#animTable tbody tr").length })`));
ws.close();
