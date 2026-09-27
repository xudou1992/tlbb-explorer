"""READ-ONLY final cross-checks.
A. corroborate the recovered grid paths against their payload content
B. clean classification of the mapref 280B body
C. .tani internal record stride + whether its references resolve to real entities
D. set/.scene container: entry stride + how many entries
"""
import collections
import random
import re
import struct
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader, strings, u32le  # noqa: E402
from jhash import path_hash  # noqa: E402

C = conn()
R = Reader()
Q = lambda s: [tuple(x) for x in C.execute(s).fetchall()]
random.seed(7)
FAM = re.compile(r'w1351_([a-z]{2,6})_')


def dec(h):
    row = C.execute('select * from resources where hash=?', (h,)).fetchone()
    return R.get(row) if row else (None, 'no-row')


# recover the nameless grid753 paths again (same enumeration)
un = dict(Q("select hash,original from resources where subtype='grid753' and named=0"))
dirs = [d for (d,) in Q("select distinct dir from resources where dir like 'mobile_maps/%'")]
found = {}
for d in dirs:
    for a in range(0, 4):
        for y in range(-6, 18):
            for z in range(-18, 6):
                k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, y, z))
                if k in un:
                    found[k] = (d, a, y, z)

print('=== A. corroboration: payload mesh names vs recovered map dir ===')
agree = disagree = nodata = 0
examples = []
for h, (d, a, y, z) in list(found.items())[:250]:
    b, _ = dec(h)
    if not b:
        nodata += 1
        continue
    fams = collections.Counter()
    for s in strings(b, 900):
        for m in FAM.findall(s):
            fams[m] += 1
    leaf = d.split('/')[-1]
    key = leaf.split('_')[2] if len(leaf.split('_')) > 2 else '?'
    if not fams:
        nodata += 1
        continue
    top, n = fams.most_common(1)[0]
    tot = sum(fams.values())
    if top == key:
        agree += 1
    else:
        disagree += 1
    if len(examples) < 6:
        examples.append((leaf, top, '%d/%d' % (n, tot), dict(fams.most_common(3))))
print('  dominant object family == map dir family: %d ; different: %d ; no-data: %d' % (agree, disagree, nodata))
for e in examples:
    print('   ', e)
print('  NOTE: 副本图常用别的图的物件前缀, 所以"不同"不等于复原错误; 真正硬证据是 0 与有名格子撞位。')

print('\n=== A2. grid753 instance grammar on recovered files (count x stride) ===')
for h, (d, a, y, z) in list(found.items())[:4]:
    b, _ = dec(h)
    w = u32le(b, 2)
    n, tag = w[0], w[1]
    stride = 761 if tag == 753 else 757
    body = len(b) - 12
    print('  %-52s count=%-4d tag=%d len=%d  (len-12)/stride=%.2f  name@%r'
          % ('%s/%d_%d_%d.scene' % (d, a, y, z), n, tag, len(b), body / stride,
             (strings(b, 6) + ['-'])[1] if len(strings(b, 6)) > 1 else '-'))

print('\n=== B. mapref 288B body classification ===')
cls = collections.Counter()
npair = 0
for row in C.execute("select * from resources where type='mapref'"):
    b, _ = R.get(row)
    w = u32le(b, 72)
    for i in range(3, 72):
        v = w[i] if i < len(w) else 0
        if v == 0:
            cls['u32 zero'] += 1
        elif v <= 0x200:
            cls['u32 small <=0x200'] += 1
        elif 0x7F00_0000 <= v <= 0x7FFF_FFFF:
            cls['u32 = 0x7Fxxxxxx (stack/module high word)'] += 1
        elif 0x1F00_0000 <= v <= 0x1FFF_FFFF:
            cls['u32 = 0x1Fxxxxxx (heap high word)'] += 1
        elif 0xBF00_0000 <= v <= 0xBFFF_FFFF or 0x3F00_0000 <= v <= 0x3FFF_FFFF:
            cls['u32 = float32 in [1e-38..3e38] normalised band'] += 1
        elif v >= 0xFFFF_FFF0:
            cls['u32 = -1/-2 sentinel'] += 1
        else:
            cls['other'] += 1
    for i in range(4, 71, 2):
        p = (w[i] << 32) | w[i - 1]
        npair += 1
        hi = w[i]
        if 0x7F00_0000 <= hi <= 0x7FFF_FFFF or 0x1F00_0000 <= hi <= 0x1FFF_FFFF:
            cls['  [paired] u64 in x64 user address range'] += 1
