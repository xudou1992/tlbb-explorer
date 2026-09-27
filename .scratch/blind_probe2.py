import sys, struct, re, random, collections, hashlib
sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le

R = Reader()
c = conn()
random.seed(11)

print('===== A. item1: set/.scene structure =====')
rows = c.execute("select * from resources where type='set' and ext='.scene' order by original desc limit 4").fetchall()
for row in rows[:2]:
    b, why = R.get(row)
    print('--', row['path'], row['props'][:200])
    print('   len', len(b), why)
    print('   head hex', b[:96].hex(' '))
    print('   u32x12', u32le(b, 12))
    banner = b.find(b'\x00', 0)
    print('   firstNUL at', banner)
    # printable after banner
    tail = b[banner:banner + 600]
    print('   after-banner', repr(tail[:300]))
    print('   all strs(head 3KB)', strings(b[:3000], 30))
    print('   ".mesh" anywhere?', b'.mesh' in b, ' count:', b.count(b'.mesh'))
    print('   ".pu" anywhere?', b.count(b'.pu'), ' ".tga"?', b.count(b'.tga'), ' ".dds"?', b.count(b'.dds'))
    print('   tail hex', b[-48:].hex(' '))
    print('   len hist check')

# structural scan over all 295
print('\n-- scan all 295 --')
prof = collections.Counter()
nmesh = 0
lens = []
for row in c.execute("select * from resources where type='set' and ext='.scene'"):
    b, why = R.get(row)
    if b is None:
        prof['decode-fail'] += 1
        continue
    lens.append(len(b))
    prof['len%%16=%d' % (len(b) % 16)] += 1
    if b'.mesh' in b:
        nmesh += 1
    # banner ends at first NUL
    z = b.find(b'\x00')
    w = u32le(b[z:z + 40], 8)
    prof['postbanner_u32_0=%d' % (w[0] if w else -1)] += 1
    prof['has_julekeji'] += 1 if b'julekeji' in b else 0
print('  .mesh-containing:', nmesh, '/295')
for k, v in prof.most_common(18):
    print('   ', k, v)
