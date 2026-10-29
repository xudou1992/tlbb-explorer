// 人眼验收代步：CDP 驱动真 app，逐阶段 DOM 断言 + 截图。
// 阶段：选中怪 → 骨架页（挂在谁/反解）→ 预览页（骨线）→ 动作页（整组/逐帧/播放）。
import { writeFileSync, mkdirSync, readFileSync } from "node:fs";
const OUT = "D:/TLGL/.scratch/verify_playback";
mkdirSync(OUT, { recursive: true });

const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
if (!page) { console.log("FAIL: 找不到页面 target"); process.exit(1); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (m, p = {}) => new Promise((res) => { const mid = ++id; const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener("message", on); res(x.result); } }; ws.addEventListener("message", on); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1500, height: 950, deviceScaleFactor: 1, mobile: false });
await wait(1500);
const ev = async (e) => { const r = await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }); if (r?.exceptionDetails) return "抛错:" + (r.exceptionDetails.exception?.description || r.exceptionDetails.text).slice(0, 200); return r?.result?.value; };
const until = async (js, ms) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await ev(`(() => { try { return Boolean(${js}); } catch (e) { return false; } })()`)) return true; await wait(800); } return false; };
const shot = async (name, clip) => {
  const r = await send("Page.captureScreenshot", { format: "png", ...(clip ? { clip: { ...clip, scale: 1 } } : {}) });
  const d = r?.data;
  if (!d) { console.log(`  截图失败 ${name}`); return null; }
  const p = `${OUT}/${name}.png`;
  writeFileSync(p, Buffer.from(d, "base64"));
  console.log(`  截图 ${name}.png`);
  return p;
};
const boxOf = (sel) => ev(`(() => { const e=document.querySelector(${JSON.stringify(sel)}); if(!e) return null; const r=e.getBoundingClientRect(); return {x:Math.max(0,r.x),y:Math.max(0,r.y),width:Math.min(r.width,1400),height:Math.min(r.height,900)}; })()`);

