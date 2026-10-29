// 一次性诊断：导航到 view.html，把控制台输出、异常、hud 文本都倒出来。
const CDP = process.env.CDP_PORT ?? '9227';
const url = process.argv[2];
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const events = [];
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails;
    events.push('EXC ' + (d.exception?.description ?? d.text ?? '').slice(0, 400));
  }
  if (m.method === 'Log.entryAdded') events.push('LOG ' + m.params.entry.text.slice(0, 300));
  if (m.method === 'Runtime.consoleAPICalled') {
    events.push('CON ' + m.params.args.map((a) => a.value ?? a.description ?? a.type).join(' ').slice(0, 300));
  }
});
const send = (method, params = {}) => new Promise((res) => {
  const mid = ++id;
  const on = (e) => { const x = JSON.parse(e.data); if (x.id === mid) { ws.removeEventListener('message', on); res(x.result); } };
  ws.addEventListener('message', on);
  ws.send(JSON.stringify({id: mid, method, params}));
});
await new Promise((r) => ws.addEventListener('open', r, {once: true}));
await send('Page.enable'); await send('Runtime.enable'); await send('Log.enable');
await send('Page.navigate', {url});
await new Promise((r) => setTimeout(r, 12000));
const ev = async (expr) => (await send('Runtime.evaluate', {expression: expr, returnByValue: true}))?.result?.value;
console.log('ready   =', await ev('String(window.__ready)'));
console.log('error   =', await ev('window.__error||""'));
console.log('info    =', await ev('JSON.stringify(window.__info||null)'));
console.log('hud     =', await ev('(document.getElementById("hud")||{}).textContent||""'));
console.log('webgl   =', await ev(`(()=>{const c=document.createElement('canvas');const g=c.getContext('webgl2')||c.getContext('webgl');return g?g.getParameter(g.VERSION)+' | '+g.getParameter(g.RENDERER):'无 WebGL';})()`));
console.log(events.length ? '\n--- 事件 ---\n' + events.join('\n') : '\n（无控制台事件）');
ws.close();