print('  len min/max/median:', min(lens), max(lens), sorted(lens)[len(lens)//2])

print('\n-- compare: named .mesh header (type=mesh) --')
for row in c.execute("select * from resources where ext='.mesh' and named=1 limit 3"):
    b, why = R.get(row)
    if not b:
        print('  fail', why); continue
    z = b.find(b'\x00')
    print('  ', row['path'], 'len', len(b), 'why', why)
    print('    head', b[:80].hex(' '))
    print('    strs', strings(b[:2500], 14))
    print('    postNUL u32x8', u32le(b[z:z+40], 8))
    print('    props', row['props'][:220])

print('\n-- props key set by type --')
for row in c.execute("select type,subtype,ext,count(*) n from resources where props like '%banner%' group by 1,2,3 order by n desc limit 12"):
    print('  ', tuple(row))

print('\n===== B. item6: geom/raw structure =====')
gr = c.execute("select * from resources where type='geom' order by original desc").fetchall()
print('  total geom rows', len(gr))
samples = random.sample(gr, 60)
qs = collections.Counter(); q5 = collections.Counter(); lens = collections.Counter()
floatish = collections.Counter()
for row in samples:
    b, why = R.get(row)
    if not b:
        print('  fail', row['hash'], why); continue
    w = u32le(b, 8)
    qs.append if False else qs.update([tuple(w[:4])])
    q5.update([w[4]])
    lens.update([len(b)])
    # how much of body looks like plausible float32 (finite, |x|<1e6)
    body = b[24:24+4000]
    vals = struct.unpack('<%df' % (len(body)//4), body[:len(body)//4*4])
    ok = sum(1 for v in vals if v == v and abs(v) < 1e7)
    floatish.update([round(ok / max(1, len(vals)) * 100)])
print('  first4-quad hist:', qs.most_common(5))
print('  word4 hist:', q5.most_common(5))
print('  len hist:', lens.most_common(6))
print('  %float-plausible buckets:', floatish.most_common(6))
b0 = None
for row in samples:
    b, why = R.get(row)
    if b and len(b) == 109960:
        b0 = b; off0 = row['offset']; break
print('  one blob hex @0     ', b0[:64].hex(' '))
print('  one blob hex @101412', b0[101412-8:101412+56].hex(' '))
print('  one blob hex @end-64', b0[-64:].hex(' '))
print('  bytes at 101412..101440 as u32:', u32le(b0[101412:101444], 8))
print('  (len-101412)=', len(b0) - 101412)
print('  distinct-byte-entropy head: zeros in first 101412?', b0[24:101412].count(0), 'of', 101412-24)

print('\n-- cross-type fingerprint search: is the geom prefix found inside named .mesh? --')
PAT = bytes([0,0,0,0,1,0,0,0,4,0,0,0,2,0,0,0]) + struct.pack('<I', 101412) + b'\x00\x00\x00\x00'
hits = collections.Counter()
scanned = collections.Counter()
for typ, pat in [("geom", None)]:
    pass
SQL = {
    'mesh_named': "select * from resources where ext='.mesh' and named=1",
    'geom': "select * from resources where type='geom'",
    'scene_grid753_named': "select * from resources where subtype='grid753' and named=1",
    'set_scene': "select * from resources where type='set' and ext='.scene'",
    'map': "select * from resources where ext='.map'",
    'sfl': "select * from resources where ext='.sfl'",
    'nav': "select * from resources where type='NAVF'",
}
for label, sql in SQL.items():
    rows = c.execute(sql).fetchall()
    rows = random.sample(rows, min(120, len(rows)))
    h = 0; tot = 0
    for row in rows:
        b, why = R.get(row)
        if not b:
            continue
        tot += 1
        if PAT in b:
            h += 1
    print('  %-18s files=%3d with geom-prefix-pATTERN=%3d' % (label, tot, h))
    scanned.update({label: tot})

print('\n===== C. item3: .tani prefix distribution + refs =====')
names = [r[0] for r in c.execute("select name from resources where ext='.tani'")]
pref = collections.Counter(n.split('_')[0] for n in names)
print('  name-prefix hist:', pref.most_common(20))
print('  total', len(names))
print('  props ref present:', c.execute("select count(*) from resources where ext='.tani' and props like '%ref%'").fetchone()[0])

print('\n===== D. item5: mapref pointer-body test =====')
import sqlite3 as s2
ptr = collections.Counter(); other = collections.Counter(); pairs = collections.Counter()
vals = []
for row in c.execute("select * from resources where type='mapref'"):
    b, why = R.get(row)
    if not b:
        continue
    w = u32le(b, 72)
    for i in range(3, 71, 2):
        lo, hi = w[i], w[i+1]
        p = (hi << 32) | lo
        vals.append(p)
        if hi < 0x10000 and 0x1000 <= p < 0x7FFFFFFFFFFF:
            ptr['heap-like 0x1xxx/0x7xxx'] += 1
        elif lo in (0xFFFFFFFE, 0xFFFFFFFF):
            ptr['sentinel'] += 1
        elif p == 0:
            ptr['null'] += 1
        else:
            other['%x' % (p >> 40)] += 1
tot = sum(ptr.values()) + sum(other.values())
print('  pointer-like pairs:', dict(ptr), ' other:', other.most_common(6), ' total pairs', tot)
print('  ptr range:', hex(min(v for v in vals if v)), hex(max(vals)))
# do these numbers match anything in the pak offsets?
offs = set(r[0] for r in c.execute("select offset from resources"))
print('  body values matching pak offsets:', sum(1 for v in vals if v in offs), '/', len(vals))
orig = set(r[0] for r in c.execute("select original from resources"))
print('  body values matching any resource original-size:', sum(1 for v in vals if v in orig and v < 2**32))
print('  unique 64-bit words:', len(set(vals)), 'of', len(vals))
