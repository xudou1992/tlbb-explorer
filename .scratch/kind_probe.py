import sqlite3, io, sys

db = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()

out = io.StringIO()
def w(*a):
    print(*a, file=out)

w("=== refs columns ===")
cur.execute("PRAGMA table_info(refs)")
for r in cur.fetchall():
    w(" ", r[1], r[2])

w("\n=== distinct kind values (raw) ===")
cur.execute("SELECT kind, count(*) FROM refs GROUP BY kind ORDER BY count(*) DESC")
for k, n in cur.fetchall():
    w(f"  [{k!r}] {n}")

w("\n=== extension-ish: do any kind values start with a dot? ===")
cur.execute("SELECT count(*) FROM refs WHERE kind LIKE '.%'")
w("  dotted kinds:", cur.fetchone()[0])

w("\n=== dangling table schema ===")
cur.execute("PRAGMA table_info(dangling)")
for r in cur.fetchall():
    w(" ", r[1], r[2])

w("\n=== dangling class distribution ===")
cur.execute("SELECT COALESCE(cls,''), count(*), sum(n_refs) FROM dangling GROUP BY cls ORDER BY count(*) DESC")
for c, n, s in cur.fetchall():
    w(f"  cls=[{c!r}] names={n} citations={s}")

w("\n=== dangling ext distribution ===")
cur.execute("SELECT COALESCE(ext,''), count(*) FROM dangling GROUP BY ext ORDER BY count(*) DESC LIMIT 20")
for e, n in cur.fetchall():
    w(f"  ext=[{e!r}] {n}")

w("\n=== cited_by for the top resolved hash: from_path null rate ===")
cur.execute("""SELECT r.to_hash, count(*), sum(CASE WHEN r.from_path IS NULL OR r.from_path='' THEN 1 ELSE 0 END)
               FROM refs r WHERE r.to_hash IS NOT NULL GROUP BY r.to_hash
               ORDER BY count(*) DESC LIMIT 5""")
for h, n, blank in cur.fetchall():
    w(f"  {h} rows={n} blank_from_path={blank}")

w("\n=== refs sample rows for template_default.mtl's hash ===")
cur.execute("SELECT to_hash FROM refs WHERE name='template_default.mtl' AND to_hash IS NOT NULL LIMIT 1")
row = cur.fetchone()
if row:
    h = row[0]
    w("  hash:", h)
    cur.execute("SELECT from_hash, from_path, kind, name, ambig FROM refs WHERE to_hash=? LIMIT 8", (h,))
    for r in cur.fetchall():
        w("   ", r)

w("\n=== how many refs rows have from_path at all ===")
cur.execute("SELECT count(*), sum(CASE WHEN from_path IS NULL OR from_path='' THEN 1 ELSE 0 END) FROM refs")
t, b = cur.fetchone()
w(f"  total={t} blank={b}")

w("\n=== distinct from_hash count vs rows ===")
cur.execute("SELECT count(DISTINCT from_hash) FROM refs")
w("  distinct from_hash:", cur.fetchone()[0])

w("\n=== do from_hash values join to resources? ===")
cur.execute("SELECT count(DISTINCT r.from_hash) FROM refs r JOIN resources x ON x.hash=r.from_hash")
w("  from_hash joinable:", cur.fetchone()[0])
cur.execute("SELECT count(DISTINCT r.from_hash) FROM refs r JOIN agroups g ON g.hub=r.from_hash")
w("  from_hash is a group hub:", cur.fetchone()[0])

con.close()
with open(r"D:\TLGL\.scratch\kind_probe.txt", "w", encoding="utf-8") as f:
    f.write(out.getvalue())
print("ok")
