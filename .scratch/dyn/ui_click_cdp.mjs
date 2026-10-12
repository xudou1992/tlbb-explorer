// 逐控件点击验收（第二版，选择器按 ui_survey 的真实 DOM 来）：
// 列表是 .row-item（缩略图 .thumb 不是 img），所以判「筛选生效」要数 .row-item 的条数，
// 判「点开有内容」要看右栏，而不是 body 里那行全局计数文案。
const targets = await (await fetch('http://127.0.0.1:9222/json')).json();
const page = targets.find(t => t.type === 'page' && (t.url || '').startsWith('http://tauri.localhost'));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
let id = 0;
const pend = new Map();
ws.onmessage = ev => { const m = JSON.parse(ev.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
const send = (method, params = {}) => new Promise(res => { const k = ++id; pend.set(k, res); ws.send(JSON.stringify({ id: k, method, params })); });
const expr = `
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const rows = () => document.querySelectorAll('.row-item').length;
  const thumbs = () => [...document.querySelectorAll('.row-item .thumb')]
    .filter(e => /url\\(/.test(getComputedStyle(e).backgroundImage || '')).length;
  const rep = { 起始行数: rows(), 起始有图行: thumbs() };
  const chip = t => [...document.querySelectorAll('button,.chip,[role=button],.filter,span,div')]
    .find(e => (e.children.length === 0 ? (e.textContent || '').trim() : '').startsWith(t));
  const fx = chip('特效');
  rep.找到特效筛选 = !!fx;
  if (fx) {
    fx.click();
    await sleep(1500);
    rep.点特效行数 = rows();
    rep.筛选生效 = rep.点特效行数 !== rep.起始行数 && rep.点特效行数 > 0;
    const all = chip('全部');
    if (all) { all.click(); await sleep(1500); rep.回全部行数 = rows(); }
  }
  const r0 = document.querySelector('.row-item');
  if (r0) {
    const name = (r0.querySelector('.t') || {}).textContent;
    r0.click();
    await sleep(2000);
    rep.点的行 = (name || '').trim().slice(0, 28);
    const aside = document.querySelector('aside,.detail,#detail,.panel,.right') || document.body;
    rep.右栏字数 = (aside.innerText || '').length;
    rep.右栏出现文件名 = /\\.(mesh|mtl|ani|tex|dds|tga|scene|pu|mdl|ske)\\b/i.test(aside.innerText || '');
    rep.右栏标题 = [...document.querySelectorAll('h1,h2,h3,h4,.title')]
      .map(e => (e.textContent || '').trim()).filter(x => x && x.length < 40).slice(0, 8);
  } else {
    rep.点的行 = '没有 .row-item';
  }
  rep.最终行数 = rows();
  return rep;
})()
`;
const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
console.log(JSON.stringify(r.result && r.result.value ? r.result.value : r, null, 1));
ws.close();
