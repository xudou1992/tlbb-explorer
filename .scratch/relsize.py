"""Size the relation graph, to see whether a relation browser has real content.

Read-only. Answers: how shared are skeletons / materials / animations? What would a
"which models use this skeleton" panel actually show?
"""
import sqlite3
from collections import Counter

DB = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()
out = []
p = out.append

p("== relations table: edge kinds ==")
for rel, n in cur.execute("SELECT rel, COUNT(*) FROM relations GROUP BY rel ORDER BY COUNT(*) DESC LIMIT 20"):
    p(f"  {str(rel)!r:28} {n}")

p("")
p("== member role totals (all groups) ==")
for role, n in cur.execute("SELECT role, COUNT(*) FROM amembers GROUP BY role ORDER BY COUNT(*) DESC"):
    p(f"  {role!r:14} {n}")

p("")
p("== sharing: how many groups does one member-hash participate in? ==")
p("  (fan-in = number of distinct groups a member hash appears in)")
for role in ("skeleton", "material", "animation", "mesh", "model", "texture"):
    rows = list(cur.execute(
        "SELECT hash, COUNT(DISTINCT gid) AS fan FROM amembers WHERE role=? "
        "GROUP BY hash ORDER BY fan DESC LIMIT 5", (role,)))
    total = cur.execute("SELECT COUNT(DISTINCT hash) FROM amembers WHERE role=?", (role,)).fetchone()[0]
    multi = cur.execute(
        "SELECT COUNT(*) FROM (SELECT hash FROM amembers WHERE role=? GROUP BY hash HAVING COUNT(DISTINCT gid)>=2)",
        (role,)).fetchone()[0]
    p(f"  {role:10} distinct={total:<6} shared_by_2plus={multi:<6} top_fan={[(h[:12], f) for h, f in rows]}")

p("")
p("== bone library example: the most-shared skeletons ==")
for h, fan in cur.execute(
    "SELECT hash, COUNT(DISTINCT gid) AS f FROM amembers WHERE role='skeleton' "
    "GROUP BY hash ORDER BY f DESC LIMIT 10"):
    path = cur.execute("SELECT path FROM resources WHERE hash=?", (h,)).fetchone()
    p(f"  {h} fan={fan:<5} {path[0] if path else '(no path)'}")

p("")
p("== animation library: clips per group ==")
row = cur.execute("SELECT COUNT(*), SUM(n), MAX(n) FROM (SELECT gid, COUNT(*) AS n FROM amembers WHERE role='animation' GROUP BY gid)").fetchone()
p(f"  groups with animations={row[0]}  total_clips={row[1]}  max_in_one={row[2]}")

p("")
p("== how many groups would a relation browser show as 'connected'? ==")
p(f"  groups with >=1 member:                 {cur.execute('SELECT COUNT(DISTINCT gid) FROM amembers').fetchone()[0]}")
p(f"  groups whose members are shared:        {cur.execute('SELECT COUNT(*) FROM (SELECT gid FROM amembers m WHERE EXISTS (SELECT 1 FROM amembers o WHERE o.hash=m.hash AND o.gid<>m.gid))').fetchone()[0]}")
p(f"  groups where ALL members are private:   {cur.execute('SELECT COUNT(*) FROM agroups g WHERE EXISTS (SELECT 1 FROM amembers m WHERE m.gid=g.id) AND NOT EXISTS (SELECT 1 FROM amembers m JOIN amembers o ON o.hash=m.hash AND o.gid<>m.gid WHERE m.gid=g.id)').fetchone()[0]}")

p("")
p("== refs vs relations: where does cross-asset linkage actually live? ==")
p(f"  refs rows:      {cur.execute('SELECT COUNT(*) FROM refs').fetchone()[0]}")
p(f"  relations rows: {cur.execute('SELECT COUNT(*) FROM relations').fetchone()[0]}")
p(f"  refs resolving to a resource: {cur.execute('SELECT COUNT(*) FROM refs WHERE to_hash IS NOT NULL').fetchone()[0]}")

con.close()
open(r"D:\TLGL\.scratch\relations_sized.txt", "w", encoding="utf-8").write("\n".join(out))
print("ok")
