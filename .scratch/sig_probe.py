import sqlite3, io

db = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()
out = io.StringIO()
def w(*a): print(*a, file=out)

w("=== does every group's hub resolve to a resource? ===")
cur.execute("""SELECT count(*) FROM agroups g LEFT JOIN resources r ON r.hash = g.hub
               WHERE r.hash IS NULL""")
w("  groups whose hub is NOT in resources:", cur.fetchone()[0])
cur.execute("SELECT count(*) FROM agroups")
w("  total groups:", cur.fetchone()[0])

w("\n=== members: any group with 0 members? ===")
cur.execute("""SELECT count(*) FROM agroups g
               WHERE NOT EXISTS (SELECT 1 FROM amembers a WHERE a.gid = g.id)""")
w("  groups with zero members:", cur.fetchone()[0])

w("\n=== distinct roles per group: distribution of distinct role count ===")
cur.execute("""SELECT dr, count(*) FROM (
                 SELECT gid, count(DISTINCT role) AS dr FROM amembers GROUP BY gid
               ) GROUP BY dr ORDER BY dr""")
for dr, n in cur.fetchall():
    w(f"  role_kinds={dr}: {n} groups")

w("\n=== raw role vocabulary ===")
cur.execute("SELECT role, count(*) FROM amembers GROUP BY role ORDER BY count(*) DESC")
for r, n in cur.fetchall():
    w(f"  role=[{r!r}] {n}")

w("\n=== how many distinct raw roles ===")
cur.execute("SELECT count(DISTINCT role) FROM amembers")
w("  distinct raw roles:", cur.fetchone()[0])

w("\n=== per-group: does role_kinds>=2 hold for most? ===")
cur.execute("""SELECT count(*) FROM (
                 SELECT gid FROM amembers GROUP BY gid HAVING count(DISTINCT role) >= 2
               )""")
w("  groups with >=2 distinct roles:", cur.fetchone()[0])

con.close()
with open(r"D:\TLGL\.scratch\sig_probe.txt", "w", encoding="utf-8") as f:
    f.write(out.getvalue())
print("ok")
