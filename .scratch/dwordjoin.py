"""Can the unnamed textures be recovered after all?

The JBCF string table stores, next to every name, a stable 32-bit value. Instead of
identifying the hash function, join it directly against the resource table: if the
engine looks textures up by a key that shares that 32-bit half, the blob is findable.
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jbcf

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'resources.db'), uri=True)

lo, hi, full = collections.defaultdict(list), collections.defaultdict(list), {}
for h, in con.execute('select hash from resources'):
    v = int(h, 16)
    lo[v & 0xffffffff].append(h)
    hi[v >> 32].append(h)
    full[v] = h

idx = {}
for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
    d = os.path.join(HERE, 'out', 'all', pak)
    if os.path.isdir(d):
        for fn in os.listdir(d):
            idx[fn[:16]] = os.path.join(d, fn)

stat = collections.Counter()
ex = []
n = 0
for h, p in con.execute("select hash, path from resources where type='JBCF' and path like '%.mtl'"):
    f = idx.get(h)
    if not f:
        continue
    try:
        _, _, _, strs = jbcf.parse(open(f, 'rb').read())
    except ValueError:
        continue
    n += 1
    for name, hv in strs:
        if not name or '.' not in name:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext not in ('.tga', '.dds', '.png'):
            continue
        stat['names'] += 1
        a, b = lo.get(hv, []), hi.get(hv, [])
        if hv in full:
            stat['exact64(low==high==v?)'] += 1
        if a or b:
            stat['dword hit'] += 1
            if len(ex) < 6:
                ex.append((name, '%08x' % hv, (a or b)[:2]))
        else:
            stat['no hit'] += 1
    if n >= 1200:
        break

print('materials scanned:', n)
print(dict(stat))
for e in ex:
    print('  ', e)
