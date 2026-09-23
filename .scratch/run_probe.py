import subprocess, os

exe = r"D:\TLGL\.scratch\rc3\debug\tlbb-shell.exe"
if not os.path.exists(exe):
    # fall back to the in-tree debug output
    alt = r"D:\TLGL\tlbb-explorer\app\src-tauri\target\debug\tlbb-shell.exe"
    exe = alt if os.path.exists(alt) else exe

env = dict(os.environ)
env["TLBB_ROOT"] = r"D:\TLGL"
env["TLBB_DB"] = r"D:\TLGL\.scratch\resources.db"

p = subprocess.run([exe, "--probe", "曹霜"],
                   capture_output=True, cwd=r"D:\TLGL",
                   env=env, timeout=600)

out = b""
for enc in ("utf-8", "gbk"):
    try:
        out = p.stdout.decode(enc)
        break
    except Exception:
        continue
else:
    out = p.stdout.decode("utf-8", "replace")

err = p.stderr.decode("utf-8", "replace")

with open(r"D:\TLGL\.scratch\probe_ref_out.txt", "w", encoding="utf-8") as f:
    f.write(f"exe={exe}\nexit={p.returncode}\n--- stdout ---\n{out}\n--- stderr ---\n{err}\n")
print("done")
