import struct, collections, glob, random, sys

def load_map(path):
    d = open(path, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16]); nb = A*B
    blk = (struct.unpack('<I', d[16:20])[0]-hdr)//nb
    v = d[hdr:hdr+nb*blk]
    W, H = A*32, B*32
    g = [0]*(W*H)
    for gy in range(B):
        for gx in range(A):
            o = (gy*A+gx)*blk
            for k in range(1024):
                r, c = divmod(k, 32)
                g[(gy*32+r)*W + gx*32+c] = (v[o+k*4+1] << 5) | v[o+k*4+2]
    return A, B, W, H, g

def load_scene(path):
    d = open(path, 'rb').read()
    n = struct.unpack('<I', d[:4])[0]
    for stride in (761, 757):
        if 4 + n*stride == len(d):
            out = []
            for i in range(n):
                o = 4 + i*stride
                f = struct.unpack('<16f', d[o+8:o+72])
                nm = d[o+76:o+stride].split(b'\x00')[0].decode('latin1')
                out.append((f[12], f[13], f[14], nm))
            return out
    return []

name = sys.argv[1] if len(sys.argv) > 1 else 'w1351_ll_dl_002'
base = 'out/tree/mobile_maps/' + name
A, B, W, H, g = load_map(base + '/' + name + '.map')
pts = []
for f in glob.glob(base + '/*.scene'):
    pts += load_scene(f)
pts = [(x, y, z, nm) for x, y, z, nm in pts if nm.endswith('.mesh')]
print('map', name, 'A', A, 'B', B, 'grid %dx%d' % (W, H), 'objects', len(pts))
gc = collections.Counter(g); tot = len(g)
print('global shares %', {k: round(100.0*v/tot, 2) for k, v in gc.most_common()})

def run(swap, ox, oz):
    c = collections.Counter(); n = 0
    for (x, y, z, nm) in pts:
        if swap:
            X, Z = z + 336.0, x
        else:
            X, Z = x, z + 336.0
        u = int((X + ox)*2); w = int((Z + oz)*2)
        if not (0 <= u < W and 0 <= w < H):
            continue
        n += 1
        c[g[w*W+u]] += 1
    return c, n

def chi2(c, n):
    return sum((v-gc[k]*n/tot)**2/(gc[k]*n/tot) for k, v in c.items() if gc[k])

best = None
for swap in (0, 1):
    for ox16 in range(32):
        for oz16 in range(32):
            c, n = run(swap, ox16*0.5, oz16*0.5)
            v = chi2(c, n)
            if best is None or v > best[0]:
                best = (v, swap, ox16*0.5, oz16*0.5, n, c)
v, swap, ox, oz, n, c = best
print('BEST chi2=%.1f swap=%d ox=%.1f oz=%.1f n=%d' % (v, swap, ox, oz, n))
print('  dist at best %', {k: round(100.0*x/n, 2) for k, x in c.most_common()})
rnd = []
for i in range(150):
    c2, n2 = run(swap, random.random()*16, random.random()*16)
    rnd.append(chi2(c2, n2))
rnd.sort()
print('  random-shift chi2: min %.1f med %.1f max %.1f  (df~10)' % (rnd[0], rnd[75], rnd[-1]))