console.log("== 0. 就绪与选中 ==");
console.log("  行数>0：", await until(`document.querySelectorAll(".row-item").length > 0`, 30000));
await ev(`(() => { const q=document.getElementById("q"); q.value=""; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(1200);
await ev(`(() => { const q=document.getElementById("q"); q.value="xiyuqiezei"; q.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
console.log("  搜到怪：", await until(`[...document.querySelectorAll(".row-item")].some(r=>r.textContent.includes("xiyuqiezei"))`, 30000));
await ev(`(() => { const r=[...document.querySelectorAll(".row-item")].find(x=>x.textContent.includes("xiyuqiezei")); r&&r.click(); return 1; })()`);
console.log("  骨架摘要出现：", await until(`document.getElementById("skelSum") && document.getElementById("skelSum").textContent.length > 0`, 40000));
console.log("  skelSum：", await ev(`document.getElementById("skelSum").textContent`));

console.log("== 1. 骨架页 ==");
const tabNames = await ev(`[...document.querySelectorAll("#dTabs .tab")].map(t=>t.dataset.tab+":"+t.textContent.trim()).join(" ")`);
console.log("  标签页：", tabNames);
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="skeleton"]').click(); return 1; })()`);
await wait(1500);
console.log("  表头：", await ev(`(() => { const h=document.querySelector("#skelTable thead tr, #skelTable thead, .d-sec table thead tr"); return h?[...h.children].map(c=>c.textContent.trim()).join(" | "):"无表头"; })()`));
console.log("  挂在谁列存在：", await ev(`[...document.querySelectorAll("th")].some(t=>t.textContent.includes("挂在谁"))`));
console.log("  根行：", await ev(`(() => { const td=[...document.querySelectorAll("td")].find(t=>t.textContent==="这是根"); return td?"有("+(td.parentElement.firstChild.textContent)+")":"无"; })()`));
console.log("  反解文案：", await ev(`[...document.querySelectorAll("#skelMissing li, .d-sec li")].map(li=>li.textContent).filter(t=>t.includes("反解")).length + " 条含「反解」"`));
console.log("  未解列表：", await ev(`(() => { const box=[...document.querySelectorAll("ul")].find(u=>u.previousElementSibling&&u.previousElementSibling.textContent.includes("还没解出来")); return box?[...box.querySelectorAll("li")].map(li=>li.textContent.slice(0,60)).join(" ／ "):"未找到"; })()`));
await shot("skeleton_table", await boxOf("#skelTable") || await boxOf(".d-sec"));

console.log("== 2. 预览页（灰模+骨线）==");
const meshTab = await ev(`(() => { const t=[...document.querySelectorAll("#dTabs .tab")].find(t=>{ const p=document.querySelector('.tabpane[data-pane="'+t.dataset.tab+'"]'); return p&&p.querySelector("#meshCanvas"); }); return t?t.dataset.tab:"无"; })()`);
console.log("  网格画布所在标签：", meshTab);
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="${meshTab}"]').click(); return 1; })()`);
console.log("  画布出现：", await until(`(() => { const c=document.getElementById("meshCanvas"); return c&&c.width>50&&c.height>50; })()`, 15000));
await wait(2500);
console.log("  画布尺寸：", await ev(`(() => { const c=document.getElementById("meshCanvas"); return c.width+"x"+c.height; })()`));
await shot("mesh_bonelines", await boxOf(".mesh-stage"));

console.log("== 3. 动作页（整组播放）==");
await ev(`(() => { document.querySelector('#dTabs .tab[data-tab="animation"]').click(); return 1; })()`);
console.log("  动作摘要出现：", await until(`document.getElementById("animSum") && document.getElementById("animSum").textContent.length > 0`, 40000));
console.log("  animSum：", await ev(`document.getElementById("animSum").textContent`));
console.log("  预览盒存在：", await until(`document.getElementById("animPoseBox") && document.getElementById("animPoseBox").hidden === false`, 30000));
console.log("  meta 行：", await ev(`(() => { const m=document.querySelector("#animPoseBox .mesh-head, #animPoseBox p"); return m?m.textContent.trim().slice(0,120):"无"; })()`));
console.log("  部件勾选数：", await ev(`document.querySelectorAll("#animPartPick input[type=checkbox]").length`));
console.log("  播放按钮：", await ev(`(() => { const b=document.querySelector("#animPoseBox button"); return b?b.textContent+"/"+b.getAttribute("aria-label"):"无"; })()`));
console.log("  参考速度字样：", await ev(`document.getElementById("animPoseBox").textContent.includes("参考速度")`));
console.log("  注记行：", await ev(`(() => { const n=document.getElementById("animPartNote"); return n?n.textContent.trim().slice(0,150):"无"; })()`));
console.log("  动画画布就绪：", await until(`(() => { const c=document.getElementById("animCanvas"); return c&&c.width>50&&c.height>50; })()`, 15000));
await wait(2500);
const clip = await boxOf("#animPoseBox .mesh-stage");
const f0ok = await shot("anim_frame0", clip) !== null;
await ev(`(() => { const s=document.getElementById("animFrame"); s.value="12"; s.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(2000);
console.log("  游标=12 后滑杆值：", await ev(`document.getElementById("animFrame").value`));
await shot("anim_frame12", clip);
await ev(`(() => { const s=document.getElementById("animFrame"); s.value="28"; s.dispatchEvent(new Event("input",{bubbles:true})); return 1; })()`);
await wait(2000);
await shot("anim_frame28", clip);
if (!f0ok) { console.log("  帧截图缺失，跳过像素差"); } else { const f0ok = true; const f0 = readFileSync(`${OUT}/anim_frame0.png`), f12 = readFileSync(`${OUT}/anim_frame12.png`), f28 = readFileSync(`${OUT}/anim_frame28.png`);
console.log("  帧间像素差：", `0vs12=${Buffer.compare(f0, f12) !== 0}, 12vs28=${Buffer.compare(f12, f28) !== 0}, 尺寸 ${f0.length}/${f12.length}/${f28.length}B`); }

console.log("== 4. 播放按钮与部件勾选 ==");
await ev(`(() => { const b=document.querySelector("#animPoseBox button"); b&&b.click(); return 1; })()`);
await wait(2500);
const played = await ev(`Number(document.getElementById("animFrame").value)`);
console.log("  播放 2.5s 后游标值：", played, played > 12 ? "（已自动步进）" : "（未动！）");
await ev(`(() => { const b=document.querySelector("#animPoseBox button"); if (b && b.textContent.includes("暂停")) b.click(); return 1; })()`);
await ev(`(() => { const c=[...document.querySelectorAll("#animPartPick input[type=checkbox]")]; if(c[1]) { c[1].checked=false; c[1].dispatchEvent(new Event("change",{bubbles:true})); } return 1; })()`);
await wait(1500);
console.log("  关掉一件后 meta：", await ev(`(() => { const m=document.querySelector("#animPoseBox .mesh-head, #animPoseBox p"); return m?m.textContent.trim().slice(0,120):"无"; })()`));
await ev(`(() => { const c=[...document.querySelectorAll("#animPartPick input[type=checkbox]")]; if(c[1]) { c[1].checked=true; c[1].dispatchEvent(new Event("change",{bubbles:true})); } return 1; })()`);
await wait(1200);
console.log("  恢复全开后 meta：", await ev(`(() => { const m=document.querySelector("#animPoseBox .mesh-head, #animPoseBox p"); return m?m.textContent.trim().slice(0,120):"无"; })()`));
console.log("  错误行：", await ev(`(() => { const e=document.getElementById("animPoseErr"); return e&&e.textContent.trim()?e.textContent.trim().slice(0,120):"(空=无错误)"; })()`));
ws.close();
console.log("== 验收脚本跑完 ==");
