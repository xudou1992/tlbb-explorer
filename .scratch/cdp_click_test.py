# -*- coding: utf-8 -*-
"""CDP 动态点击审计:真实点击每个安全按钮,记录效果与报错。
有写盘副作用的按钮(确认贴图/导出/清除覆盖)只记录不点。"""
import json, os, time
for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY'):
    os.environ.pop(k, None)
os.environ['NO_PROXY'] = '127.0.0.1,localhost'
import urllib.request
import websocket

def find_page():
    pages = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json', timeout=5))
    for p in pages:
        if p.get('type') == 'page':
            return p
    raise SystemExit('no page')

class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=15, suppress_origin=True)
        self.i = 0
    def send(self, method, params=None):
        self.i += 1
        i = self.i
        self.ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
        deadline = time.time() + 15
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get('id') == i:
                if 'error' in msg:
                    raise RuntimeError(json.dumps(msg['error']))
                return msg.get('result', {})
        raise TimeoutError(method)
    def js(self, expr, wait=False):
        r = self.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True,
                                           'awaitPromise': wait, 'userGesture': True})
        if 'exceptionDetails' in r:
            return {'__exception': r['exceptionDetails'].get('exception', {}).get('description', '?')[:200]}
        return r.get('result', {}).get('value')
    def click(self, selector, idx=0):
        """JS click:触发 onclick 与 click listener。返回异常信息(无则 None)。"""
        return self.js(f"""
          (() => {{
            const el = document.querySelectorAll('{selector}')[{idx}];
            if (!el) return 'NOT_FOUND';
            if (el.disabled) return 'DISABLED';
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return 'ZERO_RECT';
            el.click();
            return 'CLICKED';
          }})()
        """)

def snap(c):
    return c.js("""JSON.stringify({
      progress: document.getElementById('progressText')?.textContent||'',
      count: document.getElementById('count')?.textContent||'',
      treeTitle: document.getElementById('treeTitle')?.textContent||'',
      treeRows: document.querySelectorAll('.tree-row').length,
      assetRows: document.querySelectorAll('.row-item').length,
      dName: document.getElementById('dName')?.textContent||document.getElementById('bfName')?.textContent||'',
      browseHidden: document.getElementById('browseView')?.hidden,
      assetsHidden: document.getElementById('assetsView')?.hidden,
      mapsHidden: document.getElementById('maps')?.hidden,
      healthHidden: document.getElementById('health')?.hidden,
      meshCanvas: !!document.getElementById('meshCanvas'),
      errCount: (window.__errs||[]).length,
    })""")

def main():
    page = find_page()
    c = CDP(page['webSocketDebuggerUrl'])
    c.send('Runtime.enable')
    c.js("window.__errs=[];window.addEventListener('error',e=>__errs.push('ERR:'+e.message+'@'+e.lineno));"
         "window.addEventListener('unhandledrejection',e=>__errs.push('REJ:'+String(e.reason).slice(0,150)));")
    results = []

    def probe(name, selector, idx=0, settle=0.7, expect=None):
        before = json.loads(snap(c))
        r = c.click(selector, idx)
        time.sleep(settle)
        after = json.loads(snap(c))
        errs = c.js("(window.__errs||[]).slice(-5)")
        changed = {k: (before.get(k), after.get(k)) for k in before
                   if k != 'errCount' and before.get(k) != after.get(k)}
        results.append({'name': name, 'click': r, 'changed': changed,
                        'newErrs': errs if len(errs or []) else None})

    # ---- 资产视图 ----
    probe('资产: 清空筛选', '#reset')
    probe('资产: 看未命名资产', '#unnamed')      # 切到 unnamed 视图
    probe('资产: 看未命名资产(再点回来)', '#unnamed')
    probe('资产: 类型chip 全部', '#kinds button', 0)
    probe('资产: 类型chip 第2个', '#kinds button', 1)
    probe('资产: 完整程度chip 全部', '#grades button', 0)
    probe('资产: 列表第1行', '.row-item', 0)
    if json.loads(snap(c))['assetRows'] > 1:
        probe('资产: 列表第2行', '.row-item', 1)
    probe('资产: 套上看看(第1个候选)', '#texCand button', 0)
    # ---- 地图 ----
    probe('顶栏: 地图', '#openMap', settle=1.2)
    probe('地图: 灰模', '#modeGray', settle=1.0)
    probe('地图: 俯视量测', '#modeTop', settle=1.0)
    probe('地图: 返回', '#closeMap', settle=0.8)
    # ---- 库状态 ----
    probe('顶栏: 库状态', '#openHealth', settle=1.0)
    probe('库状态: 返回', '#closeHealth', settle=0.8)
    # ---- 浏览视图 ----
    probe('顶栏: 切到浏览', '#tabBrowse', settle=0.8)
    probe('浏览: pak卡片第1个', '.pakcard', 0, settle=2.5)
    n_tree = json.loads(snap(c))['treeRows']
    if n_tree:
        probe('浏览: 树第1行(目录)', '.tree-row', 0, settle=1.0)
        probe('浏览: 树第2行', '.tree-row', 1, settle=1.0)
    probe('浏览: 导出按钮(整包)', '#exportGo', settle=1.5)
    # 回资产,恢复用户原来看到的视图
    probe('顶栏: 切回资产', '#tabAssets', settle=0.8)

    print(json.dumps(results, ensure_ascii=False, indent=1))

if __name__ == '__main__':
    main()
