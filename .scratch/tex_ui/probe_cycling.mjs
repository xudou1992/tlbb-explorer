const CDP = process.env.CDP_PORT ?? '9222';
const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
console.log('目标数：', list.filter(t=>t.type==='page').length, list.map(t=>t.url.slice(0,60)));
