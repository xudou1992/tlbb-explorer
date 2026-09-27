"""READ-ONLY: does the engine's path->hash function reproduce resources.hash, and can it
re-name the nameless scene tables / geom blobs?  Also inspects ResourcePath.cfg name list."""
import collections
import json
import random
import re
import sqlite3
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from jhash import path_hash
from blind_reader import Reader, strings

C = sqlite3.connect('file:D:/TLGL/.scratch/resources.db?mode=ro', uri=True)
C.row_factory = sqlite3.Row
R = Reader()
random.seed(5)


def q(sql, a=()):
    return [tuple(r) for r in C.execute(sql, a).fetchall()]


print('=== A. validate path_hash(path) == resources.hash on NAMED rows ===')
rows = q("select hash,path from resources where named=1 and path is not null")
samp = random.sample(rows, 300)
ok = sum(1 for h, p in samp if '%016x' % path_hash(p) == h)
print('  named rows checked=%d matched=%d' % (len(samp), ok))
if ok:
    for h, p in samp[:3]:
        print('   ', p, '->', '%016x' % path_hash(p), 'db', h)

print('\n=== B. ResourcePath.cfg: how many names, and how many nameless ones are in it ===')
row = C.execute("select props,original from resources where ext='.cfg'").fetchone()
print('  .cfg rows:', q("select hash,name,original,stored,length(props) from resources where ext='.cfg'"))
d = json.loads(row['props'])
print('  props keys:', list(d.keys())[:8])
names = d.get('names') or d.get('name') or []
print('  names in cfg props:', len(names))
scene = [n for n in names if n.lower().endswith('.scene')]
print('  .scene names in cfg:', len(scene), scene[:4])
dbpaths = {p for (p,) in q("select path from resources where path is not null")}
incfg = [n for n in names if n in dbpaths]
print('  cfg names already attached in db:', len(incfg))
lost = [n for n in names if n not in dbpaths]
print('  cfg names NOT attached (db 丢了):', len(lost), lost[:6])
print('  their ext mix:', collections.Counter(n.rsplit('.', 1)[-1].lower() for n in lost).most_common(8))
# hash the lost names: do they hit a NAMELESS resource row?
nl = {r[0]: r[1] for r in q("select hash,type||'/'||ifnull(subtype,'-') from resources where named=0")}
hit = {}
for n in lost:
    k = '%016x' % path_hash(n)
    if k in nl:
        hit[k] = n
print('  lost cfg names whose hash IS a nameless resource:', len(hit))
print('   by class:', collections.Counter(nl[k] for k in hit).most_common(8))
for k, v in list(hit.items())[:6]:
    print('    ', k, v)
json_hit_ext = collections.Counter(v.rsplit('.', 1)[-1].lower() for v in hit.values())
print('   ext of recovered:', json_hit_ext.most_common(8))

print('\n=== C. exhaustive naming-space brute force for the 1,126 nameless grid753 ===')
tgt = {r[0] for r in q("select hash from resources where subtype='grid753' and named=0")}
orig = dict(q("select hash,original from resources where subtype='grid753' and named=0"))
dirs = [d0 for (d0,) in q("select distinct dir from resources where dir like 'mobile_maps/%'")]
found = {}
n = 0
for d0 in dirs:
    for a in range(0, 5):
        for b in range(-20, 21):
            for z in range(-21, 6):
                n += 1
                k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d0, a, b, z))
                if k in tgt:
                    found[k] = '%s/%d_%d_%d.scene' % (d0, a, b, z)
print('  tried %d candidate paths (%d dirs) -> recovered %d / %d' % (n, len(dirs), len(found), len(tgt)))
print('  sample:', list(found.items())[:3])

print('\n=== D. brute force .mesh-name space against nameless geom ===')
# every mesh basename mentioned in every named scene table is a candidate name
gnames = set()
pat = re.compile(rb'[\x20-\x7e]{4,}\.mesh')
for row in C.execute("select * from resources where subtype in ('grid753','bin') and ext='.scene' limit 2500"):
    b, _ = R.get(row)
    if not b:
        continue
    for m in pat.findall(b):
        gnames.add(m.decode()[1:] if m[:1] == b'?'.decode() else m.decode())
print('  distinct .mesh basenames harvested from scene tables:', len(gnames))
geom = {r[0] for r in q("select hash from resources where type='geom'")}
pref = [''] + sorted({d0 + '/' for (d0,) in q("select distinct dir from resources where named=1")})
print('  prefixes tried:', len(pref))
hits = {}
tr = 0
for nm in list(gnames)[:1500]:
    for p in pref:
        tr += 1
        k = '%016x' % path_hash(p + nm)
        if k in geom:
            hits[k] = p + nm
        if len(hits) > 60:
            break
print('  hashed %d candidate paths -> geom hits: %d' % (tr, len(hits)))
for k, v in list(hits.items())[:6]:
    print('    ', k, v)
print('  (also compare: do those names collide with already-named mesh rows?)')
nm_named = {r[0]: r[1] for r in q("select hash,path from resources where ext='.mesh'")}
c2 = 0
for nm in list(gnames)[:1500]:
    for p in pref:
        if '%016x' % path_hash(p + nm) in nm_named:
            c2 += 1
            break
print('   basenames that resolve to an EXISTING named .mesh: %d / %d' % (c2, min(1500, len(gnames))))
