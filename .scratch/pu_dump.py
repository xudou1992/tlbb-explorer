"""pu_dump.py — 注解式逐字节转储一个 .pu:字符串表 + 参数区。

用法: python pu_dump.py rel/path.pu [more.pu ...]
      (相对 .scratch/out/tree/data/effect)
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')


def hexdump(raw, start, end, base):
    lines = []
    for o in range(start, end, 16):
        chunk = raw[o:min(o + 16, end)]
        hx = ' '.join('%02x' % c for c in chunk)
        asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in chunk)
        lines.append('%06x  %-47s  %s' % (base + o, hx, asc))
    return lines


def dump(fp):
    raw = open(os.path.join(ROOT, fp), 'rb').read()
    print('=' * 100)
    print('FILE %s  size=%d' % (fp, len(raw)))
    cnt = struct.unpack_from('<I', raw, 4)[0]
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pairs = [(tab[i], tab[i + 1]) for i in range(0, 2 * cnt, 2)]
    pool = 8 + 8 * cnt
    print('magic=%r cnt=%d table=8..%d pool=%d' % (raw[:4], cnt, pool, pool))
    p = pool
    for i, (ln, hv) in enumerate(pairs):
        s = raw[p:p + ln]
        print('  str[%2d] len=%-3d hash=%08x  off=%d  %r' % (i, ln, hv, p, s))
        p += ln
    pend = len(raw)
    print('PARAM REGION %d..%d  (%d bytes)' % (p, pend, pend - p))
    for line in hexdump(raw, p, pend, 0):
        print('  ' + line)
    print()
    return raw, p


if __name__ == '__main__':
    for fp in sys.argv[1:]:
        dump(fp)
