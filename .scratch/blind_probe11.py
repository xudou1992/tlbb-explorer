import sys, re, random, collections, struct
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]
rows = lambda s: c.execute(s).fetchall()
random.seed(31)
MESHNAME = re.compile(r'[\w/\.\-]+\.mesh')

print('=== 1. the 3 oversized set/.scene (436609B): identical content? ===')
print('  ', q("select hash,path,stored,original,filecrc from resources where type='set' and ext='.scene' and original=436609"))
print('  blobs sha:', q("select b.sha, count(*) from blobs b join resources r on r.hash=b.hash where r.type='set' and r.original=436609 group by 1"))
print('  all type=set: distinct filecrc vs rows:', q("select count(*), count(distinct filecrc) from resources where type='set' and ext='.scene'"))
print('  entry-name totals over all 295:')
tot = collections.Counter()
for row in rows("select * from resources where type='set' and ext='.scene'"):
    b, _ = R.get(row)
    if not b:
        continue
    for s in strings(b, 4000):
        if s.startswith(('HQ_Lightmap', 'LQ_Lightmap', 'StaticShadow')):
            tot['entry'] += 1
        if '.mesh' in s:
            tot['meshname'] += 1
    tot['files'] += 1
print('   ', dict(tot))
print('  entries per file:', q("select count(*)/295"))

print('\n=== 2. can unnamed grid753 be re-attached to a map dir? (content subset test) ===')
dirs = [d for (d,) in q("select distinct dir from resources where subtype='grid753' and named=1 order by random() limit 60")]
dirnames = {}
for d in dirs:
    dirnames[d] = set()
for row in rows("select * from resources where subtype='grid753' and named=1 and dir in (%s)" % ','.join(['?'] * len(dirs))):
    b, _ = R.get(row)
    if not b:
        continue
    s = set(MESHNAME.findall(' '.join(strings(b, 900))))
    dirnames[row['dir']] |= s
print('  dirs built=%d avg mesh-names/dir=%.1f' % (len(dirnames), sum(len(v) for v in dirnames.values()) / max(1, len(dirnames))))
res = collections.Counter(); detail = []
un = rows("select * from resources where subtype='grid753' and named=0")
for row in random.sample(un, 60):
    b, _ = R.get(row)
    if not b:
        continue
    names = set(MESHNAME.findall(' '.join(strings(b, 900))))
    if not names:
        res['no mesh names in table'] += 1
        continue
    sc = []
    for d, s in dirnames.items():
        if s:
            j = len(names & s) / len(names | s)
            sc.append((j, d))
    sc.sort(reverse=True)
    best, second = (sc[0][0], sc[1][0] if len(sc) > 1 else 0.0)
    res['best jaccard %.1f-%.1f' % (min(int(best * 5) / 5, 0.8), min(int(best * 5) / 5 + 0.2, 1.0))] += 1
    detail.append((row['hash'], len(names), round(best, 3), round(second, 3), best - second, dirs and sc[0][1]))
print('  result hist (60 unnamed grids vs 60 random dirs):', res.most_common())
print('  margin best-vs-second >=0.15 (i.e. unambiguous):', sum(1 for x in detail if x[4] >= 0.15), '/', len(detail))
for x in detail[:8]:
    print('   ', x)
print('  NOTE: only 60 of 223 dirs were used as candidates, so real ambiguity is higher.')

print('\n=== 3. do unnamed grid753 carry a map id string anywhere? ===')
n = 0
for row in random.sample(un, 25):
    b, _ = R.get(row)
    if not b:
        continue
    for s in strings(b, 900):
        if re.search(r'^w1351_(ll|fb|gj|hd|cj)_\w+_\d+$', s) or 'mobile_maps' in s:
            n += 1
            print('   ', row['hash'], repr(s))
            break
print('  files containing a map-id-like token:', n, '/25')
print('  distinct mesh-name prefixes inside unnamed tables (first token):',
      collections.Counter(s.split('_')[1] for row in random.sample(un, 40) for s in strings(R.get(row)[0], 900)
                          if s.endswith('.mesh') and s.startswith('w1351_')).most_common(12))
