import sys, struct, re, random, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]
rows = lambda s: c.execute(s).fetchall()
random.seed(21)

print('=== 1. set/.scene = one root scene per map? ===')
print('  files/dirs:', q("select count(*), count(distinct dir) from resources where type='set' and ext='.scene'"))
print('  path==dir/<mapid>.scene:', q("select count(*) from resources where type='set' and ext='.scene' and path = dir || '/' || substr(dir, 15) || '.scene'"))
print('  .sfl dirs missing this root:', q("select count(distinct dir) from resources where ext='.sfl' and dir not in (select dir from resources where type='set' and ext='.scene')"))
stat = collections.Counter()
for row in c.execute("select * from resources where type='set' and ext='.scene'"):
    b, _ = R.get(row)
    if not b:
        stat['fail'] += 1
        continue
    n = len([s for s in strings(b, 900) if 'Shadow' in s or 'Lightmap' in s])
    stat[('has .mesh' if b'.mesh' in b else 'plain', min(n // 20, 12) * 20)] += 1
print('  (name-count bucket):', stat.most_common(14))
row = q("select * from resources where type='set' and ext='.scene' and original=518")[0]
row = c.execute("select * from resources where type='set' and ext='.scene' and original=518 limit 1").fetchone()
b, _ = R.get(row)
print('  smallest file len', len(b))
print('   hex[0x40:0x100]', b[0x40:0x100].hex(' '))
print('   hex[0x100:0x180]', b[0x100:0x180].hex(' '))
print('   hex[-80:]', b[-80:].hex(' '))

print('\n=== 2. geom <-> mesh content bridge (48B needles) ===')
geos = random.sample(rows("select * from resources where type='geom'"), 24)
needles = []
for g in geos:
    b, _ = R.get(g)
    if not b:
        continue
    for i in (200, 4000, 20000, 50000, 90000, 101500, 105000):
        w = b[i:i + 48]
        if len(w) == 48 and sum(1 for x in w if x == 0) < 10:
            needles.append((w, g['hash'], i))
print('  needles:', len(needles))
mesh = rows("select * from resources where ext='.mesh' and named=1")
mesh = random.sample(mesh, 2000)
hits = collections.Counter(); scanned = 0
tot_bytes = 0
for m in mesh:
    b, _ = R.get(m)
    if not b:
        continue
    scanned += 1
    tot_bytes += len(b)
    for w, h, i in needles:
        if w in b:
            hits[(h, i)] += 1
print('  mesh files scanned=%d bytes=%d  hits=%d' % (scanned, tot_bytes, sum(hits.values())))
# also: does ANY resource of any type contain a geom needle?
other = rows("select * from resources where type in ('binary','JBPU','JBCF','table','tiny') and ext in ('.map','.scene','.pu','')")
other = random.sample(other, 400)
h2 = 0
for o in other:
    b, _ = R.get(o)
    if b and any(w in b for w, _h, _i in needles):
        h2 += 1
print('  other-class files (%d sampled) containing a geom needle: %d' % (len(other), h2))

print('\n=== 3. geom blob anatomy ===')
b, _ = R.get(geos[0])
L = struct.unpack('<I', b[16:20])[0]
print('  len=%d u32@16(stream len)=%d tail=%d' % (len(b), L, len(b) - L))
print('  u32 @20..:', u32le(b[20:36], 4), ' floats@24:', struct.unpack('<6f', b[24:48]))
print('  floats at L-24:', struct.unpack('<6f', b[L - 24:L]))
print('  u32 at L..:', u32le(b[L:L + 40], 10))
print('  tail bytes:', b[-32:].hex(' '), 'distinct bytes in b[L:]:', sorted(set(b[L:]))[:12])
print('  vertex region zeros: %d / %d' % (b[24:L].count(0), L - 24))
v = struct.unpack('<%df' % 4000, b[24:24 + 16000])
print('  first 4000 floats: min %.2f max %.2f' % (min(v), max(v)))
print('  count of files whose u32@16 equals their own (len - tail)? ', q("select count(*) from resources where type='geom'")[0][0], 'geom rows; 6 distinct original sizes')
print('  109960-101412 =', 109960 - 101412, ' 105856-101412 =', 105856 - 101412)
print('  (101412-24)/12 =', (101412 - 24) / 12.0, ' (101412-24)/28 =', (101412 - 24) / 28.0, ' (101412-24)/4=', (101412 - 24) // 4)

print('\n=== 4. NAVF anatomy (25 named) ===')
for row in c.execute("select * from resources where ext='.nav' order by original desc limit 3"):
    b, _ = R.get(row)
    w = u32le(b, 8)
    print('  %s len=%d head=%s  (len-24)/w2=%.1f' % (row['path'], len(b), w, (len(b) - 24) / w[2]))
    print('    hex[24:120]', b[24:120].hex(' '))
    print('    tail32', b[-32:].hex(' '))
    print('    ascii frac %.2f  zeros frac %.2f' % (sum(32 <= x < 127 for x in b) / len(b), b.count(0) / len(b)))

print('\n=== 5. mapref body: pointer test ===')
al = collections.Counter()
for row in c.execute("select * from resources where type='mapref'"):
    b, _ = R.get(row)
    w = u32le(b, 72)
    for i in range(3, 71, 2):
        p = (w[i + 1] << 32) | w[i]
        hi = p >> 32
        if p == 0:
            al['null'] += 1
        elif hi == 0:
            al['small (<4GiB)'] += 1
        elif hi == 0xFFFFFFFF:
            al['-1/-2 sentinel'] += 1
        elif 0x7F00 <= hi <= 0x7FFF:
            al['0x7Fxx stack/module range'] += 1
        elif 0x1000 <= hi <= 0x8FFF:
            al['0x1xxx-0x8xxx heap range'] += 1
        else:
            al['other hi=0x%x' % hi] += 1
print(' ', al.most_common(10))
print('  props count:', q("select json_extract(props,'$.count'),count(*) from resources where type='mapref' group by 1"))
print('  word layout: w0=count w1=280 w2=1 ; w3..w6:', q("select json_extract(props,'$.count') from resources limit 0"))
row = c.execute("select * from resources where type='mapref' limit 3").fetchall()
for r in row:
    b, _ = R.get(r)
    print('   ', u32le(b, 10))
