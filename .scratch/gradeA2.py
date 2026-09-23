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

# Baseline: refs_total from group_names filtered by is_texture_name (distinct names),
# refs_located from refs_from_group filtered by is_texture_name AND to.is_some().
# These are different queries, so tot>0 && loc==tot is reachable in odd ways.
cur.execute("SELECT id, hub, stem, dir FROM agroups")
groups = cur.fetchall()
w("total groups:", len(groups))

# group_names => need to know what that query returns. Use refs as proxy for names too.
# Get per-group name set (texture) and per-group resolved count.
cur.execute("""
SELECT g.id, g.hub, g.stem, g.dir,
  (SELECT count(*) FROM refs r WHERE r.from_hash = g.hub AND r.to_hash IS NOT NULL
     AND lower(r.kind) IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp')) AS loc_refs,
  (SELECT count(*) FROM amembers m WHERE m.gid = g.id) AS n_members,
  (SELECT count(DISTINCT m.role) FROM amembers m WHERE m.gid = g.id) AS dr
FROM agroups g
""")
rows = cur.fetchall()

# grade A needs role_kinds>=2, refs_total>0, refs_located==refs_total
cands = [r for r in rows if r[6] >= 2 and r[4] > 0]
w("\ngroups with dr>=2 and loc_refs>0:", len(cands))
for r in cands[:20]:
    w("   ", r)

# Now: tot must equal loc. tot comes from names. Let's count distinct texture names per group.
w("\n=== checking name-based totals for those candidates ===")
for gid, hub, stem, d, loc, nm, dr in cands[:20]:
    cur.execute("""SELECT count(DISTINCT name) FROM refs WHERE from_hash=?
                   """, (hub,))
    all_names = cur.fetchone()[0]
    cur.execute("""SELECT count(DISTINCT name) FROM refs WHERE from_hash=?""", (hub,))
    tex_names = 0
    cur.execute("SELECT DISTINCT name FROM refs WHERE from_hash=?", (hub,))
    names = [x[0] for x in cur.fetchall()]
    tex_names = sum(1 for n in names if is_tex(n))
    w(f"  gid={gid} stem={stem!r} dir={d!r} dr={dr} loc_refs={loc} tex_names={tex_names}")

con.close()
open(r"D:\TLGL\.scratch\gradeA2.txt", "w", encoding="utf-8").write(out.getvalue())
print("ok")
