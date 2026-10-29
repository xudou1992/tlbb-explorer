#!/usr/bin/env python3
"""调 IDA MCP 工具：python idad.py <tool> '<json参数>' [输出文件]

控制台是 GBK，一律把原始响应写文件，屏幕上只打截断后的 JSON。
"""
import json
import os
import subprocess
import sys

tool = sys.argv[1]
args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
out = sys.argv[3] if len(sys.argv) > 3 else ".scratch/ida_last.json"
env = dict(os.environ, IDA_OUT=out, PYTHONIOENCODING="utf-8")
r = subprocess.run(
    [sys.executable, ".scratch/ida_rpc.py", "tools/call",
     json.dumps({"name": tool, "arguments": args}, ensure_ascii=False)],
    cwd="D:/TLGL", env=env, capture_output=True)
if r.returncode:
    print("调用失败:", r.stderr.decode("utf-8", "replace")[:400])
    sys.exit(1)
try:
    d = json.load(open(out, encoding="utf-8"))
except Exception as e:
    print("解析失败", e, open(out, encoding="utf-8", errors="replace").read()[:300])
    sys.exit(1)
sc = d.get("structuredContent", d)
txt = json.dumps(sc, ensure_ascii=False)
print(txt[: int(os.environ.get("IDAD_CHARS", "2500"))])
