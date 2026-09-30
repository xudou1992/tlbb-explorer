#!/usr/bin/env python3
"""IDA Pro MCP 的裸 JSON-RPC 通道：本会话没注册 ida-pro 工具，只能自己发请求。

用法：
  python ida_rpc.py tools/list
  python ida_rpc.py tools/call '{"name":"find_regex","arguments":{"pattern":"EsSkeleton"}}'
会话 id 缓存在 .scratch/ida_session.txt，服务端重启后自动重来一遍。
"""
import json
import os
import sys
import urllib.request

URL = "http://127.0.0.1:13337/mcp"
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ida_session.txt")


def post(body, sid=None):
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json, text/event-stream")
    if sid:
        req.add_header("Mcp-Session-Id", sid)
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.headers.get("Mcp-Session-Id"), r.read().decode("utf-8", "replace")


def rpc(body, sid):
    _, text = post(body, sid)
    # 服务端可能用 SSE 分帧（data: {...}），统一抠出最后一段 JSON
    if text.lstrip().startswith("{"):
        return json.loads(text)
    chunks = [ln[5:].strip() for ln in text.splitlines() if ln.startswith("data:")]
    for c in reversed(chunks):
        try:
            return json.loads(c)
        except Exception:
            continue
    return {"raw": text[:2000]}


def session():
    sid = None
    if os.path.exists(CACHE):
        sid = open(CACHE, encoding="utf-8").read().strip() or None
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "qoder-cli", "version": "1"}}}
    try:
        new_sid, _ = post(init, sid)
    except Exception as e:
        print("连不上 IDA MCP（IDA 没开？13337 被占？）：%s" % e)
        sys.exit(2)
    sid = new_sid or sid
    if sid:
        open(CACHE, "w", encoding="utf-8").write(sid)
        try:
            post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
        except Exception:
            pass
    return sid


def main():
    method = sys.argv[1] if len(sys.argv) > 1 else "tools/list"
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    sid = session()
    if not sid:
        print("没有会话 id，服务端可能不接受匿名请求")
        sys.exit(2)
    resp = rpc({"jsonrpc": "2.0", "id": 2, "method": method, "params": params}, sid)
    if "error" in resp:
        sys.stderr.write("出错：%s\n" % json.dumps(resp["error"], ensure_ascii=False)[:800])
        sys.exit(1)
    out = resp.get("result", resp)
    txt = json.dumps(out, ensure_ascii=False)
    # 控制台是 GBK，中文和 \\x00 都会炸；一律写文件，屏幕上只报个数
    dest = os.environ.get("IDA_OUT")
    if dest:
        with open(dest, "w", encoding="utf-8") as f:
            f.write(txt)
        sys.stdout.write("WROTE %s %d chars\n" % (dest, len(txt)))
    else:
        lim = int(os.environ.get("IDA_OUT_CHARS", "6000"))
        sys.stdout.write(repr(txt[:lim]) + "\n")


if __name__ == "__main__":
    main()
