import struct, collections, sys
p = 'out/tree/mobile_maps/w1351_ll_dl_002/w1351_ll_dl_002.map'
d = open(p, 'rb').read()
A, B = struct.unpack('<II', d[4:12])
HDR, BLK = 152, 4160
nb = A*B
# where are non-zero bytes inside blocks that are partially filled?
pat = collections.Counter()
zeros_at_end = 0
zeros_at_start = 0
for bi in range(nb):
    o = HDR + bi*BLK
    blk = d[o:o+BLK]
    if blk.count(0) == 0:
        continue
    tail = blk[4096:]
    if set(tail) <= {0}:
        zeros_at_end += 1
    head = blk[:4096]
    if set(head) <= {0}:
        zeros_at_start += 1
print('blocks', nb, 'tail4096:4160 all-zero in', zeros_at_end, 'blocks ; head4096 all-zero in', zeros_at_start)

# distribution of nonzero byte offsets within block, restricted to partial blocks
offc = collections.Counter()
for bi in range(nb):
    o = HDR + bi*BLK
    blk = d[o:o+BLK]
    for i, b in enumerate(blk):
        if b:
            offc[i] += 1
print('nonzero byte offsets: min', min(offc), 'max', max(offc), 'distinct', len(offc))
# print mask of which byte positions (mod 4) ever nonzero
mod4 = collections.Counter()
for i, n in offc.items():
    mod4[i % 4] += n
print('byte position mod4 counts', dict(mod4))
print('max nonzero offset', max(offc))
# show per-unit (u32) index nonzero frequency, look for gaps
unit = collections.Counter()
for bi in range(nb):
    o = HDR + bi*BLK
    blk = d[o:o+BLK]
    for u in range(BLK//4):
        if blk[u*4:u*4+4] != b'\x00\x00\x00\x00':
            unit[u] += 1
print('units touched', len(unit), 'min idx', min(unit), 'max idx', max(unit))
missing = [u for u in range(BLK//4) if u not in unit]
print('units never nonzero:', len(missing), missing[:40], '...', missing[-10:] if missing else '')
# occupancy profile of first 40 units
print('occupancy u0..u39', [unit.get(u, 0) for u in range(40)])
print('occupancy u1000..u1039', [unit.get(u, 0) for u in range(1000, 1040)])
