import sqlite3

db = r'D:\TLGL\.scratch\resources.db'
con = sqlite3.connect('file:%s?mode=ro' % db.replace('\\', '/'), uri=True)
c = con.cursor()

TEX = ('.tga', '.dds', '.png', '.jpg', '.jpeg', '.bmp', '.webp')
ph = ','.join('?' * len(TEX))

# Reproduce the shared texture_refs() query for every group, then grade.
c.execute("SELECT id, dir, stem FROM agroups")
groups = c.fetchall()

# members per group
c.execute("SELECT gid, role FROM amembers")
from collections import defaultdict
roles = defaultdict(list)
for gid, role in c.fetchall():
    roles[gid].append(role)

# texture refs per group, via amembers join
c.execute("""
 SELECT m.gid, r.name, max(CASE WHEN r.to_hash IS NOT NULL THEN 1 ELSE 0 END)
 FROM refs r JOIN amembers m ON m.hash = r.from_hash
 WHERE r.kind IN (%s)
 GROUP BY m.gid, r.name
""" % ph, TEX)
tex = defaultdict(list)
for gid, name, res in c.fetchall():
    tex[gid].append((name, res))

A = B = C = D = 0
a_groups = []
for gid, d, stem in groups:
    ms = roles.get(gid, [])
    distinct = len(set(ms))
    pairs = tex.get(gid, [])
    tot = len(pairs)
    loc = sum(1 for _, r in pairs if r)
    if len(ms) == 0:
        D += 1; continue
    if distinct >= 2 and tot > 0 and loc == tot:
        A += 1; a_groups.append((gid, stem, d, distinct, tot, loc, len(ms)))
    elif distinct >= 2:
        B += 1
    else:
        C += 1

print('PY_A=%d PY_B=%d PY_C=%d PY_D=%d  total=%d' % (A, B, C, D, A + B + C + D))
print('A groups (%d):' % len(a_groups))
for g in a_groups:
    print('  ', g)
con.close()
