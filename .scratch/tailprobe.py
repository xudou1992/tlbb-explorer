import math, mmap, os, struct, sys, zlib

sys.path.insert(0, r'D:\TLGL\.scratch')
import numpy as np


def ent(b):
    h = np.bincount(np.frombuffer(b, dtype=np.uint8), minlength=256)
    p = h[h > 0] / len(b)
    return float(-(p * np.log2(p)).sum())


def looks_like_record(view, i):
    """Cheap structural filter for a 36-byte JPAK Index record at byte i."""
    r = view[i:i + 36]
    if len(r) < 36:
        return False
    h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = struct.unpack('<QIIIIHBBII', r)
    return (ver < 65536 and me in (0, 51) and fl < 64 and 0 < size <= ofsz * 4 + 100 and
            ucrc == (zlib.crc32(bytes(r[:32])) & 0xFFFFFFFF))


for p in ['data.pak', 'data4.pak']:
    path = r'D:\TLGL' + '\\' + p
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        print('===', p)
        for probe in [0x8cc0, 0x4000000, 0x40000000, 0x12a499b0, 0x20000000, 0x30000000,
                      0x60000000, 0x80000000, 0x3f000000]:
            if probe + (1 << 20) > size:
                continue
            chunk = m[probe:probe + (1 << 20)]
            print('  0x%08x entropy=%.3f printable=%.3f head=%s' % (
                probe, ent(chunk), sum(32 <= c < 127 for c in chunk) / len(chunk), chunk[:24].hex()))
        # record-crc scan over a 8MB window in the unreferenced tail
        base = 0x20000000
        view = m[base:base + (8 << 20)]
        hits = [i for i in range(0, len(view) - 36, 4) if looks_like_record(view, i)]
        print('  record-like hits in 8MB @0x%x: %d %s' % (base, len(hits), ['0x%x' % (base + h) for h in hits[:5]]))
        m.close()
