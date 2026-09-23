import sqlite3, io

db = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()
TEX = (".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".webp")
def is_tex(n):
    n = (n or "").lower()
    return any(n.endswith(e) for e in TEX)

out = io.StringIO()
def w(*a): print(*a, file=out)

# Replicate exactly: refs_total = distinct texture names in agroup_names for this gid
#                  refs_located = distinct texture names from refs_from_group that resolve
w("=== replicating baseline grade computation ===")
cur.execute("SELECT id, hub, stem, dir FROM agroups")
groups = cur.fetchall()

# per-group: tex names in agroup_names
cur.execute("SELECT gid, name FROM agroup_names")
gn = {}
for gid, name in cur.fetchall():
    gn.setdefault(gid, []).append(name)

# per-group: refs_from_group (distinct by name, joined via amembers) with resolution
cur.execute("""
SELECT m.gid, r.name, max(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END) AS res
FROM refs r JOIN amembers m ON m.hash = r.from_hash
GROUP BY m.gid, r.name
""")
rg = {}
for gid, name, res in cur.fetchall():
    rg.setdefault(gid, []).append((name, res))

# per-group distinct roles
cur.execute("SELECT gid, count(DISTINCT role) FROM amembers GROUP BY gid")
dr = dict(cur.fetchall())

# member counts
cur.execute("SELECT gid, count(*) FROM amembers GROUP BY gid")
nm = dict(cur.fetchall())

grades = {"A": [], "B": [], "C": [], "D": []}
for gid, hub, stem, d in groups:
    tex_names = [n for n in gn.get(gid, []) if is_tex(n)]
    tot = len(tex_names)
    loc = sum(1 for n, r in rg.get(gid, []) if is_tex(n) and r == 1)
    kinds = dr.get(gid, 0)
    members = nm.get(gid, 0)
    # hub_decode unmeasured => no D gate
    if members == 0:
        g = "D"
    else:
        all_land = tot > 0 and loc == tot
        if kinds >= 2 and all_land:
            g = "A"
        elif kinds >= 2:
            g = "B"
        else:
            g = "C"
    grades[g].append((gid, stem, d, kinds, tot, loc, members))

for k in "ABCD":
    w(f"  {k}: {len(grades[k])}")

w("\n=== the A groups ===")
for r in grades["A"]:
    w("   ", r)

w("\n=== sanity: any group where tot>0? ===")
w("  ", sum(1 for gid, hub, stem, d in groups if any(is_tex(n) for n in gn.get(gid, []))))

con.close()
open(r"D:\TLGL\.scratch\gradeA3.txt", "w", encoding="utf-8").write(out.getvalue())
print("ok")
