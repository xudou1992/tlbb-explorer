import struct, collections, glob, os, sys, random

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
gc = collections.Counter(g); tot = len(g)
VOID = 0; GROUND = 168

def sample(swap, fu, fw, ox, oz):
    c = collections.Counter(); n = 0
    for (x, y, z, nm) in pts:
        X = (-z) if swap else x
        Z = x if swap else (-z)
        if fu: X = W/2.0 - X
        if fw: Z = H/2.0 - Z
        u = int((X + ox)*2); w = int((Z + oz)*2)
        if not (0 <= u < W and 0 <= w < H): continue
        n += 1; c[g[w*W+u]] += 1
    return c, n

def chi2(c, n):
    return sum((v-gc[k]*n/tot)**2/(gc[k]*n/tot) for k, v in c.items() if gc[k]*n/tot > 5)

print('=== zero-shift grid alignments (registration pinned by scene chunk geometry) ===')
res = []
for swap in (0, 1):
    for fu in (0, 1):
        for fw in (0, 1):
            c, n = sample(swap, fu, fw, 0, 0)
            res.append((chi2(c, n), swap, fu, fw, n, c.get(VOID, 0)*100.0/n, c.get(GROUND, 0)*100.0/n))
for r in sorted(res, reverse=True):
    print('  swap=%d flipU=%d flipW=%d n=%d chi2=%.1f void%%=%.2f ground%%=%.2f  (global void %.2f%%)' %
          (r[1], r[2], r[3], r[4], r[0], r[5], r[6], gc[VOID]*100.0/tot))

print('=== random-shift null for the same axis choice (swap=0,fu=0,fw=0) ===')
vals = []
for i in range(200):
    c, n = sample(0, 0, 0, random.uniform(-16, 16), random.uniform(-16, 16))
    vals.append((chi2(c, n), c.get(VOID, 0)*100.0/n))
vals.sort()
print('  chi2 min %.1f p25 %.1f med %.1f p75 %.1f max %.1f' % (vals[0][0], vals[50][0], vals[100][0], vals[150][0], vals[-1][0]))
vs = sorted(v for _, v in vals)
print('  void%% under objects for random shifts: min %.2f med %.2f max %.2f' % (vs[0], vs[100], vs[-1]))
zc = sample(0, 0, 0, 0, 0)
print('  zero-shift: chi2 %.1f void%% %.2f' % (chi2(zc[0], zc[1]), zc[0].get(VOID, 0)*100.0/zc[1]))
print('  value dist under objects (zero shift):', {k: round(100.0*v/zc[1], 2) for k, v in zc[0].most_common(6)})
