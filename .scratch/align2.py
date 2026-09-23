import struct, sys, zlib
import numpy as np

path = r'D:\TLGL' + '\\' + sys.argv[1]
base = int(sys.argv[2], 16)
with open(path, 'rb') as f:
    f.seek(base)
    blob = f.read(1 << 16)


def crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


for a in range(0, 44):
    r = blob[a:a + 36]
    if len(r) < 36:
        continue
    h, off, size, occ, ofsz, ver, fl, me, w28, w32 = struct.unpack('<QIIIIHBBII', r)
    if me in (0, 51) and fl < 64 and ver < 4096:
        print('align %2d: h=%016x off=%-10x size=%-8x occ=%-8x ofsz=%-8x ver=%d fl=%02x me=%02d '
              'w28=%08x w32=%08x crc32=%08x' % (a, h, off, size, occ, ofsz, ver, fl, me, w28, w32,
                                                crc(r[:32])))
# find the stride of the repeated 01 00 0c 33 marker
pat = blob.find(b'\x01\x00\x0c\x33')
hits = []
pos = 0
while True:
    i = blob.find(b'\x01\x00\x0c\x33', pos)
    if i < 0 or len(hits) > 12:
        break
    hits.append(i)
    pos = i + 1
print('marker offsets', hits, 'diffs', [hits[i + 1] - hits[i] for i in range(len(hits) - 1)])
