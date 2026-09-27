import struct, collections, itertools, sys
p = 'out/tree/mobile_maps/w1351_ll_dl_002/w1351_ll_dl_002.map'
d = open(p, 'rb').read()
A, B = struct.unpack('<II', d[4:12])
HDR, BLK, N = 152, 4160, 1024
nb = A*B
cells = [None]*nb
for bi in range(nb):
    o = HDR + bi*BLK
    blk = d[o:o+BLK]
    arr = collections.deque()
    vals = struct.unpack('<%dB' % BLK, blk)
    grid = [[(vals[r*128+1+4*c], vals[r*128+2+4*c]) for c in range(32)] for r in range(32)]
    cells[bi] = grid
print('per-block distinct combos:')
cc = collections.Counter()
for bi in range(nb):
    s = set()
    for r in range(32):
        for c in range(32):
            s.add(cells[bi][r][c])
    cc[len(s)] += 1
print(sorted(cc.items()))
allc = collections.Counter()
for bi in range(nb):
    for r in range(32):
        for c in range(32):
            allc[cells[bi][r][c]] += 1
tot = sum(allc.values())
print('total cells', tot, 'distinct combos', len(allc))
for k, v in allc.most_common(20):
    print('   ', k, v, '%.3f%%' % (100.0*v/tot))

def neighbours_metric(bx_first):
    # bx_first True: bi = gy*A + gx ; else bi = gx*B + gy
    bad = 0; tot2 = 0
    def cell_at(gx, gy, r, c):
        if 0 <= gx < A and 0 <= gy < B:
            bi = gy*A+gx if bx_first else gx*B+gy
            return cells[bi][r][c]
        return None
    # horizontal in world x direction: either within block (c,c+1) or across block boundary
    for gx in range(A):
        for gy in range(B):
            bi = gy*A+gx if bx_first else gx*B+gy
            g = cells[bi]
            for r in range(32):
                for c in range(31):
                    tot2 += 1
                    if g[r][c] != g[r][c+1]: bad += 1
    # vertical between blocks rows
    for gx in range(A):
        for gy in range(B-1):
            b1 = gy*A+gx if bx_first else gx*B+gy
            b2 = (gy+1)*A+gx if bx_first else (gx+1)*B+gy
            for c in range(32):
                tot2 += 1
                if cells[b1][31][c] != cells[b2][0][c]: bad += 1
    return bad/tot2
for f in (True, False):
    print('block-order x-fastest=%s : across-block row mismatch rate %.4f' % (f, neighbours_metric(f)))
# also within-block: rows adjacent equality for r vs c axis
h_same = v_same = 0
for bi in range(nb):
    g = cells[bi]
    for r in range(32):
        for c in range(31):
            h_same += (g[r][c] == g[r][c+1])
    for r in range(31):
        for c in range(32):
            v_same += (g[r][c] == g[r+1][c])
print('within-block horiz-equal %.4f vert-equal %.4f (n=%d each)' % (h_same/(nb*32*31), v_same/(nb*31*32), nb*32*31))
