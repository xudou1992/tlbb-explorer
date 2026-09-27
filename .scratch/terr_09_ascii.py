import struct, sys, collections
p = sys.argv[1] if len(sys.argv) > 1 else 'out/tree/mobile_maps/w1351_ll_dl_002/w1351_ll_dl_002.map'
d = open(p, 'rb').read()
magic, A, B, hdr = struct.unpack('<4I', d[:16])
nb = A*B
blk = (struct.unpack('<I', d[16:20])[0]-hdr)//nb
v = d[hdr:hdr+nb*blk]
# build full grid, xfast+rowmajor, cell(x=col index over A axis, y over B axis)
W, H = A*32, B*32
grid = bytearray(W*H)
for gy in range(B):
    for gx in range(A):
        bi = gy*A+gx
        o = bi*blk
        for k in range(1024):
            r, c = k//32, k % 32
            b1, b2 = v[o+k*4+1], v[o+k*4+2]
            grid[(gy*32+r)*W + gx*32+c] = (b1 << 4) | (b2 & 0xf)
cnt = collections.Counter(grid)
sym = {}
order = [k for k, _ in cnt.most_common()]
chars = '#.abcdefghi'
for i, k in enumerate(order):
    sym[k] = chars[i] if i < len(chars) else '?'
print('legend (idx: b1,b2 count pct):')
for i, k in enumerate(order):
    print('  %s = (%d,%d) %8d %6.3f%%' % (sym[k], k >> 4, k & 15, cnt[k], 100.0*cnt[k]/(W*H)))
step = 8
lines = []
for y in range(0, H, step):
    lines.append(''.join(sym[grid[y*W+x]] for x in range(0, W, step)))
print('\n'.join(lines))
