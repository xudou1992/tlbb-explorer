import subprocess, os

EXE = r"D:\TLGL\.scratch\rc3\debug\view.exe"
ENV = dict(os.environ)

def run(args):
    p = subprocess.run([EXE] + args, capture_output=True, cwd=r"D:\TLGL",
                       env=ENV, timeout=600)
    try:
        o = p.stdout.decode("utf-8")
    except Exception:
        o = p.stdout.decode("gbk", "replace")
    return p.returncode, o, p.stderr.decode("utf-8", "replace")

samples = ["w1351_pets_bingcan_b2.mdl", "w1351_npc_biaoche3.mdl", "w1351_monster_xiyuqiezei.mdl"]
parts = []
for nm in samples:
    rc, o, e = run(["--name=" + nm, "--dump=256"])
    parts.append("=== %s (rc=%d) ===\n%s\nstderr:%s" % (nm, rc, o, e[:300]))

with open(r"D:\TLGL\.scratch\mdl_bytes.txt", "w", encoding="utf-8") as f:
    f.write("\n\n".join(parts))
print("done")
