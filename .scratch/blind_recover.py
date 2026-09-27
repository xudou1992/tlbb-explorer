"""READ-ONLY verification: path-hash enumeration recovers the 1,126 nameless grid753 tables.
Also checks the same trick against the other nameless classes.
"""
import collections
import random
import re
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, u32le  # noqa: E402
from jhash import path_hash  # noqa: E402

C = conn()
R = Reader()
Q = lambda s: [tuple(x) for x in C.execute(s).fetchall()]

print('=== A. validate jhash.path_hash on named rows ===')
rows = Q("select hash,path from resources where named=1 and path is not null")
hit = sum(1 for h, p in rows if '%016x' % path_hash(p) == h)
print('  %d / %d named rows reproduce as hash(path)  => %.2f%%' % (hit, len(rows), 100.0 * hit / len(rows))  )
for h, p in rows[:3]:
    print('   ', p, '%016x' % path_hash(p), 'db', h)

print('\n=== B. recover the 1,126 nameless grid753 ===')
un = dict(Q("select hash,original from resources where subtype='grid753' and named=0"))
dirs = [d for (d,) in Q("select distinct dir from resources where dir like 'mobile_maps/%'")]
found = {}
for d in dirs:
    for a in range(0, 4):
        for y in range(-6, 18):
            for z in range(-18, 6):
                k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, y, z))
                if k in un:
                    found[k] = '%s/%d_%d_%d.scene' % (d, a, y, z)
print('  recovered %d / %d  (%.2f MB of %.2f MB)' % (len(found), len(un),
      sum(un[k] for k in found) / 1e6, sum(un.values()) / 1e6))
print('  sample:', list(found.items())[:5])
per = collections.Counter(v.split('/')[1] for v in found.values())
print('  distinct map dirs hit: %d ; top dirs: %s' % (len(per), per.most_common(6)))
grid753_dirs = {d for (d,) in Q("select distinct dir from resources where subtype='grid753' and named=1")}
setroot_dirs = {d for (d,) in Q("select distinct dir from resources where type='set' and ext='.scene'")}
newdir = {d for d in per if 'mobile_maps/' + d not in grid753_dirs}
print('  of those dirs: previously had NO named grid753 = %d ; had some = %d' % (len(newdir), len(per) - len(newdir)))
print('  dirs that gained cells but have no per-map root .scene:',
      len([d for d in per if 'mobile_maps/' + d not in setroot_dirs]))

pat = re.compile(r'/(\d+)_(-?\d+)_(-?\d+)\.scene$')
known = collections.defaultdict(set)
for d, n in Q("select dir,name from resources where subtype='grid753' and named=1"):
    m = re.match(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$', n or '')
    if m:
        known[d].add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
allobs = collections.defaultdict(set)
for d, n, s in Q("select dir,name,subtype from resources where ext='.scene' and named=1"):
    m = re.match(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$', n or '')
    if m:
        allobs[d].add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
in_hole = 0
clash = 0
samples = []
for k, p in found.items():
    d, leaf = p.rsplit('/', 1)
    m = pat.search(p)
    cell = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if cell in allobs.get(d, ()):
        clash += 1
    else:
        in_hole += 1
    if len(samples) < 5:
        samples.append((p, 'clash' if cell in allobs.get(d, ()) else 'free slot',
                        len(allobs.get(d, ()))))
print('  recovered cells that do NOT clash with an existing named cell: %d ; clashes: %d' % (in_hole, clash))
for s in samples:
    print('   ', s)
# are the recovered names consistent (same a prefix as the rest of the dir)?
pref_ok = 0
for k, p in found.items():
    d, leaf = p.rsplit('/', 1)
    a = leaf.split('_')[0]
    obs = {x[0] for x in allobs.get(d, ())}
    if obs and a in obs:
        pref_ok += 1
print('  recovered cells whose leading index matches the dir\'s existing index prefix: %d/%d' % (pref_ok, len(found)))

print('\n=== C. same enumeration for the other nameless classes ===')
tests = {
    'binary/.scene': "select hash from resources where type='binary' and ext='.scene' and named=0",
    'tiny/.scene': "select hash from resources where type='tiny' and ext='.scene' and named=0",
    'NAVF': "select hash from resources where type='NAVF' and named=0",
    'mapref': "select hash from resources where type='mapref'",
    'geom': "select hash from resources where type='geom'",
    'texture': "select hash from resources where type='texture' and named=0",
    'binary/other': "select hash from resources where type='binary' and named=0 and ext not in ('.scene')",
    'ani/other': "select hash from resources where type='ani' and named=0",
}
for nm, sql in tests.items():
    tgt = {r[0] for r in Q(sql)}
    if not tgt:
        print('  %-14s no nameless rows' % nm)
        continue
    got = 0
    for d in dirs[:60]:
        for a in range(0, 4):
            for y in range(-6, 18):
                for z in range(-18, 6):
                    for ext in ('.scene', '.nav', '.map', '.sfl', '.mesh', '.pu', '.ani', '.tga', ''):
                        if '%016x' % path_hash('%s/%d_%d_%d%s' % (d, a, y, z, ext)) in tgt:
                            got += 1
    print('  %-14s rows=%6d  hits from grid-naming enumeration over 60 dirs = %d' % (nm, len(tgt), got))

print('\n=== D. geom blobs: where do they live in the paks? ===')
print('  gen histogram (top):', Q("select gen,count(*) from resources where type='geom' group by 1 order by 2 desc limit 6"))
print('  pak spread:', Q("select pak,count(*),sum(original) from resources where type='geom' group by 1 order by 2 desc"))
print('  vs named grid753 gen:', Q("select gen,count(*) from resources where subtype='grid753' and named=1 group by 1 order by 2 desc limit 6"))
print('  offset range:', Q("select min(offset),max(offset) from resources where type='geom'"))
print('  same (pak,gen) as a named grid753?:', Q(
    "select count(distinct x.hash) from resources x join resources y on x.pak=y.pak and x.gen=y.gen "
    "where x.type='geom' and y.subtype='grid753' and y.named=1")[0][0], '/ 12676')
print('  props variants:', Q("select props,count(*) from resources where type='geom' group by 1 order by 2 desc"))
print('  method/flags:', Q("select method,flags,count(*) from resources where type='geom' group by 1,2 order by 3 desc"))
