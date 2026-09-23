"""Minimal stdio JSON-RPC client for the running IDA Pro MCP server (fallback when the
ida_pro MCP tools are not registered in this session).

usage: python idac.py <tool_name> '<json-args>'   |   python idac.py tools/list
"""
import json
import re
import sys
import urllib.request

BASE = 'http://127.0.0.1:13337/mcp'
INST = r'C:\Users\Administrator\AppData\Roaming\Hex-Rays\IDA Pro\mcp\instances\instance_13337.json'
HEAD = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}


def post(method, params=None, mid=1):
    body = {'jsonrpc': '2.0', 'id': mid, 'method': method}
    if params is not None:
        body['params'] = params
    req = urllib.request.Request(BASE, data=json.dumps(body).encode(), headers=HEAD, method='POST')
    with urllib.request.urlopen(req, timeout=600) as r:
        sid = r.headers.get('Mcp-Session-Id')
        raw = r.read().decode('utf-8', 'replace')
        ct = r.headers.get('Content-Type', '')
    txt = raw
    if 'event-stream' in ct:
        m = re.findall(r'^data: (.*)$', raw, re.M)
        txt = m[-1] if m else raw
    return json.loads(txt) if txt.strip() else {}, sid


def session():
    r, sid = post('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                'clientInfo': {'name': 'qoder-cli', 'version': '1'}})
    HEAD['Mcp-Session-Id'] = sid or ''
    try:
        req = urllib.request.Request(BASE, data=json.dumps(
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'}).encode(),
            headers=HEAD, method='POST')
        urllib.request.urlopen(req, timeout=60).read()
    except Exception as e:
        print('note: initialized notify failed:', e, file=sys.stderr)
    return r


def call(tool, args):
    session()
    r, _ = post('tools/call', {'name': tool, 'arguments': args}, mid=2)
    if 'error' in r:
        return {'error': r['error']}
    out = r.get('result', {})
    txt = '\n'.join(c.get('text', '') for c in out.get('content', []))
    try:
        return json.loads(txt)
    except Exception:
        return {'text': txt}


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'tools/list':
        session()
        r, _ = post('tools/list', {}, mid=2)
        print('\n'.join(t['name'] for t in r['result']['tools']))
    else:
        tool = sys.argv[1]
        args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        print(json.dumps(call(tool, args), ensure_ascii=False)[:20000])
