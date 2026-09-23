import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
con = sqlite3.connect(r"file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
res = {}
for h, p, n, e in con.execute("select hash, path, name, ext from resources"):
    cur = res.get(h)
    if cur is None or (not cur[0] and p):
        res[h] = (p or "", n or "", e or "")
members = defaultdict(list)
for gid, h, role in con.execute("select gid, hash, role from amembers"):
    members[gid].append((role, h))
refs_by = defaultdict(list)
for fh, n, k, th in con.execute("select from_hash, name, kind, to_hash from refs"):
    refs_by[fh].append((n, k, th))
c = Counter()
for gid, stem, kind, n_mesh, n_ske, n_mtl in con.execute(
        "select id, stem, kind, n_mesh, n_ske, n_mtl from agroups"):
    rows = sorted([(ro, res.get(h, ("", "", ""))[0], h) for ro, h in members.get(gid, [])],
                  key=lambda x: (x[0], x[1]))
    mdl = next(((p, h) for (_r, p, h) in rows if p.lower().endswith(".mdl")), None)
    hits = 0
    if mdl:
        hits = sum(1 for (nm, k, th) in refs_by.get(mdl[1], []) if k == ".mesh" and th)
    tag = ("有网格可画" if hits else ("组里有骨骼行但没有可画网格" if n_ske else
           ("组里有网格计数但没有可画网格" if n_mesh else "无 3D 材料")))
    c[(tag, "有mdl" if mdl else "无mdl")] += 1
L = ["=== 组成树里会不会出现「骨骼」这一行，而 3D 面板却是空的 ==="]
for (tag, m), v in c.most_common():
    L.append(f"  {v:6d}  {tag:26s} {m}")
Path(r"D:\TLGL\.scratch\agent_ui_ske.txt").write_text("\n".join(L), encoding="utf-8")
print("\n".join(L).encode("unicode_escape").decode()[:400])
