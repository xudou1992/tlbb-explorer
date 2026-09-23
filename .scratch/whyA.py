import sqlite3, io

db = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()
out = io.StringIO()
def w(*a): print(*a, file=out)

# Why does the workbench report A0 while the baseline reports A2?
# Workbench: refs_total/refs_located come from `items` (row.refs), built with
# role_word/kind mapping, and role_kinds from row.parts (Chinese labels).
w("=== group 1994 in detail ===")
cur.execute("SELECT id, hub, hub_path, dir, stem, kind, n, n_mesh, n_mtl, n_ani, n_ske, n_tex FROM agroups WHERE id=1994")
w("  group:", cur.fetchone())
cur.execute("SELECT m.hash, m.role, r.path, r.type FROM amembers m LEFT JOIN resources r ON r.hash=m.hash WHERE m.gid=1994")
w("  members:")
for r in cur.fetchall():
    w("   ", r)
cur.execute("SELECT name, cls FROM agroup_names WHERE gid=1994")
w("  agroup_names:")
for r in cur.fetchall():
    w("   ", r)
cur.execute("""SELECT r.name, r.kind, r.to_hash, r.from_hash FROM refs r
               JOIN amembers m ON m.hash = r.from_hash WHERE m.gid=1994""")
w("  refs via members:")
for r in cur.fetchall():
    w("   ", r)
# workbench's tex filter is kind == "贴图", i.e. the DISPLAY label, not the extension.
w("\n=== does kind=='贴图' ever appear as a stored value? ===")
cur.execute("SELECT DISTINCT kind FROM refs LIMIT 20")
w("  distinct kinds:", [r[0] for r in cur.fetchall()])

w("\n=== group 2118 ===")
cur.execute("SELECT m.hash, m.role, r.path, r.type FROM amembers m LEFT JOIN resources r ON r.hash=m.hash WHERE m.gid=2118")
for r in cur.fetchall():
    w("   ", r)
cur.execute("SELECT name, cls FROM agroup_names WHERE gid=2118")
for r in cur.fetchall():
    w("   name:", r)

con.close()
open(r"D:\TLGL\.scratch\whyA.txt", "w", encoding="utf-8").write(out.getvalue())
print("ok")
