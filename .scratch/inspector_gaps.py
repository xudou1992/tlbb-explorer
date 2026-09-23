import subprocess, os, sqlite3

EXE = r"D:\TLGL\.scratch\rc3\debug\view.exe"
ENV = dict(os.environ)

def run(args):
    p = subprocess.run([EXE] + args, capture_output=True, cwd=r"D:\TLGL",
                       env=ENV, timeout=600)
    return p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")

out = []

# (a) mtl texture slots — the missing Inspector layer under material
o, e = run(["--name=w1351_monster_xiyuqiezei_yifu_001.mtl"])
out.append("=== mtl 贴图槽 ===\n" + o)

# (b) animations from group refs — mdl has none, group carries them
con = sqlite3.connect(r"D:\TLGL\.scratch\resources.db")
c = con.cursor()
c.execute("SELECT hash FROM resources WHERE name='w1351_monster_xiyuqiezei.mdl'")
mh = c.fetchone()
c.execute("SELECT gid FROM amembers WHERE hash=?", mh)
gids = [r[0] for r in c.fetchall()]
out.append("=== 组归属 ===\nmdl hash=%s -> gids=%s" % (mh[0], gids))
for gid in gids:
    c.execute("""SELECT r.name, r.kind, CASE WHEN r.to_hash IS NULL THEN '缺' ELSE '已定位' END,
                        count(*) FROM refs r JOIN amembers m ON m.hash=r.from_hash AND m.gid=?
                 WHERE r.kind='.ani' GROUP BY r.name, r.kind""", (gid,))
    rows = c.fetchall()
    out.append("gid=%s ani refs (%d):" % (gid, len(rows)))
    for r in rows[:15]:
        out.append("   %s %s %s x%d" % r)
con.close()

open(r"D:\TLGL\.scratch\inspector_gaps.txt", "w", encoding="utf-8").write("\n".join(out))
print("done")
