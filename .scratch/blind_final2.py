import collections
import re
import struct
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le  # noqa: E402
from jhash import path_hash  # noqa: E402

C = conn()
R = Reader()
Q = lambda s: [tuple(x) for x in C.execute(s).fetchall()]


def dec(h):
    row = C.execute('select * from resources where hash=?', (h,)).fetchone()
    return R.get(row) if row else (None, 'no-row')


# --- 1. recovered-path quality: do they fill real lattice holes? ---
un = dict(Q("select hash,original from resources where subtype='grid753' and named=0"))
dirs = [d for (d,) in Q("select distinct dir from resources where dir like 'mobile_maps/%'")]
found = {}
for d in dirs:
    for a in range(0, 4):
        for y in range(-6, 18):
            for z in range(-18, 6):
                k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, y, z))
                if k in un:
                    found[k] = (d, a, y, z)
obs = collections.defaultdict(set)
for d, n in Q("select dir,name from resources where ext='.scene' and named=1"):
    m = re.match(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$', n or '')
    if m:
        obs[d].add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
inb = hole = out = 0
firsts = collections.Counter()
for h, (d, a, y, z) in found.items():
    firsts[a] += 1
    cells = obs.get(d, set())
    ys = sorted({c[1] for c in cells}); zs = sorted({c[2] for c in cells})
    if not cells or (a, y, z) in cells:
        out += 1
        continue
    if ys and zs and min(ys) <= y <= max(ys) and min(zs) <= z <= max(zs):
        inb += 1
    else:
        hole += 1
print('recovered 1126 paths: first-component hist', firsts.most_common())
print('  inside the dir\'s existing (y,z) bbox (真补洞): %d ; outside bbox/edge: %d ; no named cells or clash: %d' % (inb, hole, out))
per = collections.Counter(v[0] for v in found.values())
print('  dirs gaining cells:', len(per), '; cells per dir top:', per.most_common(5))
print('  example full names:', [('%s/%d_%d_%d.scene' % v) for v in list(found.values())[:3]])

# --- 2. do the other nameless classes respond to ANY enumerable naming? ---
sets = {
    'NAVF-un': {r[0] for r in Q("select hash from resources where type='NAVF' and named=0")},
    'geom': {r[0] for r in Q("select hash from resources where type='geom'")},
    'mapref': {r[0] for r in Q("select hash from resources where type='mapref'")},
    'bin-other': {r[0] for r in Q("select hash from resources where type='binary' and named=0 and ext not in ('.scene')")},
}
tpl_ext = ['.nav', '.scene', '.mesh', '.map', '.bin', '.geo', '.obj', '.buf', '.ani', '.tga', '.pu']
hit = collections.Counter()
tried = 0
for d in dirs:
    leaf = d.split('/')[-1]
    cands = ['%s/%s%s' % (d, leaf, e) for e in tpl_ext]
    for a in range(0, 2):
        for y in range(-2, 12):
            for z in range(-12, 2):
                for e in tpl_ext:
                    cands.append('%s/%d_%d_%d%s' % (d, a, y, z, e))
    for p in cands:
        tried += 1
        k = '%016x' % path_hash(p)
        for nm, t in sets.items():
            if k in t:
                hit[nm] += 1
print('\nenumeration over %d candidate paths (root-name + grid-name x %d exts, 302 maps):' % (tried, len(tpl_ext)))
print('  hits per class:', dict(hit), '<- 0 = 这些类的路径无法用地图命名法穷举出来')
for nm, t in sets.items():
    print('  %-9s rows=%d' % (nm, len(t)))

# --- 3. set/.scene entry layout probe ---
print('\nset/.scene entry probe:')
for row in Q("select hash from resources where type='set' and ext='.scene' order by original desc limit 2"):
    b, _ = dec(row[0])
    z = b.find(b'\x00')
    names = [(s, b.find(s.encode())) for s in set(strings(b, 900)) if s.startswith(('StaticShadow', 'HQ_Lightmap', 'LQ_Lightmap'))]
    names.sort(key=lambda x: x[1])
    st = [names[i][1] - names[i - 1][1] for i in range(1, len(names))]
    print('  hash=%s len=%d names=%d first@0x%x strides(head8)=%s ver=%d' % (row[0], len(b), len(names),
          names[0][1] if names else -1, st[:8], u32le(b[0x40:0x50], 4)[3]))
    if names:
        i0 = names[0][1]
        print('     record area hex[%x:%x]=%s' % (i0 - 24, i0 + 40, b[i0 - 24:i0 + 40].hex(' ')))
        print('     gap between name0 and name1 hex=%s' % b[names[0][1] + 16:names[1][1] + 16].hex(' ') if len(names) > 1 else '')
b, _ = dec(Q("select hash from resources where type='set' and ext='.scene' and original=436609 limit 1")[0])
i = b.find(b'.mesh')
print('  436KB file: name area hex around first .mesh =', b[i - 40:i + 48].hex(' '))
names = re.findall(rb'[\x20-\x7e]{4,80}\.mesh', b)
print('  .mesh names found:', len(names), [n.decode() for n in names[:3]])
d0 = [b.find(names[0]) for _ in [0]]
ds = [b.find(names[k]) - b.find(names[k - 1]) for k in range(1, min(8, len(names)))]
print('  distance between consecutive .mesh name offsets:', ds, ' file len', len(b))
print('  u32 header of that file:', u32le(b, 24))
