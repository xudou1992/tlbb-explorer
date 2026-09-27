import sys, os, sqlite3, collections, struct
sys.path.insert(0, r'D:\TLGL\.scratch')
import numpy as np
from mine2 import batch_hash

c = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
c.row_factory = sqlite3.Row
L = 200

print('=== 1. validate hash(path)==resources.hash on named rows ===')
rows = c.execute("select path,hash from resources where named=1 and path is not null limit 4000").fetchall()
hs = batch_hash([r['path'].encode() for r in rows], L)
ok = sum(1 for r, h in zip(rows, hs) if '%016x' % int(h) == r['hash'])
print('  %d/%d exact match' % (ok, len(rows)))

print('\n=== 2. enumerate grid scene paths -> can the 1126 nameless grid753 be recovered? ===')
un = {r['hash']: r for r in c.execute("select * from resources where subtype='grid753' and named=0")}
print('  nameless grid753:', len(un))
dirs = sorted({r[0] for r in c.execute("select distinct dir from resources where dir like 'mobile_maps/%'")})
print('  candidate map dirs:', len(dirs))
# coordinate ranges seen in named grid names
rng = collections.Counter()
for (n,) in c.execute("select name from resources where subtype='grid753' and named=1"):
    a = n[:-6].split('_')
    rng[(int(a[0]),)] += 1
print('  first component hist:', rng.most_common(6))
J = range(-4, 16)
K = range(-16, 5)
cands = []
for d in dirs:
    base = d.split('/', 1)[1]
    for i in (0, 1, 2, 3):
        for j in J:
            for k in K:
                cands.append(('%s/%d_%d_%d.scene' % (d, i, j, k)).encode())
print('  candidate paths:', len(cands))
found = {}
for s0 in range(0, len(cands), 200000):
    chunk = cands[s0:s0 + 200000]
    for p, h in zip(chunk, batch_hash(chunk, L)):
        k = '%016x' % int(h)
        if k in un:
            found[k] = p.decode()
print('  >>> RECOVERED %d / %d nameless grid753 tables' % (len(found), len(un)))
for k, v in list(found.items())[:6]:
    print('     ', k, v)
cov = collections.Counter(v.split('/')[1] for v in found.values())
print('  per map dir hits:', len(cov), cov.most_common(6))
hits = [h for h in found]
sizes = sum(un[h]['original'] for h in found)
print('  bytes recovered: %.2f MB of %.2f MB' % (sizes / 1e6, sum(r['original'] for r in un.values()) / 1e6))
print('  candidate paths that hit an existing db row of ANY class (sanity of the space):')
allh = {r[0]: r[1] for r in c.execute("select hash,path from resources")}
tot = 0
for s0 in range(0, len(cands), 200000):
    chunk = cands[s0:s0 + 200000]
    for h in batch_hash(chunk, L):
        if '%016x' % int(h) in allh:
            tot += 1
print('   ', tot, 'of', len(cands), 'enumerated paths exist as a resource')

print('\n=== 3. same trick for the tiny/binary scene stubs? ===')
for cls, sql in [('tiny/.scene', "select * from resources where subtype='bin' and ext='.scene' and named=0"),
                 ('binary/.scene', "select * from resources where type='binary' and ext='.scene' and named=0")]:
    tgt = {r['hash'] for r in c.execute(sql)}
    if not tgt:
        print('  %s: none nameless' % cls)
        continue
    got = 0
    for s0 in range(0, len(cands), 200000):
        chunk = cands[s0:s0 + 200000]
        for h in batch_hash(chunk, L):
            if '%016x' % int(h) in tgt:
                got += 1
    print('  %s nameless=%d hits from the same enumeration=%d' % (cls, len(tgt), got))
