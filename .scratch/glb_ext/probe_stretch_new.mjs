// 新配对这批的「两边数字对得上」核对：查看器里 three.js 自己算蒙皮，逐帧量边长拉伸；
// 同一份网格 + 同一条动作再用 app 侧 stretch_probe 量一遍，数字对上才算导出与实现一致。
const CDP = process.env.CDP_PORT ?? '9333';
const ASSET = process.env.ASSET;
const CLIP = process.env.CLIP;
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const pages = list.filter(t => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise(res => { const mid = ++id; pend.set(mid, x => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async x => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : r; };
await send('Page.enable', {}); await send('Runtime.enable', {});
await send('Page.navigate', { url: `http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=${encodeURIComponent(ASSET)}&bones=0&view=front` });
await new Promise(r => setTimeout(r, 9000));
for (let i = 0; i < 20; i++) { if (await ev('!!window.__ready')) break; await new Promise(r => setTimeout(r, 700)); }
const has = await ev('typeof window.__stretch');
console.log('__stretch 可用:', has, '| ready:', await ev('!!window.__ready'), '| error:', String(await ev('JSON.stringify(window.__error||null)')).slice(0,200));
const times = JSON.parse(process.env.TIMES ?? '[0.1,0.2,0.3]');
for (const tt of times) {
  const out = await ev(`(async()=>{
    const r = await window.__stretch(${JSON.stringify(CLIP)}, ${tt});
    return JSON.stringify(r);
  })()`);
  console.log('查看器 t=' + tt + ' 量得:', String(out).slice(0, 300));
}
ws.close();
