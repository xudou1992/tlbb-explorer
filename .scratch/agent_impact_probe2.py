"""Probe 2: name prefixes inside each bucket, to split monster/pet/player/weapon reliably."""
import collections
import io
import os
import re

TREE = r"D:\TLGL\.scratch\out\tree"
OUT = r"D:\TLGL\.scratch\agent_impact_probe2.txt"

mdl, mesh = [], []
for dp, _dn, names in os.walk(TREE):
    rel = os.path.relpath(dp, TREE).replace("\\", "/")
    for f in names:
        low = f.lower()
        p = (rel + "/" + f) if rel != "." else f
        if low.endswith(".mdl"):
            mdl.append(p)
        elif low.endswith(".mesh"):
            mesh.append(p)


def stems(lst):
    return [os.path.basename(p)[: -len(os.path.splitext(p)[1])] for p in lst]


def prefix_counts(lst, words=2):
    c = collections.Counter()
    for s in stems(lst):
        parts = s.lower().split("_")
        if parts[0].startswith("w") and parts[0][1:].isdigit():
            parts = parts[1:]
        c["_".join(parts[:words])] += 1
    return c


fh = io.open(OUT, "w", encoding="utf-8")
fh.write("MDL total %d   MESH total %d\n\n" % (len(mdl), len(mesh)))
for label, base in [("MDL", mdl), ("MESH", mesh)]:
    fh.write("== %s by top-level bucket ==\n" % label)
    c = collections.Counter()
    for p in base:
        parts = p.split("/")
        if parts[0] == "data" and parts[1] == "source" and len(parts) > 3:
            k = "/".join(parts[:4])
        elif len(parts) > 2:
            k = "/".join(parts[:2])
        else:
            k = parts[0]
        c[k] += 1
    for k, v in c.most_common():
        fh.write("  %-40s %5d\n" % (k, v))
    fh.write("\n")

fh.write("== quest/ name prefixes (2 words), MESH ==\n")
q = [p for p in mesh if p.startswith("data/source/npc/quest/")]
for k, v in prefix_counts(q, 2).most_common(30):
    fh.write("  %-32s %5d\n" % (k, v))
fh.write("\n== quest/ name prefixes (2 words), MDL ==\n")
qm = [p for p in mdl if p.startswith("data/source/npc/quest/")]
for k, v in prefix_counts(qm, 2).most_common(30):
    fh.write("  %-32s %5d\n" % (k, v))
fh.write("\n== npc/model name prefixes ==\n")
for k, v in prefix_counts([p for p in mesh if p.startswith("data/source/npc/model/")], 2).most_common(15):
    fh.write("  %-32s %5d\n" % (k, v))
fh.write("\n== player ==\n")
for k, v in prefix_counts([p for p in mesh if p.startswith("data/source/player/")], 2).most_common(15):
    fh.write("  %-32s %5d\n" % (k, v))
fh.write("\n== wuqi / toukui / guajian / changjingdaoju / dynamic sample ==\n")
for d in ["wuqi", "toukui", "guajian", "changjingdaoju", "dynamic"]:
    ps = [p for p in mesh if ("/npc/%s/" % d) in p]
    fh.write("  %s: %d e.g. %s\n" % (d, len(ps), ps[:2]))
fh.write("\n== mobile_maps_source sample ==\n")
mp = [p for p in mesh if p.startswith("mobile_maps_source/")]
fh.write("  count %d e.g. %s\n" % (len(mp), mp[:3]))
for k, v in prefix_counts(mp, 2).most_common(15):
    fh.write("  %-32s %5d\n" % (k, v))
fh.write("\n== effect sample ==\n")
ep = [p for p in mesh if p.startswith("data/effect/")]
fh.write("  count %d e.g. %s\n" % (len(ep), ep[:3]))
fh.close()
print("ok")
