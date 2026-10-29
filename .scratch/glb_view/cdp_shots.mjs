// 验收取片：用本机 Chrome headless（自己的 user-data-dir，不碰别人），
// 靠 CDP 的 Page.captureScreenshot 拿画面。每条 shot 等 window.__ready 再拍。
import { writeFileSync } from "node:fs";

const BASE = "http://127.0.0.1:9223";
const V = "http://127.0.0.1:8765/.scratch/glb_view/viewer.html";
const YIFU = "/.scratch/glb_rigged/m_db18794d0000cd38.glb";
const SHOUTAO = "/.scratch/glb_rigged/m_8ff895cd00003a5c.glb";

const shots = [
  ["g_rebind_f0_t0",     `asset=${YIFU}&clip=9&t=0&view=front&bones=0&hud=0&rebind=f0`],
  ["h_rebind_f0_t5",     `asset=${YIFU}&clip=9&t=0.5&view=front&bones=0&hud=0&rebind=f0`],
  ["i_rebind_run_t3",    `asset=${YIFU}&clip=12&t=0.3&view=front&bones=0&hud=0&rebind=f0`],
  ["j_rebind_dead_t9",   `asset=${YIFU}&clip=2&t=0.9&view=front&bones=0&hud=0&rebind=f0`],
];



const list = await (await fetch(`${BASE}/json/list`)).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
if (!page) { console.log("没有 page 目标"); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) =>
  new Promise((res) => {
    const mid = ++id;
    const on = (e) => {
      const x = JSON.parse(e.data);
      if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); }
    };
    ws.addEventListener("message", on);
    ws.send(JSON.stringify({ id: mid, method: m, params: p }));
  });
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1400, height: 900, deviceScaleFactor: 1, mobile: false });

const ev = async (expr) => {
  const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true });
  if (r?.exceptionDetails) return "抛错:" + JSON.stringify(r.exceptionDetails).slice(0, 200);
  return r?.result?.value;
};

const log = [];
for (const [name, qs] of shots) {
  await send("Page.navigate", { url: `${V}?${qs}` });
  let ready = false;
  for (let i = 0; i < 60 && !ready; i++) {
    await new Promise((r) => setTimeout(r, 250));
    ready = await ev("!!window.__ready");
  }
  const info = await ev("JSON.stringify(window.__info||{err:window.__error||'超时未就绪'})");
  const out = `D:/TLGL/.scratch/glb_view/${name}.png`;
  const r = await send("Page.captureScreenshot", { format: "png" });
  const d = r?.data;
  if (!d) { log.push(`${name}: 截图失败 ${JSON.stringify(r).slice(0, 120)}`); continue; }
  writeFileSync(out, Buffer.from(d, "base64"));
  log.push(`${name} -> ${out}\n    ${info}`);
}
console.log(log.join("\n"));
writeFileSync("D:/TLGL/.scratch/glb_view/shots_log.txt", log.join("\n"));
ws.close();
