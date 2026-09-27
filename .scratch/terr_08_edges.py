import struct, collections, glob, os, sys

def load_map(path):
    d = open(path, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16])
    nb = A*B
    blk = (struct.unpack('<I', d[16:20])[0] - hdr)//nb
    v = d[hdr:hdr+nb*blk]
    per_block = []
    for bi in range(nb):
        o = bi*blk
        per_block.append(bytes(x ^ 0 for x in [0]) )  # placeholder
    # map combos to small ints
    codes = {}
    out = []
    for bi in range(nb):
        o = bi*blk
        arr = bytearray(1024)
        for k in range(1024):
            key = (v[o+k*4+1], v[o+k*4+2])
            c = codes.get(key)
            if c is None:
                c = len(codes) % 251
                codes[key] = c
            arr[k] = c + 1
        out.append(bytes(arr))
    return A, B, hdr, blk, nb, out, codes

def build(A, B, blocks, xfast, rowmajor):
    W, H = A*32, B*32
    rows = []
    for y in range(H):
        gy = y//32; cy = y % 32
        buf = bytearray(W)
        if rowmajor:
            for gx in range(A):
                bi = gy*A+gx if xfast else gx*B+gy
                blk = blocks[bi]
                base = cy*32
                buf[gx*32:gx*32+32] = blk[base:base+32]
        else:
            for gx in range(A):
                bi = gy*A+gx if xfast else gx*B+gy
                blk = blocks[bi]
                for cx in range(32):
                    buf[gx*32+cx] = blk[cx*32+cy]
        rows.append(bytes(buf))
    return rows

def rate(rows, W, H):
    nh = ne = 0
    for r in rows:
        nh += sum(1 for a, b in zip(r, r[1:]) if a != b)
    for i in range(H-1):
        a, b = rows[i], rows[i+1]
        ne += sum(1 for j in range(W) if a[j] != b[j])
    return nh, ne

p = sys.argv[1] if len(sys.argv) > 1 else 'out/tree/mobile_maps/w1351_ll_dl_002/w1351_ll_dl_002.map'
A, B, hdr, blk, nb, blocks, codes = load_map(p)
W, H = A*32, B*32
print(os.path.basename(p), 'A', A, 'B', B, 'hdr', hdr, 'blk', blk, 'cells', W, 'x', H, 'combos', len(codes))
inv = {v: k for k, v in codes.items()}
print('combo table', sorted(codes.items(), key=lambda kv: kv[1]))
for xfast in (True, False):
    for rowmajor in (True, False):
        rows = build(A, B, blocks, xfast, rowmajor)
        nh, ne = rate(rows, W, H)
        tot = (W-1)*H + W*(H-1)
        print('  xfast=%d rowmajor=%d -> diff-rate=%.5f' % (xfast, rowmajor, (nh+ne)/tot))
