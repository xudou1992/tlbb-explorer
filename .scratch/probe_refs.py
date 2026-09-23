"""Read-only probe: what does the refs table actually contain?

Answers the one question the grade rules depend on: how many texture references
exist, and how many resolve. Nothing is written to the DB (mode=ro).
"""
import sqlite3

DB = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()
out = []
p = out.append

TEX = ("tga", "dds", "png", "jpg", "jpeg", "bmp", "webp")
tex_clause = " OR ".join(
    f"lower(substr(kind, -{len(e)+1})) = '.{e}'" for e in TEX
)

p("== resources.ext distribution ==")
for ext, n in cur.execute(
    "SELECT lower(ext), COUNT(*) FROM resources GROUP BY lower(ext) ORDER BY COUNT(*) DESC LIMIT 20"
):
    p(f"  {str(ext)!r:12} {n}")

p("")
p("== refs.kind distribution ==")
for kind, total, resolved in cur.execute(
    "SELECT kind, COUNT(*), SUM(CASE WHEN to_hash IS NOT NULL THEN 1 ELSE 0 END) "
    "FROM refs GROUP BY kind ORDER BY COUNT(*) DESC LIMIT 25"
):
    p(f"  {str(kind)!r:28} total={total:<7} resolved={resolved}")

p("")
p("== texture refs only (exactly what grade() counts) ==")
tex_total, tex_resolved = 0, 0
for kind, total, resolved in cur.execute(
    f"SELECT kind, COUNT(*), SUM(CASE WHEN to_hash IS NOT NULL THEN 1 ELSE 0 END) "
    f"FROM refs WHERE {tex_clause} GROUP BY kind"
):
    tex_total += total
    tex_resolved += resolved or 0
    p(f"  {str(kind)!r:24} total={total:<6} resolved={resolved}")
p(f"  TEXTURE REF ROWS: total={tex_total} resolved={tex_resolved}")

p("")
p("== how many assets have >=1 texture ref / >=1 resolved texture ref ==")
p(f"  >=1 texture ref:          {cur.execute(f'SELECT COUNT(DISTINCT from_hash) FROM refs WHERE {tex_clause}').fetchone()[0]}")
p(f"  >=1 RESOLVED texture ref: {cur.execute(f'SELECT COUNT(DISTINCT from_hash) FROM refs WHERE ({tex_clause}) AND to_hash IS NOT NULL').fetchone()[0]}")

p("")
p("== all refs regardless of kind ==")
p(f"  >=1 ref at all:     {cur.execute('SELECT COUNT(DISTINCT from_hash) FROM refs').fetchone()[0]}")
p(f"  >=1 RESOLVED ref:   {cur.execute('SELECT COUNT(DISTINCT from_hash) FROM refs WHERE to_hash IS NOT NULL').fetchone()[0]}")
p(f"  total ref rows:     {cur.execute('SELECT COUNT(*) FROM refs').fetchone()[0]}")
p(f"  resolved ref rows:  {cur.execute('SELECT COUNT(*) FROM refs WHERE to_hash IS NOT NULL').fetchone()[0]}")

p("")
p("== amembers.role distribution ==")
for role, n in cur.execute("SELECT role, COUNT(*) FROM amembers GROUP BY role ORDER BY COUNT(*) DESC LIMIT 15"):
    p(f"  {str(role)!r:14} {n}")

p("")
p("== agroups: role_kinds>=2 count (the `composition` signal) ==")
row = cur.execute(
    "SELECT COUNT(*) FROM (SELECT g.id FROM agroups g JOIN amembers m ON m.gid = g.id "
    "GROUP BY g.id HAVING COUNT(DISTINCT m.role) >= 2)"
).fetchone()
p(f"  groups with role_kinds>=2: {row[0]}")
p(f"  total agroups:             {cur.execute('SELECT COUNT(*) FROM agroups').fetchone()[0]}")
p(f"  groups with 0 members:     {cur.execute('SELECT COUNT(*) FROM agroups g WHERE NOT EXISTS (SELECT 1 FROM amembers m WHERE m.gid = g.id)').fetchone()[0]}")

p("")
p("== n_tex / n_mtl columns on agroups (catalog's own counts) ==")
row = cur.execute("SELECT SUM(n_tex>0), SUM(n_mtl>0), SUM(n_mesh>0), SUM(n_ani>0), COUNT(*) FROM agroups").fetchone()
p(f"  groups with n_tex>0:  {row[0]}")
p(f"  groups with n_mtl>0:  {row[1]}")
p(f"  groups with n_mesh>0: {row[2]}")
p(f"  groups with n_ani>0:  {row[3]}")
p(f"  total:                {row[4]}")

p("")
p("== resources: how many are decodable images (width>0)? ==")
p(f"  resources with width>0: {cur.execute('SELECT COUNT(*) FROM resources WHERE width>0').fetchone()[0]}")
p(f"  resources total:        {cur.execute('SELECT COUNT(*) FROM resources').fetchone()[0]}")

con.close()
open(r"D:\TLGL\.scratch\probe_refs_out.txt", "w", encoding="utf-8").write("\n".join(out))
print("written")
