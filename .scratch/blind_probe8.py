import sys, re, struct, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, u32le, strings

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]

print('=== A. pak co-location: neighbours (by offset, same pak) of each blind-spot class ===')
rows = q("select hash,pak,offset,type,subtype,ext,named from resources")
by = collections.defaultdict(list)
for h, pak, off, typ, sub, ext, nm in rows:
    key = 'geom' if typ == 'geom' else ('grid753-un' if (sub == 'grid753' and not nm) else
          ('NAVF-un' if (typ == 'NAVF' and not nm) else ('mapref' if typ == 'mapref' else
           ('grid753-named' if sub == 'grid753' else 'other:%s' % (typ or '-')))))
    by[pak].append((off, key, '%s/%s' % (typ, ext or '-')))
nb = collections.defaultdict(collections.Counter)
selfc = collections.defaultdict(collections.Counter)
for pak, recs in by.items():
    recs.sort()
    for i, (off, key, lab) in enumerate(recs):
        if key in ('geom', 'grid753-un', 'NAVF-un', 'mapref'):
            for j in (i - 1, i + 1):
                if 0 <= j < len(recs):
                    nb[key][recs[j][1]] += 1
            selfc[key][lab] += 0  # noop
for k in ('geom', 'grid753-un', 'NAVF-un', 'mapref'):
    print('  %-11s neighbour classes:' % k, nb[k].most_common(6))

print('\n  geom offset neighbours - exact ext of neighbour:')
nb2 = collections.defaultdict(collections.Counter)
for pak, recs in by.items():
    recs.sort()
    for i, (off, key, lab) in enumerate(recs):
        if key in ('geom', 'grid753-un', 'mapref', 'NAVF-un'):
            for j in (i - 1, i + 1):
                if 0 <= j < len(recs):
                    nb2[key][recs[j][2]] += 1
for k in nb2:
    print('   ', k, nb2[k].most_common(8))

print('\n=== B. lattice holes ===')
pat = re.compile(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$')
per = collections.defaultdict(dict)
for d_, n, sub in q("select dir,name,subtype from resources where dir like 'mobile_maps/%' and ext='.scene'"):
    m = pat.match(n or '')
    if m:
        per[d_][(int(m.group(2)), int(m.group(3)))] = sub
holes_hist = collections.Counter()
for dd, cells in per.items():
    xs = {k[0] for k in cells}; zs = {k[1] for k in cells}
    holes_hist[len(xs) * len(zs) - len(cells)] += 1
print('  dirs=%d holes-hist:' % len(per), holes_hist.most_common(8))
print('  cells per dir:', collections.Counter(len(v) for v in per.values()).most_common(6))
print('  dirs whose cells are ALL grid753 (no stub):', sum(1 for v in per.values() if all(s == 'grid753' for s in v.values())))

print('\n=== C. set/.scene small files full structure ===')
n_rec = collections.Counter()
for row in c.execute("select * from resources where type='set' and ext='.scene' order by original limit 3"):
    b, _ = R.get(row)
    z = b.find(b'\x00')
    print('  ', row['path'], 'len', len(b), 'bannerNUL@', z)
    print('    hex[0:0x40]', b[:0x40].hex(' '))
    print('    hex[0x40:0x100]', b[0x40:0x100].hex(' '))
    print('    hex[0x100:0x1c0]', b[0x100:0x1c0].hex(' '))
    print('    tail', b[-48:].hex(' '))
    print('    names', strings(b, 40)[:14])
    n_rec.update([len(strings(b, 400))])
print('\n  name-token patterns across all 295:')
tok = collections.Counter()
for row in c.execute("select * from resources where type='set' and ext='.scene'"):
    b, _ = R.get(row)
    for s in strings(b, 500):
        if len(s) > 3 and not s.startswith(('Copyright', 'julekeji')):
            tok[re.sub(r'\d+', '#', s)] += 1
print('   ', tok.most_common(14))

print('\n=== D. .anis (type=set, 671MB) ===')
for row in c.execute("select * from resources where ext='.anis' limit 2"):
    b, why = R.get(row)
    print('  ', row['path'], why, len(b) if b else None, (row['props'] or '')[:150])
    if b:
        print('    hex', b[:64].hex(' '))
        print('    strs', strings(b[:6000], 10))

print('\n=== E. mapref pointer stats ===')
tot = inband = 0
hi = collections.Counter()
for row in c.execute("select * from resources where type='mapref'"):
    b, _ = R.get(row)
    w = u32le(b, 72)
    for i in range(3, 71, 2):
        p = (w[i + 1] << 32) | w[i]
        tot += 1
        hi['%x' % (p >> 32)] += 1
        if 0x10000 <= (p >> 32) <= 0x7FFFFFFF:
            inband += 1
print('  64-bit pairs=%d ; with hi32 in 0x1_0000..0x7FFF_FFFF (x64 user range): %d (%.1f%%)' % (tot, inband, 100 * inband / tot))
print('  hi32 hist:', hi.most_common(10))
print('  64-bit values matching a pak byte offset:', sum(1 for row in c.execute("select * from resources where type='mapref' limit 200")
      for v in [] ))
print('  u32 words == 280/1/count only? distinct u32 values overall:',
      len({v for row in c.execute("select * from resources where type='mapref'") for v in u32le(R.get(row)[0] or b'', 72)}))

print('\n=== F. .tani keyword census ===')
kw = collections.Counter()
for row in c.execute("select * from resources where ext='.tani' limit 400"):
    b, _ = R.get(row)
    for k in (b'.pu', b'.mesh', b'.ogg', b'.wav', b'.tga', b'skill', b'hit', b'idle', b'walksound', b'terrain', b'lightmap', b'height'):
        if b and k in b:
            kw[k.decode()] += 1
print('  ', kw.most_common(), 'of 400 sampled')
