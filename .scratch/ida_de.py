#!/usr/bin/env python3
"""批量反编译：python ida_de.py 0x14060ec20 0x140299f90 ...  > 结果文件"""
import json
import subprocess
import sys

addrs = sys.argv[1:]
out = []
for a in addrs:
    args = {"addr": a, "include_addresses": False}
    open(".scratch/ida_args_tmp.json", "w", encoding="utf-8").write(json.dumps(args))
    r = subprocess.run([sys.executable, ".scratch/ida_call.py", "decompile",
                        ".scratch/ida_args_tmp.json", ".scratch/ida_dec_one.txt"],
                       capture_output=True, cwd="D:/TLGL")
    try:
        d = json.load(open(".scratch/ida_dec_one.txt", encoding="utf-8"))
        sc = d.get("structuredContent", d)
        txt = json.dumps(sc, ensure_ascii=False)
        # 反编译体一般在 content[0].text 或 structuredContent.code
        code = None
        for k in ("code", "c", "decompiled", "text"):
            if isinstance(sc, dict) and k in sc:
                code = sc[k]
                break
        if code is None:
            if isinstance(sc, dict) and "result" in sc:
                rr = sc["result"]
                if isinstance(rr, list) and rr and isinstance(rr[0], dict):
                    code = json.dumps(rr[0], ensure_ascii=False)
                else:
                    code = json.dumps(rr, ensure_ascii=False)
            else:
                code = txt
        out.append("/* ==== %s ==== */\n%s" % (a, code))
    except Exception as e:
        out.append("/* ==== %s 失败: %s ==== */\n%s" % (a, e, open(".scratch/ida_dec_one.txt", encoding="utf-8", errors="replace").read()[:600]))
print("\n\n".join(out))
