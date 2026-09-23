"""One-off: census the JMT1 header fields across every extracted texture."""
import os, sqlite3, struct, collections, json

HERE = os.path.dirname(os.path.abspath(__file__))
ALL = os.path.join(HERE, 'out', 'all')
con = sqlite3.connect(os.path.join(HERE, 'resources.db'))

FIND = {}
for pak in sorted(os.listdir(ALL)):
    d = os.path.join(ALL, pak)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if len(fn) >= 16:
            FIND.setdefault(fn[:16], os.path.join(d, fn))

stat = collections.defaultdict(lambda: collections.Counter())
ex = collections.defaultdict(list)
n = 0
for h, codec, w, hh, mips in con.execute(
        "select hash,codec,width,height,mips from resources where type='texture'"):
    p = FIND.get(h)
    if not p:
        stat[codec]['no-payload'] += 1
        continue
    sz = os.path.getsize(p)
    with open(p, 'rb') as f:
        b = f.read(64)
    if b[:4] != b'JMT1':
        stat[codec]['bad-magic'] += 1
        continue
    f8, blob, pw, ph, m, l0 = struct.unpack_from('<IIHHII', b, 8)
    c = stat[codec]
    c['u32@8=0x%x' % f8] += 1
    c['mips=%s' % m] += 1
    ratio = (l0 * 8.0) / max(1, w * hh)
    c['bpp=%.2f' % ratio] += 1
    c['blob==sz-24' if blob == sz - 24 else 'blob!=sz-24'] += 1
    c['l0==sz-28' if l0 == sz - 28 else ('l0+table==sz-28' if l0 + 4 * max(0, m - 1) == sz - 28
                                         else 'l0-vs-size-other')] += 1
    if m != mips or w != (pw & 0xffff) or hh != (pw >> 16):
        c['db-mismatch'] += 1
    n += 1
    if len(ex[codec]) < 6:
        ex[codec].append((h, sz, w, hh, m, l0, round(ratio, 3), f8, blob))

print('textures inspected:', n)
for c in sorted(stat, key=lambda x: -sum(stat[x].values())):
    tot = sum(stat[c].values())
    print('\n=== codec=%s  n=%d' % (c, tot))
    for k, v in stat[c].most_common(18):
        print('    %-22s %7d' % (k, v))
    for e in ex[c]:
        print('    ex hash=%s size=%d %dx%d mips=%d l0=%d bpp=%s u32@8=0x%x blob=%d' % e)
