import json
import sqlite3
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
import jhash

con = sqlite3.connect(r'D:\TLGL\.scratch\resources.db')
c = con.cursor()
paths = dict(c.execute('SELECT hash, path FROM resources WHERE path IS NOT NULL'))
known = {int(h, 16) for h in paths}
sel = list(c.execute("SELECT hash, props FROM resources WHERE props LIKE '%ref%'"))
a = b = 0
for h, props in sel[:50]:
    d = json.loads(props or '{}')
    cand = d.get('ref')
    if not cand:
        continue
    k1 = jhash.path_hash(cand)
    k2 = jhash.path_hash(cand.replace('\\', '/').lstrip('/'))
    a += ('%016x' % k1) in paths
    b += (k1 in known)
    if len(sel) and a + b == 0:
        pass
print('via paths-membership:', a, ' via int-set membership:', b, 'of', len(sel))
print('sample:', sel[0][0], json.loads(sel[0][1]).get('ref'),
      '%016x' % jhash.path_hash(json.loads(sel[0][1]).get('ref')))
print('type of path_hash result:', type(jhash.path_hash('data/tani/x.tani')))
