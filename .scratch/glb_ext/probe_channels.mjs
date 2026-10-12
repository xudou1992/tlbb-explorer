// 诊断「三份救回来的角色在查看器里三个时刻包围盒一模一样」：
// 把 GLB 里动画通道的目标名与场景节点名两边列出来比，看是不是通道没绑上骨头。
// three.js 对绑不上的通道是静默忽略的，所以 grow=1.00 看着像"没撕"，其实是"没动"。
import { writeFileSync } from 'node:fs';
const CDP = process.env.CDP_PORT ?? '9333';
const targets = JSON.parse(process.env.TARGETS ?? '[]');
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
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
const out = [];
for (const t of targets) {
  await send('Page.navigate', { url: `http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=${encodeURIComponent(t.asset)}&bones=0&view=three` });
  await sleep(2500);
  let ready = false;
  for (let i = 0; i < 25 && !ready; i++) { ready = await ev('!!window.__ready'); if (!ready) await sleep(700); }
  const r = await ev(`(()=>{
    const i = window.__info || {};
    const clip = (i.clips || [])[0];
    if (!clip) return JSON.stringify({err:'没有动作'});
    // 用台子留下的钩子做不到遍历，这里直接重读一次 GLB 的 JSON 块：
    // three 的 clip.tracks[].name 形如 "节点名.quaternion"，节点名对不上就不会动。
    return JSON.stringify({asset:i.asset, joints:i.joints, clip:clip.name, keys:clip.keys});
  })()`);
  const info = JSON.parse(String(r));
  const cmp = await ev(`(async()=>{
    const buf = await (await fetch(${JSON.stringify(t.asset)})).arrayBuffer();
    const dv = new DataView(buf);
    const jsonLen = dv.getUint32(12, true);
    const j = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 20, jsonLen)));
    const nodes = (j.nodes || []).map(n => n.name || '(无名)');
    const skin = (j.skins || [])[0];
    const joints = skin && skin.joints ? skin.joints.map(i => (j.nodes[i] || {}).name || '(无名)') : [];
    const chans = [];
    for (const a of (j.animations || [])) for (const c of a.channels || []) {
      const sam = (a.samplers || [])[c.sampler] || {};
      const tn = c.target && c.target.node;
      chans.push({ target: (j.nodes[tn] || {}).name || ('#' + tn), path: sam.path, anim: a.name });
    }
    const first = chans.filter(c => c.anim === ${JSON.stringify(info.clip || '')}).slice(0, 60);
    const nodeSet = new Set(nodes);
    const miss = first.filter(c => !nodeSet.has(c.target));
    const byPath = {}; for (const c of first) byPath[c.path] = (byPath[c.path] || 0) + 1;
    const named = nodes.filter(n => n && n !== '(无名)');
    return JSON.stringify({
      节点数: nodes.length, 有名节点: named.length, 蒙皮关节数: joints.length,
      该动作通道数: first.length, 通道按路径分布: byPath, 通道目标不在节点表里: miss.length,
      通道目标样例: [...new Set(first.map(c => c.target))].slice(0, 6),
      节点名样例: named.slice(0, 6),
      动画总条数: (j.animations || []).length, 网格数: (j.meshes || []).length,
      场景根: (j.scenes || []).map(s => (s.nodes || []).length),
    });
  })()`);
  console.log(t.name, JSON.stringify(cmp, null, 1).replace(/\n\s*/g, ' '));
  out.push({ name: t.name, info, cmp: JSON.parse(String(cmp)) });
}
writeFileSync('D:/TLGL/.scratch/glb_ext/shots_sidecar/channel_probe.json', JSON.stringify(out, null, 2));
ws.close();
