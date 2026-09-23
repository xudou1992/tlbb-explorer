"""Dump representative payload headers for format documentation."""
import os

root = r'D:\TLGL\.scratch\out\all'


def find(cond, n=3):
    out = []
    for pak in os.listdir(root):
        d = os.path.join(root, pak)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            p = os.path.join(d, fn)
            if os.path.isdir(p):
                continue
            h = open(p, 'rb').read(96)
            if cond(h):
                out.append((p, h, os.path.getsize(p)))
                if len(out) >= n:
                    return out
    return out


Z = b'\x00'
CASES = [
    ('JMT1', lambda h: h[:4] == b'JMT1'),
    ('COPY-ani', lambda h: h[:10] == b'Copyright ' and h[64:67] == b'ani'),
    ('COPY-mesh', lambda h: h[:10] == b'Copyright ' and h[64:68] == b'mesh'),
    ('JBCF', lambda h: h[:4] == b'JBCF'),
    ('JBPU', lambda h: h[:4] == b'JBPU'),
    ('GATA', lambda h: h[:4] == b'GATA'),
    ('NAVF', lambda h: h[:4] == b'NAVF'),
    ('raw-geom', lambda h: h[:8] == Z * 4 + b'\x01' + Z * 3),
]

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'heads.txt'), 'w',
          encoding='utf-8') as o:
    for title, cond in CASES:
        o.write('==== %s ====\n' % title)
        for p, h, s in find(cond):
            o.write('%s size=%d\n' % (os.path.basename(p), s))
            for off in range(0, 80, 16):
                ch = h[off:off + 16]
                o.write('   +%02x %s  |%s|\n' % (
                    off, ' '.join('%02x' % b for b in ch),
                    ''.join(chr(b) if 32 <= b < 127 else '.' for b in ch)))
            o.write('   ints: %s\n' % ' '.join(str(v) for v in
                                                __import__('struct').unpack('<16I', h[:64])))
print('ok')
