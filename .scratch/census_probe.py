import subprocess, os, re, json

exe = r"D:\TLGL\.scratch\rc3\debug\tlbb-shell.exe"
env = dict(os.environ)
env["TLBB_ROOT"] = r"D:\TLGL"
env["TLBB_DB"] = r"D:\TLGL\.scratch\resources.db"

# The workbench has a startup census; ask for it explicitly. If the flag is unknown the
# binary will fall back to usage, which is itself informative.
probes = []

for arg in (["--grade-census"], ["--grades"], ["--probe", "__CENSUS__"]):
    try:
        p = subprocess.run([exe] + arg, capture_output=True, cwd=r"D:\TLGL",
                           env=env, timeout=900)
    except Exception as e:
        probes.append((arg, "TIMEOUT/ERR %s" % e))
        continue
    try:
        out = p.stdout.decode("utf-8")
    except Exception:
        out = p.stdout.decode("gbk", "replace")
    err = p.stderr.decode("utf-8", "replace")
    probes.append((arg, "exit=%s\n--- out ---\n%s\n--- err ---\n%s" % (p.returncode, out[-4000:], err[-2000:])))

with open(r"D:\TLGL\.scratch\census_probe.txt", "w", encoding="utf-8") as f:
    for a, r in probes:
        f.write("=== %s ===\n%s\n\n" % (" ".join(a), r))
print("done")
