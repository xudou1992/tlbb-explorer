import sqlite3, io

db = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()
out = io.StringIO()
def w(*a): print(*a, file=out)

# Reproduce the baseline's hub_decoded: "any texture in the same dir", falling back to
# "any ref that resolved". This is what makes D either reachable or not.
w("=== groups where NO texture exists in the group's own dir (=> baseline says D) ===")
cur.execute("""SELECT count(*) FROM agroups g
               WHERE NOT EXISTS (
                 SELECT 1 FROM resources r
                 WHERE r.dir = g.dir AND r.type = 'texture'
               )""")
w("  no same-dir texture:", cur.fetchone()[0])

w("\n=== how many groups have a non-empty dir at all ===")
cur.execute("SELECT count(*) FROM agroups WHERE dir <> ''")
w("  dir <> '':", cur.fetchone()[0])
cur.execute("SELECT count(*) FROM agroups WHERE dir IS NULL OR dir = ''")
w("  dir empty:", cur.fetchone()[0])

w("\n=== so baseline's D would be roughly ===")
cur.execute("""SELECT count(*) FROM agroups g
               WHERE NOT EXISTS (
                 SELECT 1 FROM refs rf WHERE rf.from_hash = g.hub
                   AND rf.to_hash IS NOT NULL
               )
               AND NOT EXISTS (
                 SELECT 1 FROM resources r WHERE r.dir = g.dir AND r.type = 'texture'
               )""")
w("  neither resolved-ref nor same-dir texture:", cur.fetchone()[0])

w("\n=== group.dir sample ===")
cur.execute("SELECT dir, count(*) FROM agroups GROUP BY dir ORDER BY count(*) DESC LIMIT 8")
for d, n in cur.fetchall():
    w(f"  [{d!r}] {n}")

w("\n=== cross-check: 2601 + 10479 = ? ===")
w("  ", 2601 + 10479)

con.close()
with open(r"D:\TLGL\.scratch\sig_probe2.txt", "w", encoding="utf-8") as f:
    f.write(out.getvalue())
print("ok")
