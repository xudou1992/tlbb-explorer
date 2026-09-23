import sqlite3
from collections import defaultdict

db = r'D:\TLGL\.scratch\resources.db'
con = sqlite3.connect('file:%s?mode=ro' % db.replace('\\', '/'), uri=True)
c = con.cursor()
TEX = ('.tga', '.dds', '.png', '.jpg', '.jpeg', '.bmp', '.webp')
ph = ','.join('?' * len(TEX))

# Per (gid, name) over texture refs: is 'resolves' consistent across rows?
c.execute("""
 SELECT m.gid, r.name, min(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END),
        max(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END), count(*)
 FROM refs r JOIN amembers m ON m.hash = r.from_hash
 WHERE r.kind IN (%s)
 GROUP BY m.gid, r.name
 HAVING min(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END)
        <> max(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END)
""" % ph, TEX)
mixed = c.fetchall()
print('mixed (gid,name) texture pairs:', len(mixed))
for row in mixed[:10]:
    print('  ', row)

# Also: how many (gid,name) pairs have >1 row at all (to_hash differing or not)?
c.execute("""
 SELECT count(*) FROM (
   SELECT m.gid, r.name, count(*) n
   FROM refs r JOIN amembers m ON m.hash = r.from_hash
   WHERE r.kind IN (%s)
   GROUP BY m.gid, r.name HAVING n > 1)
""" % ph, TEX)
print('multi-row (gid,name) pairs:', c.fetchone()[0])
con.close()
