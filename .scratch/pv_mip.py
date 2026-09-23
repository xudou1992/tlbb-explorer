"""One-off: pin down the JMT1 mip table and the pixel start offset.

Hypothesis under test:
  +0  'JMT1'   +4 codec4CC  +8 u32 sub-format  +12 u32 (=filesize-24)
  +16 u16 w    +18 u16 h    +20 u32 mips        +24 u32 level-0 byte size
  +28 ...      [sub-table | pixel data]
"""
import os, sqlite3, struct, collections

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


def chain(w, h, mips, blk):
    """DDS-style mip sum: block size `blk` bytes, min 1 block per axis."""
    tot, W, H = 0, max(1, w), max(1, h)
    sizes = []
    for i in range(mips):
        bw, bh = max(1, (W + 3) // 4), max(1, (H + 3) // 4)
        s = bw * bh * blk
        sizes.append(s)
        tot += s
        W, H = max(1, W // 2), max(1, H // 2)
    return tot, sizes


res = collections.Counter()
odd = []
for h, codec, w, hh, mips in con.execute(
        "select hash,codec,width,height,mips from resources where type='texture'"):
    p = FIND.get(h)
    if not p:
        continue
    sz = os.path.getsize(p)
    with open(p, 'rb') as f:
        b = f.read(2048)
    f8, blob, pw, ph, m, l0 = struct.unpack_from('<IIHHII', b, 8)
    if m != mips or pw != w or ph != hh:
        res['DB-MISMATCH %s/%s/%s vs %s/%s/%s' % (pw, ph, m, w, hh, mips)] += 1
    if codec in ('COLW',):
        continue
    blk = 8 if f8 == 0x83f0 else (16 if f8 == 0x83f3 else 0)
    if blk == 0:
        res['nonblock %s f8=0x%x' % (codec, f8)] += 1
        continue
    tot, sizes = chain(pw, ph, m, blk)
    extra = sz - 28 - tot
    res['extra=%d m=%d' % (extra, m)] += 1
    res['fmt f8=0x%x bpp=%.1f' % (f8, l0 * 8.0 / (pw * ph))] += 1
    if extra != 4 * (m - 1) and len(odd) < 12:
        odd.append((h, codec, pw, ph, m, l0, sz, tot, extra, f8))

for k, v in res.most_common(30):
    print('%-40s %6d' % (k, v))
print()
print('odd samples (extra != 4*(m-1)):')
for o in odd:
    print('   ', o)
