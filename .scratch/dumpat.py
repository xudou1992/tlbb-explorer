import struct, sys, zlib

sys.path.insert(0, r'D:\TLGL\.scratch')
from pakunpack import read_index

path = r'D:\TLGL' + '\\' + sys.argv[1]
base = int(sys.argv[2], 16)
n = int(sys.argv[3]) if len(sys.argv) > 3 else 32
pkg = read_index(path)
last = max(r['off'] + r['occ'] for r in pkg['recs'])
print('index cover ends at 0x%x ; header n=%d ver=%d' % (last, pkg['n'], pkg['ver']))
with open(path, 'rb') as f:
    f.seek(base)
    blob = f.read(n * 36 + 64)
print('dump @0x%x' % base)
for i in range(0, min(len(blob), 64 * n), 36):
    r = blob[i:i + 36]
    if len(r) < 36:
        break
    h, off, size, occ, ofsz, ver, fl, me, fcrc, ucrc = struct.unpack('<QIIIIHBBII', r)
    ok = ucrc == (zlib.crc32(bytes(r[:32])) & 0xFFFFFFFF)
    print('  +0x%04x h=%016x off=%-10x size=%-9x occ=%-9x ofsz=%-9x ver=%-5d fl=%02x me=%02x ucrc=%08x %s' % (
        base - base + i, h, off, size, occ, ofsz, ver, fl, me, ucrc, 'CRC-OK' if ok else ''))
print()
print(blob[:128].hex())
print(repr(blob[:64]))
