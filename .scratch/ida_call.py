#!/usr/bin/env python3
"""调 IDA 工具：参数写在文件里，避开 Windows 命令行转义地狱。

用法：python ida_call.py <工具名> <参数json文件> [输出文件]
参数文件内容形如 {"pattern":"EsSkeleton","limit":40}
"""
import json
import os
import subprocess
import sys

name = sys.argv[1]
args = json.load(open(sys.argv[2], encoding="utf-8")) if len(sys.argv) > 2 else {}
out = sys.argv[3] if len(sys.argv) > 3 else ".scratch/ida_out.txt"
env = dict(os.environ, IDA_OUT=out, PYTHONIOENCODING="utf-8")
r = subprocess.run([sys.executable, ".scratch/ida_rpc.py", "tools/call",
                    json.dumps({"name": name, "arguments": args}, ensure_ascii=False)],
                   capture_output=True, cwd="D:/TLGL", env=env)
sys.stdout.write(r.stdout.decode("utf-8", "replace")[:200] + "\n")
err = r.stderr.decode("utf-8", "replace").strip()
if err:
    sys.stdout.write("stderr: " + err[:300] + "\n")
