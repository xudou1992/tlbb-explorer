import sys, struct, re, collections, math
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, u32le, strings

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]

print('=== item2b: grid lattice holes per map dir ===')
rows = q("select dir,name from resources where subtype='grid753' and named=1")
pat = re.compile(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$')
per = collections.defaultdict(list)
bad = 0
for d, n in rows:
    m = pat.match(n or '')
    if not m:
        bad += 1
        continue
    per[d].append(tuple(int(x) for x in m.groups()))
print('  named grid753=%d dirs=%d unparsable-names=%d' % (len(rows), len(per), bad))
holes = 0
filled = 0
cover = collections.Counter()
for d, lst in per.items():
    pref = {x[0] for x in lst}
    xs = [x[1] for x in lst]; zs = [x[2] for x in lst]
    span = (max(xs) - min(xs) + 1) * (max(zs) - min(zs) + 1)
    holes += max(0, span - len(set(lst)))
    filled += len(lst)
    cover[(min(xs), max(xs), min(zs), max(zs))] += 1
print('  within-bbox missing slots: %d (filled %d)' % (holes, filled))
print('  distinct bbox shapes (top6):', cover.most_common(6))
print('  sample dir lattice:', list(per.items())[:3])
print('  name patterns not A_B_C:', q("select name,count(*) from resources where subtype='grid753' and named=1 and name not like '%\\_%\\_%.scene' escape '\\' limit 5"))
print('  total named scene-ish files per dir for one dir:')
print('   ', q("select name,ext,type,subtype from resources where dir='mobile_maps/w1351_ll_dh_001'"))

print('\n=== item5 full: mapref body analysis ===')
ptr = collections.Counter(); hi_hi = collections.Counter()
allpairs = []
for row in c.execute("select * from resources where type='mapref'"):
    b, why = R.get(row)
    if not b:
        continue
    w = u32le(b, 72)
    for i in range(3, 71, 2):
        lo, hi = w[i], w[i + 1]
        p = (hi << 32) | lo
        allpairs.append(p)
        if hi >= 0xFFF0:
            ptr['signext/-1 region (0x%04x)' % (hi >> 12)] += 1
        elif 0x1000 <= hi <= 0x7FFF:
            ptr['user-mode x64 heap/stack (hi=%04x)' % (hi >> 8)] += 1
        elif p == 0:
            ptr['null'] += 1
        else:
            ptr['other hi=%04x' % hi] += 1
print('  total 64-bit pairs:', len(allpairs))
for k, v in ptr.most_common(12):
    print('   ', k, v)
nz = [p for p in allpairs if p]
print('  nonzero range:', hex(min(nz)), hex(max(nz)))
offs = {r[0] for r in q("select offset from resources")}
print('  pairs equal to a pak offset:', sum(1 for p in nz if p in offs))
print('  float-view of first 8 words (sample record):')
b, _ = R.get(c.execute("select * from resources where type='mapref' limit 1").fetchone())
print('   ', struct.unpack('<8f', b[8:40]))
print('   raw u32:', u32le(b, 20))

print('\n=== item4: NAVF layout / section counts ===')
for row in c.execute("select * from resources where ext='.nav' order by original desc limit 3"):
    b, _ = R.get(row)
    w = u32le(b, 10)
    print('  %s len=%d head=%s' % (row['path'], len(b), w))
print('  header field stats over all 455 NAVF:')
st = collections.Counter()
for row in c.execute("select * from resources where type='NAVF'"):
    b, _ = R.get(row)
    if not b:
        st['decode-fail'] += 1
        continue
    w = u32le(b, 6)
    st['ver=%d' % w[1]] += 1
    st['len==w3+w4+%d' % (24 if len(b) == w[3] + w[4] + 24 else -1)] += 1
    st['w3>len||w4>len'] += 1 if (w[3] > len(b) or w[4] > len(b)) else 0
for k, v in st.most_common(10):
    print('   ', k, v)

print('\n=== item3: tani string graph ===')
kinds = collections.Counter()
for row in c.execute("select * from resources where ext='.tani' limit 300"):
    b, _ = R.get(row)
    if not b:
        continue
    for s in strings(b, 400):
        ext = s[s.rfind('.'):] if '.' in s[-6:] else ''
        if s.endswith('.pu') or s.endswith('.mesh') or s.endswith('.ogg') or s.endswith('.tga') or s.endswith('.wav'):
            kinds[s.rsplit('.', 1)[1]] += 1
print('  referenced target extensions (300-file sample):', kinds.most_common(10))
tg = collections.Counter()
for row in c.execute("select * from resources where ext='.tani' limit 200"):
    b, _ = R.get(row)
    if not b:
        continue
    tg[('skill' in b, 'hit' in b, 'idle' in b, 'walksound' in b, 'Lightmap' in b, 'terrain' in b.lower())] += 1
print('  keyword presence buckets:', tg.most_common(6))
print('  tani referenced by JBCF refs?', q("select count(*) from refs where to_hash in (select hash from resources where ext='.tani')"))
