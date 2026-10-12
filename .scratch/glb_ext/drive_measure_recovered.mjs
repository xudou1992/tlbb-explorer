// 量「骨线乱飘」到底是不是撕：对同一份 GLB 调台子的 __measure(clip, [0, 半, 尾])，
// 看包围盒相对 bind 涨了几倍（grow）、中心漂了多少（drift）。
// 判据沿用 10-09 那次：用**边长比**而不是位移，位移小不代表没撕。
import { writeFileSync, mkdirSync } from 'node:fs';
const CDP = process.env.CDP_PORT ?? '9333';
const OUT = 'D:/TLGL/.scratch/glb_ext/shots_sidecar';
mkdirSync(OUT, { recursive: true });
const targets = JSON.parse(process.env.TARGETS ?? '[]');
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter((t) => t.type === 'page' && t.webSocketDebuggerUrl);
if (!pages.length) { console.log('没有页面'); process.exit(1); }
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

const rows = [];
for (const t of targets) {
  await send('Page.navigate', { url: `http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=${encodeURIComponent(t.asset)}&bones=0&view=three` });
  await sleep(3000);
  let ready = false;
  for (let i = 0; i < 25 && !ready; i++) { ready = await ev('!!window.__ready'); if (!ready) await sleep(700); }
  const r = await ev(`(()=>{
    const i = window.__info || {};
    const clips = (i.clips || []).slice(0, 4);
    const out = [];
    for (const c of clips) {
      const times = [0, +(c.dur / 2).toFixed(3), +c.dur.toFixed(3)];
      const m = window.__measure ? window.__measure(c.name, times) : { error: '没有 __measure' };
      out.push(m);
    }
    return JSON.stringify({ asset: i.asset, skinned: i.skinnedMeshes, verts: i.verts,
      joints: i.joints, bindSpan: (i.box ? null : null), results: out, error: window.__error || null });
  })()`);
  const j = JSON.parse(String(r));
  console.log(`${t.name}: 蒙皮网格 ${j.skinned} · 顶点 ${j.verts} · 关节 ${j.joints} · 报错 ${j.error || '无'}`);
  for (const m of j.results || []) {
    if (!m || m.error) { console.log('   ', JSON.stringify(m)); continue; }
    const g = m.rows.map((x) => x.grow).filter((v) => Number.isFinite(v));
    const d = m.rows.map((x) => x.drift).filter((v) => Number.isFinite(v));
    console.log(`    ${m.clip}: 时长 ${m.duration}s · 包围盒相对 bind 涨到 ${Math.max(...g).toFixed(2)}×` +
                ` · 中心漂 ${(Math.max(...d) * 100).toFixed(1)}% 跨度 · 逐帧 ${m.rows.map((x) => x.grow + '/' + x.drift).join('  ')}`);
    rows.push({ name: t.name, clip: m.clip, grow: Math.max(...g), drift: Math.max(...d), span: m.bindSpan });
  }
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(`${OUT}/量_${t.name}.png`, Buffer.from(shot.data, 'base64'));
}
writeFileSync(`${OUT}/measure_recovered.json`, JSON.stringify(rows, null, 2));
console.log('\n汇总：最大涨缩 ' + Math.max(...rows.map((x) => x.grow)).toFixed(2) +
            '× · 最大漂移 ' + (Math.max(...rows.map((x) => x.drift)) * 100).toFixed(1) + '% 跨度');
ws.close();
