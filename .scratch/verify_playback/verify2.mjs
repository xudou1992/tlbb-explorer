// 验收第二轮：对准真实 ID。判定信号：部件勾选区出现 = 尾部名兜底修复生效。
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
const OUT = "D:/TLGL/.scratch/verify_playback";
mkdirSync(OUT, { recursive: true });

const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
if (!page) { console.log("FAIL: 找不到页面 target"); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result ?? x.error ?? {}); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1500, height: 950, deviceScaleFactor: 1, mobile: false });
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text).slice(0, 200); return r?.result?.value; };
const until = async (js, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await ev(`(() => { try { return Boolean(${js}); } catch (e) { return false; } })()`)) return true; await wait(800); } return false; };
const shot = async (name, clip) => {
  let r = await send("Page.captureScreenshot", { format: "png", ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
  if (!r?.data) console.log(`  clip 截图失败 ${name}: ` + JSON.stringify(r).slice(0, 160) + "，试全视口");
  if (!r?.data) r = await send("Page.captureScreenshot", { format: "png" });
  const d = r?.data;
  if (!d) { console.log(`  截图失败 ${name}: ` + JSON.stringify(r ?? {}).slice(0, 160)); return null; }
  writeFileSync(`${OUT}/${name}.png`, Buffer.from(d, "base64"));
  console.log(`  截图 ${name}.png`);
  return `${OUT}/${name}.png`;
};
const boxOf = (sel) => ev(`(() => { const e=document.querySelector(${JSON.stringify(sel)}); if(!e) return null; const r=e.getBoundingClientRect(); return {x:Math.max(0,r.x),y:Math.max(0,r.y),width:Math.min(r.width,1400),height:Math.min(r.height,900)}; })()`);

console.log("== 0. 切到资产视图 ==");
await ev(`(() => { document.getElementById("tabAssets").click(); return 1; })()`);
console.log("  资产视图激活：", await until(`document.getElementById("tabAssets").classList.contains("on")`, 10000));
await wait(1500);

console.log("== 1. 选中怪 ==");
console.log("  行数>0：", await until(`document.querySelectorAll(".row-item").length > 0`, 30000));
await ev(`(() => { const q=document.getElementById("q"); q.value=""; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(1200);
await ev(`(() => { const q=document.getElementById("q"); q.value="xiyuqiezei"; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
console.log("  搜到怪：", await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes("xiyuqiezei"))`, 30000));
await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes("xiyuqiezei")); r&&r.click(); return 1; })()`);
console.log("  详情出现：", await until(`document.getElementById("skelSum") && document.getElementById("skelSum").textContent.length > 0`, 40000));

console.log("== 2. 骨架页（挂在谁/反解）==");
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="skeleton"]').click(); return 1; })()`);
await wait(1500);
console.log("  表头：", await ev(`(() => { const h=document.querySelector("table thead tr"); return h?[...h.children].map(c=>c.textContent.trim()).join(" | "):"无"; })()`));
console.log("  根行：", await ev(`(() => { const td=[...document.querySelectorAll("td")].find(t=>t.textContent==="这是根"); return td?"有("+td.parentElement.firstChild.textContent+")":"无"; })()`));
console.log("  反解条数：", await ev(`[...document.querySelectorAll("li")].filter(li=>li.textContent.includes("反解")).length`));
await shot("skeleton_table", await boxOf("table.hl-table") || await boxOf(".d-sec"));

console.log("== 3. 动作页（整组播放，核心验收）==");
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="animation"]').click(); return 1; })()`);
console.log("  动作摘要：", await until(`document.getElementById("animSum") && document.getElementById("animSum").textContent.length > 0`, 40000));
console.log("  animSum：", await ev(`document.getElementById("animSum").textContent`));
console.log("  部件勾选出现（=修复生效）：", await until(`document.querySelectorAll("#animPartPick input[type=checkbox]").length >= 2`, 60000));
console.log("  meta 行：", await ev(`(() => { const m=document.getElementById("animPoseMeta"); return m?m.textContent.trim():"无"; })()`));
console.log("  勾选件数：", await ev(`document.querySelectorAll("#animPartPick input[type=checkbox]").length`));
console.log("  播放按钮：", await ev(`(() => { const b=document.getElementById("animPlay"); return b?b.textContent:"无"; })()`));
console.log("  参考速度：", await ev(`document.getElementById("animPoseBox").textContent.includes("参考速度")`));
console.log("  注记行：", await ev(`(() => { const n=document.getElementById("animPartNote"); return n&&!n.hidden?n.textContent.trim().slice(0,160):"(隐藏或空)"; })()`));
console.log("  错误行：", await ev(`(() => { const e=document.getElementById("animPoseErr"); return e&&!e.hidden?e.textContent.trim().slice(0,160):"(隐藏=无错误)"; })()`));
console.log("  动画画布就绪：", await until(`(() => { const c=document.getElementById("animCanvas"); return c&&c.width>100&&c.height>100; })()`, 20000));
console.log("  画布尺寸：", await ev(`(() => { const c=document.getElementById("animCanvas"); return c.width+"x"+c.height; })()`));
await wait(2000);
const clip = await boxOf("#animStage");
await shot("anim_frame0", clip);
await ev(`(() => { const s=document.getElementById("animFrame"); s.value="12"; s.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(2200);
await shot("anim_frame12", clip);
await ev(`(() => { const s=document.getElementById("animFrame"); s.value="28"; s.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(2200);
await shot("anim_frame28", clip);
try {
  const f0 = readFileSync(`${OUT}/anim_frame0.png`), f12 = readFileSync(`${OUT}/anim_frame12.png`), f28 = readFileSync(`${OUT}/anim_frame28.png`);
  console.log("  帧间像素差：", `0vs12=${Buffer.compare(f0, f12) !== 0 ? "不同" : "相同!"}, 12vs28=${Buffer.compare(f12, f28) !== 0 ? "不同" : "相同!"}, 字节 ${f0.length}/${f12.length}/${f28.length}`);
} catch { console.log("  帧截图缺失，跳过像素差"); }

console.log("== 4. 播放与部件勾选 ==");
await ev(`(() => { document.getElementById("animPlay").click(); return 1; })()`);
await wait(2500);
const played = await ev(`Number(document.getElementById("animFrame").value)`);
console.log("  播放 2.5s 后游标：", played, played > 0 ? "(已步进)" : "(未动!)");
await ev(`(() => { const b=document.getElementById("animPlay"); if (b && b.textContent.includes("暂停")) b.click(); return 1; })()`);
console.log("  暂停按钮文案：", await ev(`document.getElementById("animPlay").textContent`));
await ev(`(() => { const c=[...document.querySelectorAll("#animPartPick input[type=checkbox]")]; if(c[1]) { c[1].checked=false; c[1].dispatchEvent(new Event("change",{bubbles:true})); } return 1; })()`);
await wait(1800);
console.log("  关掉一件后 meta：", await ev(`document.getElementById("animPoseMeta").textContent.trim()`));
await ev(`(() => { const c=[...document.querySelectorAll("#animPartPick input[type=checkbox]")]; if(c[1]) { c[1].checked=true; c[1].dispatchEvent(new Event("change",{bubbles:true})); } return 1; })()`);
await wait(1500);
console.log("  恢复后 meta：", await ev(`document.getElementById("animPoseMeta").textContent.trim()`));

console.log("== 5. 详情预览页（骨线）==");
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="preview"]').click(); return 1; })()`);
console.log("  画布就绪：", await until(`(() => { const c=document.getElementById("meshCanvas"); return c&&c.width>100&&c.height>100; })()`, 25000));
await wait(2500);
console.log("  画布尺寸：", await ev(`(() => { const c=document.getElementById("meshCanvas"); return c.width+"x"+c.height; })()`));
await shot("mesh_bonelines", await boxOf("#meshCanvas"));
ws.close();
console.log("== 脚本跑完 ==");