offs = {r[0] for r in Q("select offset from resources")}
origs = {r[0] for r in Q("select original from resources")}
hashes = {int(r[0], 16) for r in Q("select hash from resources")}
hit_o = hit_s = hit_h = 0
for row in C.execute("select * from resources where type='mapref' limit 300"):
    b, _ = R.get(row)
    w = u32le(b, 72)
    for i in range(2, 72, 2):
        p = (w[i + 1] << 32) | w[i] if i + 1 < len(w) else 0
        hit_o += p in offs
        hit_s += p in origs
        hit_h += p in hashes
print('  12,886 u32 words in the 280B bodies:', cls.most_common(10))
print('  u64 pairs that equal a pak offset: %d ; a resource original size: %d ; a resource hash: %d (300 files)'
      % (hit_o, hit_s, hit_h))

print('\n=== C. .tani internals ===')
b, _ = dec(Q("select hash from resources where ext='.tani' order by original desc limit 1")[0][0])
print('  head hex[0:48] =', b[:48].hex(' '))
print('  self path len byte @0x08 =', b[8], ' u32[2..6]:', u32le(b, 8))
z = b.find(b'\x00', 8)
print('  after self-path: next u32s =', u32le(b[z + 1:z + 33], 8), ' hex =', b[z + 1:z + 33].hex(' '))
lens = collections.Counter()
for row in C.execute("select * from resources where ext='.tani' limit 400"):
    bb, _ = R.get(row)
    if bb:
        lens[len(bb)] += 1
print('  sizes all multiples of 4?', all(k % 4 == 0 for k in lens), ' gcd:',
      __import__('math').gcd(*list(lens)))
print('  distinct sizes among 400:', len(lens), ' top:', lens.most_common(4))
# do tani references resolve to real entities?
tgt_pu = {r[0] for r in Q("select path from resources where path is not null")}
res = collections.Counter()
for row in C.execute("select * from resources where ext='.tani' limit 60"):
    bb, _ = R.get(row)
    if not bb:
        continue
    for s in strings(bb, 200):
        if s.endswith(('.pu', '.wav', '.ogg', '.mesh')):
            if s in tgt_pu:
                res[s.rsplit('.', 1)[1] + ' resolves-to-db-path'] += 1
            else:
                res[s.rsplit('.', 1)[1] + ' bare-name'] += 1
                for p in ('data/effect/', 'data/sound/'):
                    if p + s in tgt_pu:
                        res[s.rsplit('.', 1)[1] + ' resolves-with-prefix'] += 1
                        break
print('  reference resolution over 60 .tani:', res.most_common())

print('\n=== D. set/.scene container entry stride ===')
for row in C.execute("select * from resources where type='set' and ext='.scene' and original between 1800 and 2200 limit 2"):
    b, _ = R.get(row)
    names = [(s, b.find(s.encode())) for s in strings(b, 900) if s.startswith(('HQ_Lightmap', 'LQ_Lightmap', 'StaticShadow'))]
    d = [names[i][1] - names[i - 1][1] for i in range(1, len(names))]
    print('  len=%d names=%d strides=%s ver@0x48=%d' % (len(b), len(names), d[:8], u32le(b, 20)[18]))
    print('   hex[0x90:0x110] =', b[0x90:0x110].hex(' '))
    i = b.find(b'StaticShadow')
    print('   around 1st name:', b[max(0, i - 32):i + 40].hex(' '))
