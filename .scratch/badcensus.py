"""Cluster the still-unclassified payloads by their first 8 bytes."""
import collections
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ALL = os.path.join(HERE, 'out', 'all')

paths = {}
for pak in os.listdir(OUT_ALL):
    d = os.path.join(OUT_ALL, pak)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if len(fn) >= 16:
            paths.setdefault(fn[:16], os.path.join(d, fn))

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
rows = con.execute("SELECT hash, original, type, name FROM resources "
                   "WHERE type IN ('binary','unknown')").fetchall()
c = collections.Counter()
ex = {}
for h, orig, t, name in rows:
    p = paths.get(h)
    head = open(p, 'rb').read(8) if p and os.path.isfile(p) else b''
    k = (t, head.hex())
    c[k] += 1
    ex.setdefault(k, (name or h, orig))
print('unclassified:', len(rows))
for k, v in c.most_common(40):
    n, sz = ex[k]
    print('  %-9s %-18s %6d  size~%-9s ex=%s' % (k[0], k[1], v, sz, n[:44]))
