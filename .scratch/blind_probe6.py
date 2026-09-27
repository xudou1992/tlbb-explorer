import sys, re, struct, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, u32le

R = Reader()
c = conn()
q = lambda s: [tuple(r) for r in c.execute(s).fetchall()]

print('=== A. per-dir lattice completeness (grid753 + tiny stubs) ===')
rows = q("select dir,name,subtype from resources where dir like 'mobile_maps/%' and ext='.scene'")
pat = re.compile(r'^(\d+)_(-?\d+)_(-?\d+)\.scene$')
per = collections.defaultdict(dict)
for d, n, sub in rows:
    m = pat.match(n or '')
    if m:
        per[d][tuple(int(x) for x in m.groups()[1:])] = sub
print('  dirs with cell-shaped .scene:', len(per))
holes_tot = 0
dirs_with_holes = 0
for d, cells in per.items():
    xs = [k[0] for k in cells]; zs = [k[1] for k in cells]
    span = (max(xs) - min(xs) + 1) * (max(zs) - min(zs) + 1)
    h = span - len(cells)
    holes_tot += h
    dirs_with_holes += 1 if h > 0 else 0
print('  within-bbox empty cells across all dirs: %d in %d dirs' % (holes_tot, dirs_with_holes))
print('  cell subtype mix:', collections.Counter(s for cells in per.values() for s in cells.values()))

print('\n=== B. which mobile_maps dirs have NO grid753 at all ===')
alld = q("select distinct dir from resources where dir like 'mobile_maps/%'")
setd = {r[0] for r in q("select distinct dir from resources where type='set' and ext='.scene'")}
gridd = {r[0] for r in q("select distinct dir from resources where subtype='grid753' and named=1")}
tinyd = {r[0] for r in q("select distinct dir from resources where subtype='bin' and ext='.scene' and named=1")}
mapd = {r[0] for r in q("select distinct dir from resources where ext='.map' and named=1")}
sfld = {r[0] for r in q("select distinct dir from resources where ext='.sfl' and named=1")}
navd = {r[0] for r in q("select distinct dir from resources where type='NAVF' and named=1")}
D = {r[0] for r in alld}
print('  dirs total=%d | with set-root=%d | grid753=%d | tiny-stub=%d | .map=%d | .sfl=%d | .nav=%d'
      % (len(D), len(setd), len(gridd), len(tinyd), len(mapd), len(sfld), len(navd)))
print('  set-root dirs WITHOUT any grid753:', len(setd - gridd))
print('  sfl dirs WITHOUT grid753:', len(sfld - gridd))
print('  map dirs WITHOUT grid753:', len(mapd - gridd))
print('  grid753 dirs WITHOUT set-root:', len(gridd - setd))
print('  example set-root-no-grid dirs:', sorted(setd - gridd)[:6])
print('  grid753 dirs whose cells are all tiny (empty maps):',
      [d for d in gridd if d not in {dd for dd, cc in per.items() if any(v == "grid753" for v in cc.values())}][:5])
print('\n  how many grid cells per set-root-no-grid dir would be needed (avg from others): %.1f'
      % (sum(len(v) for k, v in per.items() if k in gridd) / max(1, len(gridd))))

print('\n=== C. mapref pointer-body statistics ===')
vals = []
align = collections.Counter()
files = 0
rep = collections.Counter()
for row in c.execute("select * from resources where type='mapref'"):
    b, _ = R.get(row)
    if not b:
        continue
    files += 1
    w = u32le(b, 72)
    for i in range(3, 71, 2):
        p = (w[i + 1] << 32) | w[i]
        vals.append(p)
        rep[p] += 1
        if p == 0:
            align['null'] += 1
        elif p >= (1 << 32):
            if p >> 44 in (0x7FF, 0x7FE, 0x1F3, 0x1F4, 0x1F5, 0x2, 0x3):
                align['ptr-range hi=0x%x' % (p >> 40)] += 1
            else:
                align['nonptr-big hi=0x%x' % (p >> 40)] += 1
        else:
            align['small-int(<4G)'] += 1
print('  files=%d pairs=%d distinct=%d' % (files, len(vals), len(set(vals))))
for k, v in align.most_common(14):
    print('   ', k, v)
low_mult8 = sum(1 for v in vals if v and v % 8 == 0)
print('  pairs divisible by 8: %d/%d (%.0f%%)' % (low_mult8, len(vals), 100 * low_mult8 / len(vals)))
top = rep.most_common(8)
print('  most repeated 64-bit values:', [(hex(v), n) for v, n in top])
print('  values appearing in >100 files:', sum(1 for v, n in rep.items() if n > 100))
print('  max word index range check: are pairs 8-aligned u64?')

print('\n=== D. NAVF: is it grid/navmesh? section guess ===')
for row in c.execute("select * from resources where ext='.nav' order by original desc limit 2"):
    b, _ = R.get(row)
    w = u32le(b, 40)
    print('  ', row['path'], 'len', len(b))
    print('    w[0:6]', w[:6], ' w[6:20]', w[6:20])
    print('    last 32 bytes', b[-32:].hex(' '))
    print('    bytes/ (w2) =', len(b) / max(1, w[2]))
print('  NAVF family totals:', q("select named,count(*),sum(original) from resources where type='NAVF' group by 1"))
