// 为什么「剔掉无记录骨」挪不动槽位？直接看页面里骨架与 JOINTS_0 到底是什么。
const CDP = process.env.CDP_PORT || '9227';
const list = await (await fetch('http://127.0.0.1:' + CDP + '/json/list')).json();
const pages = list.filter(t => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
const pend = new Map(); let id = 0;
ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result ?? m); pend.delete(m.id); } });
await new Promise(r => ws.addEventListener('open', r, { once: true }));
const send = (m, p) => new Promise(res => { const mid = ++id; pend.set(mid, x => res(x.result ?? x)); ws.send(JSON.stringify({ id: mid, method: m, params: p })); });
const ev = async x => { const r = await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true });
  if (r && r.exceptionDetails) return 'ERR ' + JSON.stringify(r.exceptionDetails).slice(0, 300);
  return r && Object.prototype.hasOwnProperty.call(r, 'value') ? r.value : (r?.result?.value); };
await send('Page.enable', {}); await send('Runtime.enable', {});
const ASSET = process.env.ASSET || '/.scratch/glb_after_gate/m_f8e9433000036a9c.glb';
await send('Page.navigate', { url: 'http://127.0.0.1:8765/.scratch/glb_ext/view.html?asset=' + encodeURIComponent(ASSET) + '&bones=0&view=three&_=' + Date.now() });
await new Promise(r => setTimeout(r, 2600));
for (let i = 0; i < 25 && !(await ev('!!window.__ready')); i++) await new Promise(r => setTimeout(r, 700));
const out = await ev('(function(){' +
  'var miss2=["bip01_pelvis","bip01_spine","bip01_spine1","bip01_head","bip01_footsteps","bip01_l_clavicle","bip01_l_forearm","bip01_l_calf","bip01_l_finger0","bip01_r_clavicle","bip01_r_forearm","bip01_r_calf","bip01_r_finger0","bone39","bone49","bone59","bone69","bone79","bone89"];' +
  'return JSON.stringify(window.__jointDiag(miss2));})()');
console.log(String(out).slice(0, 1600));
ws.close();
