# -*- coding: utf-8 -*-
"""CDP 界面审计:给每个按钮查 click 监听器,找「点开无反应」的死按钮。"""
import json, time, sys, os
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY'):
    os.environ.pop(k, None)
os.environ['NO_PROXY'] = '127.0.0.1,localhost'
import websocket

def find_page():
    import urllib.request
    req = urllib.request.Request('http://127.0.0.1:9222/json')
    pages = json.load(urllib.request.urlopen(req, timeout=5))
    for p in pages:
        if p.get('type') == 'page':
            return p
    raise SystemExit('no page target')

class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=10, suppress_origin=True)
        self.i = 0
        self.pending = {}
    def send(self, method, params=None):
        self.i += 1
        i = self.i
        self.ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == i:
                if 'error' in msg:
                    raise RuntimeError(json.dumps(msg['error']))
                return msg.get('result', {})
    def eval_js(self, expr):
        r = self.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True,
                                           'awaitPromise': True})
        if 'exceptionDetails' in r:
            return {'__exception': r['exceptionDetails'].get('exception', {}).get('description', '?')}
        return r.get('result', {}).get('value')

    def listeners_of(self, expr):
        """给一个返回节点对象的表达式查 click 监听器。"""
        r = self.send('Runtime.evaluate', {'expression': expr, 'returnByValue': False})
        if 'result' not in r or 'objectId' not in r['result']:
            return None
        oid = r['result']['objectId']
        try:
            ls = self.send('DOMDebugger.getEventListeners', {'objectId': oid})['listeners']
            return [l['type'] for l in ls]
        except Exception:
            return None

def main():
    page = find_page()
    c = CDP(page['webSocketDebuggerUrl'])
    c.send('Runtime.enable')
    c.send('DOM.enable')

    # 注入错误捕获
    c.eval_js("window.__errs=[];window.addEventListener('error',e=>__errs.push('ERR:'+e.message+':'+e.lineno));"
              "window.addEventListener('unhandledrejection',e=>__errs.push('REJ:'+String(e.reason)));")

    # 1) 枚举所有可见按钮:序号、id、文案、所在区块
    buttons = c.eval_js("""
      JSON.stringify([...document.querySelectorAll('button')].map((b,i)=>({
        i, id: b.id||'', text: b.textContent.trim().slice(0,14),
        disabled: b.disabled,
        hidden: !b.offsetParent && getComputedStyle(b).display==='none',
        view: b.closest('#browseView') ? 'browse' : (b.closest('#assetsView') ? 'assets' : 'common'),
      })))
    """)
    buttons = json.loads(buttons)
    report = []

    # 2) 对每个可见、未禁用按钮查 click 监听器(自身 + 是否命中委托)
    for b in buttons:
        if b['hidden']:
            continue
        expr = f"document.querySelectorAll('button')[{b['i']}]"
        own = c.listeners_of(expr)
        # 委托检测:沿祖先找监听(click 委托常见挂法)
        delegated = c.eval_js(f"""
          (() => {{
            const el = document.querySelectorAll('button')[{b['i']}];
            const hits = [];
            for (let n = el; n && n !== document.documentElement; n = n.parentElement) {{
              const tag = n.id ? '#'+n.id : (n.className ? '.'+String(n.className).split(' ')[0] : n.tagName);
              hits.push(tag);
            }}
            return hits.join('>');
          }})()
        """)
        report.append({**b, 'own_click': bool(own and 'click' in own), 'events': own, 'path': delegated})

    print(json.dumps({
        'page': page['title'],
        'buttons': report,
    }, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    main()
