import sys, struct, re, random, collections, hashlib, binascii
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le

R = Reader()
c = conn()
q = lambda s: c.execute(s).fetchall()
random.seed(3)

print('=== item2: flags/manifest test for grid753 ===')
for r in q("select named, flags&1 as has_path_manifest, flags, count(*) from resources where subtype='grid753' group by 1,2,3 order by 4 desc"):
    print('  named=%s manifest=%s flags=%s n=%s' % tuple(r))
for r in q("select named, src, count(*) from resources where subtype='grid753' group by 1,2"):
    print('  src:', tuple(r))

print('\n-- duplicate-content check via blobs.sha --')
print('  blobs cols:', [x[1] for x in q("PRAGMA table_info(blobs)")][:5])
r = q("""select count(*), count(distinct sha) from blobs where hash in
         (select hash from resources where subtype='grid753' and named=0)""")
print('  unnamed: rows/distinct-sha', r)
r = q("""select count(*) from blobs b join resources x on x.hash=b.hash and x.subtype='grid753' and x.named=0
         where exists(select 1 from blobs b2 join resources r2 on r2.hash=b2.hash
                      where b2.sha=b.sha and r2.subtype='grid753' and r2.named=1)""")
print('  unnamed whose sha equals a NAMED grid753 sha:', r)
r = q("""select size, count(*) from blobs where hash in
         (select hash from resources where subtype='grid753' and named=0) group by 1 order by 2 desc limit 5""")
print('  blobs.size sample (is it stored or original?):', r[:3])
r = q("select b.hash,b.sha,b.size,r.original from blobs b join resources r on r.hash=b.hash where r.subtype='grid753' and r.named=0 limit 3")
print('  compare blobs.size vs original:', r)

print('\n-- filecrc collisions with named grid753? --')
r = q("""select count(*) from resources a where a.subtype='grid753' and a.named=0 and exists(
           select 1 from resources b where b.subtype='grid753' and b.named=1 and b.filecrc=a.filecrc)""")
print('  unnamed with same filecrc as a named one:', r)
r = q("select count(*), count(distinct filecrc) from resources where subtype='grid753'")
print('  all grid753 rows / distinct filecrc:', r)

print('\n-- adjacency heuristic: same pak & gen as named grid753? --')
r = q("""select a.pak, a.gen, count(*) from resources a where a.subtype='grid753' and a.named=0
         group by 1,2 order by 3 desc limit 8""")
print('  ', r)
r = q("select count(distinct dir) from resources where ext in ('.map','.sfl') and named=1")
print('  distinct map dirs (.map/.sfl):', r)
r = q("select ext, count(*), count(distinct dir) from resources where ext in ('.map','.sfl','.nav') and named=1 group by 1")
print('  per-ext dir coverage:', r)
r = q("""select count(distinct m.dir) from resources m where m.ext='.map' and m.named=1 and not exists(
          select 1 from resources s where s.subtype='grid753' and s.named=1 and s.dir=m.dir)""")
print('  .map dirs lacking any named grid753:', r)

print('\n-- could unnamed fill grid slots? sample names in dirs --')
r = q("select dir, count(*) from resources where subtype='grid753' and named=1 group by 1 order by 2 desc limit 5")
print('  grids per dir top:', r)
r = q("select min(n), max(n), avg(n) from (select count(*) n from resources where subtype='grid753' and named=1 group by dir)")
print('  grids-per-dir min/max/avg:', r)
r = q("select name from resources where subtype='grid753' and named=1 limit 12")
print('  grid naming:', [x[0] for x in r])

print('\n=== geom: refs linkage + duplicate sha ===')
ph = q("select count(*) from resources where type='geom'")[0][0]
r = q("select count(*) from refs where to_hash in (select hash from resources where type='geom')")
print('  geom referenced in refs:', r)
r = q("select count(*) from relations where to_hash in (select hash from resources where type='geom')")
print('  geom in relations.to:', r)
r = q("select count(*), count(distinct b.sha) from blobs b join resources r on r.hash=b.hash where r.type='geom'")
print('  geom rows / distinct sha:', r)
r = q("select count(*) from resources a where a.type='geom' and exists(select 1 from resources b where b.type='geom' and b.hash<>a.hash and b.filecrc=a.filecrc)")
print('  geom with duplicate filecrc:', r)
r = q("select flags, method, count(*) from resources where type='geom' group by 1,2 order by 3 desc limit 5")
print('  geom flags/method:', r)

print('\n=== decisive: do geom blobs appear inside named .mesh payloads? (window search) ===')
mesh_rows = q("select * from resources where ext='.mesh' and named=1")
mesh_rows = random.sample(mesh_rows, 250)
geom_rows = q("select * from resources where type='geom'")
geom_rows = random.sample(geom_rows, 12)
# build a set of 16-byte hex fingerprints from mesh payloads at every 4 bytes
fp = set()
for row in mesh_rows:
    b, why = R.get(row)
    if not b:
        continue
    for i in range(0, len(b) - 16, 4):
        fp.add(b[i:i+16])
print('  mesh windows:', len(fp), 'from', len(mesh_rows), 'files')
hit = 0; tot = 0
for row in geom_rows:
    b, why = R.get(row)
    if not b:
        continue
    tot += 1
    found = any(b[i:i+16] in fp for i in range(24, min(len(b)-16, 101400), 64))
    hit += 1 if found else 0
print('  geom blobs with >=1 window inside sampled mesh payloads: %d/%d' % (hit, tot))

print('\n=== mesh internal layout: is there a (0,1,4,2)+101412 section? ===')
row = q("select * from resources where ext='.mesh' and named=1 limit 1")[0]
b, _ = R.get(row)
print('  ', row['path'], len(b))
print('   hex@0   ', b[:128].hex(' '))
for probe_off in (128, 256, 512, 1024):
    print('   hex@%-5d' % probe_off, b[probe_off:probe_off+64].hex(' '))
i = b.find(struct.pack('<I', 101412))
print('   offset of u32 101412 in this mesh:', i)
print('   strs', strings(b, 20))
