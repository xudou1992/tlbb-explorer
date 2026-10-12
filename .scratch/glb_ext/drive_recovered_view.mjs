// 用外部查看器台子（three.js 自己算蒙皮与动画，不加任何补丁）把「按 cfg 身份救回来的角色」
// 真渲染一遍：证明那 271 个 GLB 不是字节对了形状是垃圾，而是画得出人形。
// 用法：node drive_recovered_view.mjs  （需先在仓库根起 HTTP 服务、Chrome 带 --remote-debugging-port）
import { writeFileSync, mkdirSync } from 'node:fs';
const CDP = process.env.CDP_PORT ?? '9333';
const OUT = 'D:/TLGL/.scratch/glb_ext/shots_sidecar';
mkdirSync(OUT, { recursive: true });

const targets = JSON.parse(process.env.TARGETS ?? '[]'); // [{name, asset}]
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (!pages.length) { console.log('没有可连的页面'); process.exit(1); }
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise((res) => { const mid = ++id; pend.set(mid, (x) => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async (x) => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return 'ERR ' + JSON.stringify(r.exceptionDetails).slice(0, 200);
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await send('Page.enable', {}); await send('Runtime.enable', {});

for (const t of targets) {
  const url = `http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=${encodeURIComponent(t.asset)}&bones=1&view=front`;
  await send('Page.navigate', { url });
  await sleep(3500);
  let ready = false;
  for (let i = 0; i < 25; i++) {
    ready = await ev('!!window.__ready');
    if (ready) break;
    await sleep(700);
  }
  // 关键：台子只在 __shot() 里才 renderer.render，不调它就截图必然全黑（上一轮就是这样）。
  const info = await ev(`(async()=>{
    const i = window.__info || {};
    const clip = (i.clips && i.clips[0]) ? i.clips[0].name : null;
    const shotOk = clip && window.__shot ? window.__shot(clip, +(i.clips[0].dur * 0.4).toFixed(3)) : null;
    return JSON.stringify({
      ready: !!window.__ready, asset: i.asset, skinned: i.skinnedMeshes, verts: i.verts,
      joints: i.joints, box: i.box, clips: (i.clips||[]).slice(0,4),
      用了动作: clip, 摆姿后渲染: shotOk, 当前包围盒: window.__lastBox || null,
      hud: (document.getElementById('hud')?.textContent||'').trim().slice(0,160),
    });})()`);
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  const f = `${OUT}/${t.name}.png`;
  writeFileSync(f, Buffer.from(shot.data, 'base64'));
  console.log(`${t.name}  就绪=${ready}  截图=${f}`);
  console.log('   ', String(info).slice(0, 420));
}
ws.close();
