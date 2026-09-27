import struct, collections, sys
p = sys.argv[1] if len(sys.argv) > 1 else 'out/tree/mobile_maps/w1351_ll_dl_002/w1351_ll_dl_002.map'
d = open(p, 'rb').read()
A, B = struct.unpack('<II', d[4:12])
HDR = 152
BLK = 4160
print('A', A, 'B', B, 'blocks', A * B, 'size', len(d))

for bi in [0, 1, 2, A*B//2]:
    o = HDR + bi*BLK
    blk = d[o:o+BLK]
    print('=== block', bi, 'off', o)
    print('  first 128 hex:', blk[:128].hex(' '))
    # byte histogram
    c = collections.Counter(blk)
    print('  distinct bytes', len(c), 'top', c.most_common(8))
    # u16 view
    u16 = struct.unpack('<%dH' % (BLK//2), blk)
    c16 = collections.Counter(u16)
    print('  distinct u16', len(c16), 'top', c16.most_common(6))
    print('  u16 min/max', min(u16), max(u16))
    u32 = struct.unpack('<%dI' % (BLK//4), blk)
    c32 = collections.Counter(x & 0xffff for x in u32)
    print('  u32 count', len(u32), 'low16 distinct', len(c32))
