"""List the 25 registered texture members with hash + pak location, so we can test decoding."""
import sqlite3
DB = r"D:\TLGL\.scratch\resources.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
cur = con.cursor()
out = []
out.append("== all texture-role members, joined to resources ==")
sql = """
SELECT m.gid, m.hash, r.path, r.codec, r.width, r.height, r.pak, r.offset, r.original, r.method, r.flags, r.type
FROM amembers m LEFT JOIN resources r ON r.hash = m.hash
WHERE m.role = 'texture'
ORDER BY m.gid
"""
for row in cur.execute(sql):
    out.append(repr(row))

out.append("")
out.append("== the same hashes: what does resources say, if anything ==")
sql2 = """
SELECT m.hash, COUNT(r.hash)
FROM amembers m LEFT JOIN resources r ON r.hash = m.hash
WHERE m.role='texture' GROUP BY m.hash
"""
missing = 0
for h, n in cur.execute(sql2):
    if n == 0:
        missing += 1
        out.append(f"  MISSING from resources: {h}")
out.append(f"  total missing: {missing}")
con.close()
open(r"D:\TLGL\.scratch\textures25.txt", "w", encoding="utf-8").write("\n".join(out))
print("ok")
