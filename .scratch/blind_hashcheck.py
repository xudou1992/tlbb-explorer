import sys, os, sqlite3, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
import numpy as np
from mine2 import batch_hash

c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row

print('=== validate engine path-hash replication on known (path -> hash) pairs ===')
pairs = c.execute("select path,hash from resources where named=1 and path is not null limit 6").fetchall()
L = 200
hs = batch_hash([p['path'].encode() for p in pairs], L)
ok = 0
for p, h in zip(pairs, hs):
    g = '%016x' % int(h)
    print('  %-58s -> %s expect %s %s' % (p['path'], g, p['hash'], 'OK' if g == p['hash'] else 'xx'))
    ok += g == p['hash']
print('  matched %d/%d' % (ok, len(pairs)))
