#!/usr/bin/env python3
"""IDA Pro MCP 的最小 JSON-RPC 客户端（一次握手、反复调工具）。

用法：
  python mcp.py tools                     # 列工具名
  python mcp.py call find_regex '{"pattern":"Copyright 2013"}'
  python mcp.py call decompile '{"address":"0x14072f000"}' > out.c
端口从 IDA 的 instances/*.json 现读，不写死。
"""
import glob
import json
import os
import sys
import urllib.request

INST = glob.glob(os.path.expandvars(
    r"C:\Users\Administrator\AppData\Roaming\Hex-Rays\IDA Pro\mcp\instances\instance_*.json"))
PORT = 13337
if INST:
    PORT = json.load(open(INST[-1], encoding="utf-8")).get("port", PORT)
URL = f"http://127.0.0.1:{PORT}/mcp"
SID = None


def post(method, params=None, mid=1, notify=False):
    global SID
    body = {"jsonrpc": "2.0", "id": mid, "method": method} if not notify else \
           {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **({"Mcp-Session-Id": SID} if SID else {}),
    })
    with urllib.request.urlopen(req, timeout=600) as r:
        sid = r.headers.get("Mcp-Session-Id")
        if sid:
            SID = sid
        raw = r.read().decode("utf-8", "replace")
    # 服务端可能回 SSE（"data: {...}" 若干行），取最后一个 JSON 对象
    obj = None
    for line in raw.splitlines():
        if line.startswith("data: "):
            raw = line[6:]
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                pass
    if obj is None:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return obj


def init():
    post("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "qoder-scratch", "version": "1"},
    }, mid=1)
    post("notifications/initialized", notify=True)


def call(tool, args):
    init()
    r = post("tools/call", {"name": tool, "arguments": args}, mid=2)
    if "error" in r:
        return f"ERROR {r['error']}"
    out = r.get("result", {})
    c = out.get("content") or []
    txt = "\n".join(x.get("text", "") for x in c if x.get("type") == "text")
    return txt or json.dumps(out, ensure_ascii=False)[:4000]


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "tools"
    if what == "tools":
        init()
        r = post("tools/list", {}, mid=2)
        names = [t["name"] for t in r.get("result", {}).get("tools", [])]
        print(len(names), "个工具：", ", ".join(names))
    elif what == "call":
        print(call(sys.argv[2], json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}))
