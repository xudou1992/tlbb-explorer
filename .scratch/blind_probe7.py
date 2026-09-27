import sys, re, struct, collections, bisect
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, u32le, strings

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]

print('=== A. pak co-location: who are the neighbours of type=geom blobs? ===')
rows = q("select hash,pak,gen,offset,type,subtype,ext,named from resources")
by = collections.defaultdict(list)
for h, pak, gen, off, typ, sub, ext, nm in rows:
    by[(pak, gen)].append((off, typ, sub, ext, h))
for k in by:
    by[k].sort()
nb_geom = collections.Counter()
nb_grid = collections.Counter()
nb_nav = collections.Counter()
nb_mapref = collections.Counter()
targets = {'geom': nb_geom, 'grid753-un': nb_grid, 'NAVF-un': nb_nav, 'mapref': nb_mapref}
sel = {
    'geom': lambda t, s, e, n: t == 'geom',
    'grid753-un': lambda t, s, e, n: s == 'grid753' and n == 0,
    'NAVF-un': lambda t, s, e, n: t == 'NAVF' and n == 0,
    'mapref': lambda t, s, e, n: t == 'mapref',
}
for k, recs in by.items():
    offs = [r[0] for r in recs]
    for i, (off, typ, sub, ext, h) in enumerate(recs):
        for name, fn in sel.items():
            if fn(typ, sub, ext, 0 if typ != 'scene' else 0) and name != 'geom':
                pass
    for i, (off, typ, sub, ext, h) in enumerate(recs):
        for name, fn in sel.items():
            if not fn(typ, sub, ext, recs[i][4] and 0):
                continue
            lo = recs[i - 1] if i > 0 else None
            hi = recs[i + 1] if i + 1 < len(recs) else None
            for side in (lo, hi):
                if side:
                    key = '%s/%s/%s' % (side[1], side[2], side[3] or '-')
                    targets[name][key] += 1
for name, ctr in targets.items():
    print('  %-12s neighbours:' % name, ctr.most_common(7))

print('\n=== A2. distance to nearest neighbour (bytes) for geom ===')
d = collections.Counter()
for k, recs in by.items():
    for i in range(len(recs) - 1):
        if recs[i][1] == 'geom':
            gap = recs[i + 1][0] - recs[i][0]
            d['<1k' if gap < 1000 else ('1k-100k' if gap < 100000 else '>100k')] += 1
print('  ', d.most_common())

print('\n=== B. lattice holes (product of observed coordinate sets) ===')
pat = re.compile(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$')
per = collections.defaultdict(dict)
for d_, n, sub in q("select dir,name,subtype from resources where dir like 'mobile_maps/%' and ext='.scene'"):
    m = pat.match(n or '')
    if m:
        per[d_][(int(m.group(2)), int(m.group(3)))] = sub
tot_holes = 0
hist = collections.Counter()
for dd, cells in per.items():
    xs = sorted({k[0] for k in cells}); zs = sorted({k[1] for k in cells})
    holes = len(xs) * len(zs) - len(cells)
    tot_holes += holes
    hist[holes] += 1
print('  dirs=%d total product-bbox holes=%d  holes-hist(top)=%s' % (len(per), tot_holes, hist.most_common(6)))
print('  grid+stub cell counts per dir (top):', collections.Counter(len(v) for v in per.values()).most_common(6))

print('\n=== C. set/.scene small-file full dump ===')
for row in c.execute("select * from resources where type='set' and ext='.scene' and original between 500 and 2200 order by original limit 2"):
    b, _ = R.get(row)
    z = b.find(b'\x00')
    print('  ', row['path'], 'len', len(b), 'bannerNUL@', z)
    print('    hex[0:128]   ', b[:128].hex(' '))
    print('    hex[64:192]  ', b[64:192].hex(' '))
    print('    ascii tail   ', repr(b[128:400]))
    print('    hex[end-64:] ', b[-64:].hex(' '))
    names = strings(b, 200)
    print('    names:', names[:20])
    print('    count of float-looking segments: len%%(names*?)')
print('  -- name-token census over all 295 --')
tok = collections.Counter()
for row in c.execute("select * from resources where type='set' and ext='.scene'"):
    b, _ = R.get(row)
    if not b:
        continue
    for s in strings(b, 500):
        if len(s) > 3 and not s.startswith('Copyright') and s != 'julekeji':
            tok[re.sub(r'\d+', '#', s)] += 1
print('   ', tok.most_common(20))

print('\n=== D. .anis (same container family, 671MB) header ===')
for row in c.execute("select * from resources where ext='.anis' limit 2"):
    b, why = R.get(row)
    print('  ', row['path'], why, len(b) if b else None, row['props'][:160])
    if b:
        print('    hex', b[:96].hex(' '))
        print('    strs', strings(b[:4000], 14))

print('\n=== E. mapref clean pointer stats ===')
hi_c = collections.Counter(); lo_align = collections.Counter(); inuser = 0; tot = 0
for row in c.execute("select * from resources where type='mapref'"):
    b, _ = R.get(row)
    w = u32le(b, 72)
    for i in range(3, 71, 2):
        p = (w[i + 1] << 32) | w[i]
        tot += 1
        hi_c['%04x' % (p >> 32)] += 1
        if 0x10000 <= (p >> 32) <= 0x7FFFFFFF:
            inuser += 1
print('  pairs=%d in x64-user-address band (hi32 in 0x10000..0x7fffffff): %d (%.1f%%)' % (tot, inuser, 100 * inuser / tot))
print('  hi32 hist:', hi_c.most_common(12))
print('  u32 word value hist over whole corpus (top 14):', collections.Counter(
    v for row in c.execute("select * from resources where type='mapref'") for v in (u32le(R.get(row)[0] or b'', 72))).most_common(14))

print('\n=== F. tani keyword census (fixed) ===')
kw = collections.Counter()
for row in c.execute("select * from resources where ext='.tani' limit 400"):
    b, _ = R.get(row)
    if not b:
        continue
    for k in (b'.pu', b'.mesh', b'.ogg', b'.wav', b'.tga', b'skill', b'hit', b'idle', b'walksound', b'terrain', b'lightmap'):
        if k in b:
            kw[k.decode()] += 1
print('  ', kw.most_common(), ' (of 400 sampled)')
print('  distinct token after GATA header: always self-path?',
      q("select count(*) from resources where ext='.tani' and props like '%ref%'")[0][0], '/2560 have props ref')
