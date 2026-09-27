import sys, struct, re, random, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]
random.seed(21)

print('=== 1. set/.scene : is it one root per map? ===')
r = q("select count(*), count(distinct dir) from resources where type='set' and ext='.scene'")
print('  files/dirs:', r)
print('  path == dir/basename(dir).scene ?',
      q("select count(*) from resources where type='set' and ext='.scene' and path = dir || '/' || substr(dir,15) || '.scene'")[0][0])
r = q("select distinct dir from resources where type='set' and ext='.scene' and dir not in (select distinct dir from resources where ext='.sfl')")
print('  set-dirs without .sfl sibling:', len(r))
r = q("select distinct dir from resources where ext='.sfl' and dir not in (select distinct dir from resources where type='set' and ext='.scene')")
print('  .sfl dirs without set root:', len(r))
print('  stride test: (len - first-name-offset)/n_names')
for row in c.execute("select * from resources where type='set' and ext='.scene' order by original limit 6"):
    b, _ = R.get(row)
    names = [s for s in strings(b, 500) if 'Shadow' in s or 'Lightmap' in s or s.endswith('.mesh')]
    first = b.find(names[0].encode()) if names else -1
    print('   len=%7d names=%3d first@0x%03x  (len-first)/n=%.1f  ver=%d' % (len(b), len(names), first,
          (len(b) - first) / max(1, len(names)), u32le(b[0x40:0x4c], 2)[1] if len(b) > 0x4c else -1))

print('\n=== 2. geom vs mesh content bridge (decisive) ===')
geos = random.sample(q("select * from resources where type='geom'"), 14)
needles = {}
for row in geos:
    b, _ = R.get(row)
    if not b:
        continue
    for i in range(100, 101400, 512):
        w = b[i:i + 24]
        if len(w) == 24 and sum(1 for x in w if x == 0) < 6:
            needles[w] = (row['hash'], i)
            if len(needles) >= 400:
                break
    if len(needles) >= 400:
        break
print('  needles (24B, high-entropy) from geom:', len(needles), 'from', len(geos), 'blobs')
mesh = q("select * from resources where ext='.mesh' and named=1")
mesh = random.sample(mesh, 1200)
found = collections.Counter(); scanned = 0
for row in mesh:
    b, _ = R.get(row)
    if not b:
        continue
    scanned += 1
    for i in range(0, len(b) - 24, 4):
        k = b[i:i + 24]
        if k in needles:
            found[needles[k]] += 1
    if len(found) > 20:
        break
print('  mesh files scanned:', scanned, ' needle hits:', sum(found.values()))

print('\n  reverse: is geom the *padded tail* of mesh? check tail-fill signature')
for row in geos[:3]:
    b, _ = R.get(row)
    tail = b[-4096:]
    print('   geom tail counter:', collections.Counter(tail).most_common(4))
    L = struct.unpack('<I', b[16:20])[0]
    seg = b[L:L + 4096]
    print('   post-101412 counter:', collections.Counter(seg).most_common(4), ' first16', seg[:16].hex(' '))
mrow = mesh[0]
mb, _ = R.get(mrow)
print('   mesh tail counter:', collections.Counter(mb[-4096:]).most_common(4), mrow['path'])

print('\n=== 3. NAVF quick layout (25 named) ===')
for row in c.execute("select * from resources where ext='.nav' order by original desc limit 3"):
    b, _ = R.get(row)
    w = u32le(b, 6)
    print('  ', row['path'], 'len=%d w=%s' % (len(b), w))
    # look for a repeated stride after the u32 run
    nz = [i for i in range(0, len(b)) if b[i] != 0]
    print('    zero-fraction: %.2f ; distinct f32 in body: %d' % (1 - len(nz) / len(b),
          len({b[i:i+4] for i in range(24, min(len(b), 4000), 4)})))

print('\n=== 4. mapref: do the 280B bodies decode to anything stable? ===')
sig = collections.Counter()
for row in c.execute("select * from resources where type='mapref'"):
    b, _ = R.get(row)
    w = u32le(b, 72)
    sig[tuple(w[:6])] += 1
print('  first6 words patterns:', sig.most_common(6))
print('  claim check "count is 4|5":', q("select json_extract(props,'$.count'),count(*) from resources where type='mapref' group by 1"))
