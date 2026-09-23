import sqlite3, io

db = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()
out = io.StringIO()
def w(*a): print(*a, file=out)

TEX = (".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".webp")

# The 2 groups that grade A: >=2 distinct roles AND every texture ref resolves.
w("=== groups with >=2 distinct roles AND all texture refs resolved (grade A) ===")
cur.execute("""
WITH rk AS (
  SELECT gid, count(DISTINCT role) dr FROM amembers GROUP BY gid
), tr AS (
  SELECT from_hash, count(*) tot,
         sum(CASE WHEN to_hash IS NOT NULL THEN 1 ELSE 0 END) loc
  FROM refs WHERE lower(kind) IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp')
  GROUP BY from_hash
)
SELECT g.id, g.stem, g.dir, rk.dr, tr.tot, tr.loc
FROM agroups g
JOIN rk ON rk.gid = g.id
JOIN tr ON tr.from_hash = g.hub
WHERE rk.dr >= 2 AND tr.tot > 0 AND tr.loc = tr.tot
""")
rows = cur.fetchall()
w("  count:", len(rows))
for r in rows:
    w("   ", r)

w("\n=== texture-ref resolution counts across groups (sanity) ===")
cur.execute("""
SELECT count(*) FROM (
  SELECT from_hash FROM refs
  WHERE lower(kind) IN ('.tga','.dds','.png','.jpg','.jpeg','.bmp','.webp')
  GROUP BY from_hash
)""")
w("  distinct from_hash with texture refs:", cur.fetchone()[0])

# The two structures disagree: kind vs name-suffix. Check they agree for .tga.
w("\n=== for .tga rows: does kind match the name suffix? ===")
cur.execute("""SELECT count(*) FROM refs WHERE kind='.tga'
               AND lower(name) NOT LIKE '%.tga'""")
w("  kind=.tga but name not ending .tga:", cur.fetchone()[0])
cur.execute("""SELECT count(*) FROM refs WHERE kind<>'.tga'
               AND lower(name) LIKE '%.tga'""")
w("  name ends .tga but kind<>'.tga':", cur.fetchone()[0])

con.close()
open(r"D:\TLGL\.scratch\gradeA.txt", "w", encoding="utf-8").write(out.getvalue())
print("ok")
