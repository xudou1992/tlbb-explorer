import subprocess, os, time

EXE = r"D:\TLGL\.scratch\rc3\debug\tlbb-shell.exe"
ENV = dict(os.environ)
ENV["TLBB_ROOT"] = r"D:\TLGL"
ENV["TLBB_DB"] = r"D:\TLGL\.scratch\resources.db"

t0 = time.time()
p = subprocess.run([EXE, "--probe", "验收"], capture_output=True, cwd=r"D:\TLGL",
                   env=ENV, timeout=900)
wall = time.time() - t0
try:
    o = p.stdout.decode("utf-8")
except Exception:
    o = p.stdout.decode("gbk", "replace")
e = p.stderr.decode("utf-8", "replace")

# 只取 M1 验收段 + 首尾
i = o.find("模型组成（M1 验收）")
m1 = o[i:] if i >= 0 else "(未找到 M1 验收段)\n" + o[-800:]
head = o[:o.find("\n全部读取") if "\n全部读取" in o else 120]
out = "exit=%d wall=%.2fs\n\n%s\n\n--- stderr ---\n%s" % (p.returncode, wall, m1, e[:300])
open(r"D:\TLGL\.scratch\m1_accept.txt", "w", encoding="utf-8").write(out)
print("done")
