import subprocess, os, re

EXE = r"D:\TLGL\.scratch\rc3\debug\view.exe"
ENV = dict(os.environ)

def run(args):
    p = subprocess.run([EXE] + args, capture_output=True, cwd=r"D:\TLGL",
                       env=ENV, timeout=600)
    return p.stdout.decode("utf-8", "replace")

parts = []
for nm, size in [("w1351_npc_biaoche3.mdl", 4728), ("w1351_monster_xiyuqiezei.mdl", 568)]:
    o = run(["--name=" + nm, "--dump=%d" % size])
    hexes = []
    for line in o.splitlines():
        m = re.match(r"\s*[0-9a-f]{6}\s+((?:[0-9a-f]{2} ){1,16})", line)
        if m:
            hexes.extend(int(x, 16) for x in m.group(1).split())
    data = bytes(hexes)
    # printable runs >= 4
    runs = re.findall(rb"[ -~]{4,}", data)
    parts.append("=== %s (%d bytes hex, %d runs) ===\n%s" % (
        nm, len(data), len(runs),
        "\n".join("  " + r.decode("ascii", "replace") for r in runs)))

with open(r"D:\TLGL\.scratch\mdl_strings.txt", "w", encoding="utf-8") as f:
    f.write("\n\n".join(parts))
print("done")
