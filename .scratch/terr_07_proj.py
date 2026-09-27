import struct, collections, itertools, sys, random

def load_map(path):
    d = open(path, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16])
    nb = A*B
    blk = (struct.unpack('<I', d[16:20])[0] - hdr)//nb
    n = nb*(blk//4)
    vals = struct.unpack('<%dB' % len(d), d)
    grids = []
    for bi in range(nb):
        o = hdr + bi*blk
        g = [[(vals[o + (r*32+c)*4 + 1], vals[o + (r*32+c)*4 + 2]) for c in range(32)] for r in range(32)]
        grids.append(g)
    return A, B, hdr, blk, nb, grids, d

def load_scene(path):
    d = open(path, 'rb').read()
    n = struct.unpack('<I', d[:4])[0]
    for stride in (761, 757):
        if 4 + n*stride == len(d):
            recs = []
            for i in range(n):
                o = 4 + i*stride
                f = struct.unpack('<16f', d[o+8:o+72])
                nm = d[o+76:o+stride].split(b'\x00')[0].decode('latin1')
                recs.append((f[12], f[13], f[14], nm))
            return recs
    return []

MP = 'out/tree/mobile_maps/w1351_ll_dl_002/w1351_ll_dl_002.map'
A, B, hdr, blk, nb, grids, raw = load_map(MP)
import glob, os
pts = []
for f in glob.glob('out/tree/mobile_maps/w1351_ll_dl_002/*.scene'):
    pts += load_scene(f)
pts = [p for p in pts if p[3].endswith('.mesh')]
print('A,B', A, B, 'hdr', hdr, 'blk', blk, 'objects', len(pts))
xs = [p[0] for p in pts]; zs = [p[2] for p in pts]
print('x %.2f..%.2f  z %.2f..%.2f' % (min(xs), max(xs), min(zs), max(zs)))

# hypotheses: origin at x=0,z=-B*16 or z=0 ; block order x-fast or z-fast ; cell row-major or transposed
def probe(xfast, zsign, rowmajor, flipx=False):
    hit = collections.Counter(); outside = 0
    for (x, y, z, nm) in pts:
        if not (0 <= x < A*16 and (-B*16 if zsign < 0 else 0) <= z < (0 if zsign < 0 else B*16)):
            outside += 1; continue
        fx = (A*16 - 1 - x) if flipx else x
        gx = int(fx//16); gz = int(((z + B*16) if zsign < 0 else z)//16)
        gx = min(max(gx, 0), A-1); gz = min(max(gz, 0), B-1)
        bi = gz*A + gx if xfast else gx*B + gz
        cx = int((fx % 16)//0.5)
        cz = int(((z % 16) + 16) % 16 // 0.5)
        if rowmajor:
            v = grids[bi][cz][cx]
        else:
            v = grids[bi][cx][cz]
        hit[v] += 1
    return hit, outside

for xfast in (True, False):
    for zsign in (1, -1):
        for rowmajor in (True, False):
            for flipx in (False, True):
                h, o = probe(xfast, zsign, rowmajor, flipx)
                t = sum(h.values())
                if t == 0: continue
                void = h.get((0, 0), 0)/t
                print('xfast=%d zneg=%d rowmajor=%d flipx=%d -> n=%d outside=%d void(0,0)=%.3f  (5,8)=%.3f  top=%s'
                      % (xfast, zsign < 0, rowmajor, flipx, t, o, void, h.get((5,8),0)/t, h.most_common(3)))
