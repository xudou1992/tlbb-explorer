import sys, struct, random, collections
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings

R = Reader()
c = conn()
q = lambda s: c.execute(s).fetchall()
random.seed(3)

print('=== item2: flags/manifest for grid753 ===')
for r in q("select named, flags&1, count(*) from resources where subtype='grid753' group by 1,2"):
    print('  named=%s manifest=%s n=%s' % tuple(r))
print('  src:', q("select named, src, count(*) from resources where subtype='grid753' group by 1,2"))

print('\n=== dup-content test (filecrc + sha) computed in python ===')
g = q("select hash,named,filecrc,original from resources where subtype='grid753'")
named_crc = {r[2] for r in g if r[1] == 1}
un = [r for r in g if r[1] == 0]
print('  unnamed=%d, unnamed filecrc also seen in named=%d' % (len(un), sum(1 for r in un if r[2] in named_crc)))
sh = q("select b.sha, x.named from blobs b join resources x on x.hash=b.hash where x.subtype='grid753'")
ns = {s for s, n in sh if n == 1}
us = [(s, n) for s, n in sh if n == 0]
print('  sha rows named=%d unnamed=%d ; unnamed sha in named set=%d ; distinct unnamed sha=%d'
      % (len(ns), len(us), sum(1 for s, _ in us if s in ns), len({s for s, _ in us})))
print('  distinct filecrc all grid753:', q("select count(distinct filecrc) from resources where subtype='grid753'"))

print('\n=== geom dup test (no self-join) ===')
gcrc = collections.Counter(r[0] for r in q("select filecrc from resources where type='geom'"))
print('  geom rows=%d distinct filecrc=%d duplicated rows=%d' % (sum(gcrc.values()), len(gcrc), sum(v for v in gcrc.values() if v > 1)))
gs = collections.Counter(r[0] for r in q("select b.sha from blobs b join resources x on x.hash=b.hash where x.type='geom'"))
print('  geom blobs rows=%d distinct sha=%d' % (sum(gs.values()), len(gs)))
print('  geom flags/method:', q("select flags,method,count(*) from resources where type='geom' group by 1,2 order by 3 desc limit 5"))

print('\n=== geom referenced anywhere? ===')
ge = {r[0] for r in q("select hash from resources where type='geom'")}
print('  refs.to_hash hits:', sum(1 for r in q("select distinct to_hash from refs") if r[0] in ge))
print('  relations.to hits:', sum(1 for r in q("select distinct to_hash from relations") if r[0] in ge))
print('  assets hits:', sum(1 for r in q("select primary_hash from assets") if r[0] in ge))

print('\n=== map dirs coverage ===')
print('  per-ext:', q("select ext, count(*), count(distinct dir) from resources where ext in ('.map','.sfl','.nav') and named=1 group by 1"))
print('  grids/dir:', q("select min(n),max(n),avg(n) from (select count(*) n from resources where subtype='grid753' and named=1 group by dir)"))
print('  naming:', [x[0] for x in q("select name from resources where subtype='grid753' and named=1 limit 10")])
print('  .map dirs with NO named grid753:', q("""select count(*) from (select dir from resources where ext='.map' and named=1 group by dir
      except select dir from resources where subtype='grid753' and named=1 group by dir)"""))
print('  all named dirs:', q("select count(distinct dir) from resources where dir like 'mobile_maps/%'"))

print('\n=== decisive: geom windows vs mesh payload windows ===')
mesh_rows = random.sample(q("select * from resources where ext='.mesh' and named=1"), 200)
fp = set()
nm = 0
for row in mesh_rows:
    b, why = R.get(row)
    if not b:
        continue
    nm += 1
    for i in range(0, len(b) - 16, 8):
        fp.add(b[i:i + 16])
print('  mesh files decoded=%d, windows=%d' % (nm, len(fp)))
hit = tot = 0
for row in random.sample(q("select * from resources where type='geom'"), 20):
    b, why = R.get(row)
    if not b:
        continue
    tot += 1
    f = any(b[i:i + 16] in fp for i in range(24, 101400, 256))
    hit += 1 if f else 0
print('  geom blobs sharing a 16B window with sampled mesh payloads: %d/%d' % (hit, tot))

print('\n=== mesh layout dump ===')
for row in q("select * from resources where ext='.mesh' and named=1 limit 2"):
    b, _ = R.get(row)
    print(' ', row['path'], len(b))
    print('   hex@0  ', b[:160].hex(' '))
    i = b.find(struct.pack('<I', 101412))
    print('   u32 101412 at', i, ' | "mesh" token at', b.find(b'mesh'), b.find(b'mesh', b.find(b'mesh') + 1))
    print('   strs ', strings(b[:900], 12))
