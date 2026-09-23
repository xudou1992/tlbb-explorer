"""Probe: which directory prefixes hold .mesh / .mdl, so the buckets are data-driven."""
import collections
import io
import os

TREE = r"D:\TLGL\.scratch\out\tree"
OUT = r"D:\TLGL\.scratch\agent_impact_probe.txt"

c = collections.Counter()
leaf = collections.Counter()
for dp, _dn, names in os.walk(TREE):
    rel = os.path.relpath(dp, TREE).replace("\\", "/")
    if rel == ".":
        rel = ""
    for f in names:
        low = f.lower()
        if low.endswith(".mesh") or low.endswith(".mdl") or low.endswith(".ske"):
            ext = low[-5:] if low.endswith(".mdl") else low[-5:]
            ext = os.path.splitext(low)[1]
            parts = [p for p in rel.split("/") if p]
            c[("/".join(parts[:4]) or "(root)", ext)] += 1
            leaf[("/".join(parts[:5]) or "(root)", ext)] += 1

with io.open(OUT, "w", encoding="utf-8") as fh:
    fh.write("== prefix depth 4 ==\n")
    for (k, e), v in sorted(c.items()):
        fh.write("%-55s %-6s %6d\n" % (k, e, v))
    fh.write("\n== prefix depth 5 (leaf) ==\n")
    for (k, e), v in sorted(leaf.items()):
        fh.write("%-62s %-6s %6d\n" % (k, e, v))
print("ok")
