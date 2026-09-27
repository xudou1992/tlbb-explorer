import sys, re, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]

print('=== gen distribution by class (are nameless blobs patch-generated?) ===')
for r in q("""select case when type='geom' then 'geom' when subtype='grid753' and named=0 then 'grid753-un'
                when subtype='grid753' then 'grid753-named' when type='mapref' then 'mapref'
                when type='NAVF' and named=0 then 'NAVF-un' when type='texture' and named=0 then 'tex-un'
                else 'other' end cls, min(gen), max(gen), count(distinct gen), count(*),
                cast(sum(original)/count(*) as int) avg_orig
              from resources group by 1 order by 6 desc"""):
    print('  ', r)

print('\n=== the 71 set-root dirs with no grid753: what do they contain? ===')
setd = {r[0] for r in q("select distinct dir from resources where type='set' and ext='.scene'")}
gridd = {r[0] for r in q("select distinct dir from resources where subtype='grid753' and named=1")}
nog = sorted(setd - gridd)
ph = ','.join(['?'] * len(nog))
mix = collections.Counter()
for d, sub, n in q("select dir,subtype,count(*) from resources where dir in (%s) group by 1,2" % ph, nog):
    pass
rows = q("select dir,ext,subtype,count(*) from resources where dir in (%s) group by 1,2,3" % ph)
per = collections.defaultdict(dict)
for d, e, s, n in rows:
    per[d][(e or '-', s or '-')] = n
pat = collections.Counter()
for d, m in per.items():
    pat[tuple(sorted(m.items()))] += 1
for k, v in pat.most_common(6):
    print('  %2d dirs: %s' % (v, k))
print('  dirs among the 71 that have scene cells at all:',
      sum(1 for d, m in per.items() if any(e == '.scene' for (e, s) in m)))

print('\n=== can unnamed grid753 be re-attached to a map dir by mesh-family signature? ===')
FAM = re.compile(r'w1351_([a-z]+)_')
dirfam = collections.defaultdict(collections.Counter)
named = q("select * from resources where subtype='grid753' and named=1")
import random
random.seed(5)
for row in random.sample(named, 500):
    b, _ = R.get(row)
    if not b:
        continue
    for s in strings(b, 4000):
        for m in FAM.findall(s):
            dirfam[row['dir']][m] += 1
print('  dirs sampled:', len(dirfam), 'family-vocab:', len({f for v in dirfam.values() for f in v}))
res = collections.Counter(); ex = []
un = q("select * from resources where subtype='grid753' and named=0")
for row in random.sample(un, 40):
    b, _ = R.get(row)
    if not b:
        continue
    fams = {m for s in strings(b, 4000) for m in FAM.findall(s)}
    cands = [d for d, v in dirfam.items() if fams and fams <= set(v)]
    res['%d candidates' % min(len(cands), 9)] += 1
    ex.append((row['hash'], sorted(fams)[:6], len(cands)))
print('  candidate-dir count hist over 40 unnamed grids:', res.most_common())
for e in ex[:6]:
    print('   ', e)
print('  (note: dirfam built from only 500 of 9288 named grids, so candidate counts are upper bounds)')

print('\n=== lightmap/shadow naming inside set/.scene (how many entries) ===')
n = collections.Counter()
for row in q("select * from resources where type='set' and ext='.scene' order by original desc limit 40"):
    b, _ = R.get(row)
    names = [s for s in strings(b, 2000) if 'Lightmap' in s or 'Shadow' in s]
    n[len(names)] += 1
print('  entries-per-file hist:', sorted(n.items())[:14])

print('\n=== geom: is 101412 == vertex-stream length? index section sanity ===')
import struct
for row in q("select * from resources where type='geom' limit 6"):
    b, _ = R.get(row)
    if not b:
        continue
    L = struct.unpack('<I', b[16:20])[0]
    tail = b[L:]
    nz = sum(1 for i in range(24, L, 4) if struct.unpack_from('<f', b, i)[0] != 0.0)
    print('  len=%d hdr4=%s stream_len=%d bytes_after=%d floatwords=%d/%d verts12B=%d verts20B=%d'
          % (len(b), b[:16].hex(), L, len(b) - L, nz, (L - 24) // 4, (L - 24) / 12.0, (L - 24) / 20.0))
