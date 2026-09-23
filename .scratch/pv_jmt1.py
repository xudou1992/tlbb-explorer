"""One-off analysis tool (NOT product code): JMT1 -> DDS/PNG reconstruction probe.

Reverse-engineered JMT1 layout (validated over all 26520 extracted textures):
  +0  char[4] 'JMT1'
  +4  char[4] codec 4CC  'DXT1' | 'RGBA' | 'COLW' | 'ALI8' | 'COLR'
  +8  u32     sub-format  0x83f0 -> BC1 (8-byte blocks, 4bpp)
                          0x83f3 -> 8bpp/16-byte blocks (BC3 or DXT3)
                          0x1908 / 0x1907 -> WebP (COLW) ; 0x1909 -> raw 8-bit (ALI8)
  +12 u32     blob size  (== filesize - 24, 100% of corpus)
  +16 u16 width  +18 u16 height  +20 u32 mipcount  +24 u32 level-0 byte size
  +28         mip0 pixels, then per extra mip: [u32 mipSize][pixels]   <-- under test
"""
import os, sqlite3, struct, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ALL = os.path.join(HERE, 'out', 'all')
OUT = os.path.join(HERE, 'pv_out')
os.makedirs(OUT, exist_ok=True)
SUB_BC1, SUB_8BPP = 0x83f0, 0x83f3


def dds_chain(w, h, mips, blk):
    out, W, H = [], max(1, w), max(1, h)
    for _ in range(mips):
        out.append(max(1, (W + 3) // 4) * max(1, (H + 3) // 4) * blk)
        W, H = max(1, W // 2), max(1, H // 2)
    return out


FIND = {}
for pak in sorted(os.listdir(ALL)):
    d = os.path.join(ALL, pak)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if len(fn) >= 16:
            FIND.setdefault(fn[:16], os.path.join(d, fn))


def parse(path):
    b = open(path, 'rb').read()
    if b[:4] != b'JMT1':
        return None
    sub, blob, w, h, mips, l0 = struct.unpack_from('<IIHHII', b, 8)
    return dict(path=path, raw=b, codec=b[4:8].decode('latin1'), sub=sub, w=w, h=h,
                mips=mips, l0=l0, size=len(b), blob=blob)


def walk(j):
    """Return list of (mip_index, file_offset, size) or None if layout doesn't fit."""
    blk = 8 if j['sub'] == SUB_BC1 else 16
    want = dds_chain(j['w'], j['h'], j['mips'], blk)
    if want[0] != j['l0']:
        return None
    out, off = [(0, 28, want[0])], 28 + want[0]
    for i in range(1, j['mips']):
        sz = struct.unpack_from('<I', j['raw'], off)[0]
        if sz != want[i]:
            return None
        out.append((i, off + 4, sz))
        off += 4 + sz
    return out if off == j['size'] else None


def dds_header(w, h, fourcc, mips, bitcount=0, masks=(0, 0, 0, 0), pf_flags=0x4,
               pitch=0):
    linear = pf_flags & 0x40 and not (pf_flags & 0x1000)
    dwFlags = 0x1 | 0x2 | 0x4 | 0x1000 | (0x8 if linear else 0x200000)
    if mips > 1:
        dwFlags |= 0x20000
    pf = struct.pack('<II4sIIIII', 32, pf_flags, fourcc, bitcount, *masks)
    hdr = b'DDS ' + struct.pack('<7I', 124, dwFlags, h, w, pitch, 0, max(1, mips))
    hdr += b'\0' * 44 + pf
    hdr += struct.pack('<5I', 0x1000 | (0x4000000 | 0x8 if mips > 1 else 0), 0, 0, 0, 0)
    assert len(hdr) == 128, len(hdr)
    return hdr


def to_dds(j, bpp_fourcc=None):
    """-> (bytes, kind) ; bytes is a DDS file (or a raw .webp) ready for the shell."""
    w, h, mips = j['w'], j['h'], j['mips']
    if j['codec'] == 'COLW':
        return j['raw'][28:28 + j['l0']], 'webp'
    if j['codec'] == 'RGBA':
        return (dds_header(w, h, b'BGRA', 1, 32,
                           (0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000),
                           0x40 | 0x2 | 0x1, w * 4) + j['raw'][28:28 + w * h * 4], 'BGRA')
    if j['codec'] == 'ALI8':
        return (dds_header(w, h, b'RGBA', 1, 8, (0xFF, 0, 0, 0), 0x40, w)
                + j['raw'][28:28 + w * h], 'L8')
    fourcc = bpp_fourcc or ('DXT1' if j['sub'] == SUB_BC1 else 'DXT5')
    blk = 8 if fourcc == 'DXT1' else 16
    ms = [m for m in walk(j) or [(i, 28 + s, s) for i, s in
                                 enumerate(dds_chain(w, h, mips, blk))]]
    body = b''.join(j['raw'][o:o + s] for _, o, s in ms)
    return dds_header(w, h, fourcc.encode(), mips) + body, fourcc


if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'walk'
    con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
    tex = list(con.execute("select hash,codec,path from resources where type='texture'"))

    if mode == 'walk':
        res = collections.Counter()
        bad = []
        for h, codec, path in tex:
            p = FIND.get(h)
            if not p:
                continue
            j = parse(p)
            if j['codec'] not in ('DXT1',):
                continue
            w = walk(j)
            res['per-mip-u32-prefix:OK' if w else 'NO'] += 1
            res['sub=0x%x' % j['sub']] += 1
            if not w and len(bad) < 8:
                bad.append((h, j['sub'], j['w'], j['h'], j['mips'], j['l0'], j['size']))
        for k, v in res.most_common():
            print('%-24s %6d' % (k, v))
        for b in bad:
            print('  nofit', b)

    if mode == 'png':
        from PIL import Image
        q = ("select hash,path,codec from resources where type='texture' and path is not null"
             " order by original desc")
        made = collections.Counter()
        for h, path, codec in con.execute(q):
            if made[codec] >= 3 or sum(made.values()) >= 11:
                break
            p = FIND.get(h)
            if not p:
                continue
            j = parse(p)
            for variant in ((j['codec'] == 'DXT1' and j['sub'] == SUB_8BPP)
                            and ['DXT5', 'DXT3'] or [None]):
                d, kind = to_dds(j, variant)
                if kind == 'webp':
                    fn = os.path.join(OUT, '%s.webp' % h)
                    open(fn, 'wb').write(d)
                    im = Image.open(fn)
                else:
                    fn = os.path.join(OUT, '%s_%s.dds' % (h, kind))
                    open(fn, 'wb').write(d)
                    im = Image.open(fn)
                im.load()
                png = os.path.join(OUT, '%s_%s_%s.png' % (h, kind, variant or ''))
                im.convert('RGBA').save(png)
                print('OK %-16s %-34s %sx%s mips=%-2s %-6s -> %s' %
                      (h, os.path.basename(path), j['w'], j['h'], j['mips'], kind,
                       os.path.basename(png)))
                made[codec] += 1
