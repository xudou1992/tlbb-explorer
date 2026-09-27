import struct, collections, glob, os, sys, random

def load_map(path):
    d = open(path, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16]); nb = A*B
    end = struct.unpack('<I', d[16:20])[0]; blk = (end-hdr)//nb
    v = d[hdr:end]
    W, H = A*32, B*32
    g = [0]*(W*H)
    for gy in range(B):
        for gx in range(A):
            o = (gy*A+gx)*blk
            for k in range(1024):
                r, c = divmod(k, 32)
                g[(gy*32+r)*W + gx*32+c] = (v[o+k*4+1] << 8) | v[o+k*4+2]
    return A, B, W, H, g, v, blk, nb

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

name = 'w1351_ll_dl_002'
base = 'out/tree/mobile_maps/' + name
A, B, W, H, g, v, blk, nb = load_map(base + '/' + name + '.map')
pts = []
for f in glob.glob(base + '/*.scene'):
    pts += load_scene(f)
pts = [(x, y, z, nm) for x, y, z, nm in pts if nm.endswith('.mesh')]
gc = collections.Counter(g); tot = W*H
VOID = 0

def stat(ox, oz):
    c = collections.Counter(); n = 0
    for (x, y, z, nm) in pts:
        u = int((x+ox)*2); w = int((-z+oz)*2)
        if 0 <= u < W and 0 <= w < H:
            n += 1; c[g[w*W+u]] += 1
    return c, n

def chi2(c, n):
    return sum((val-gc[k]*n/tot)**2/(gc[k]*n/tot) for k, val in c.items() if gc[k]*n/tot > 5)

print('--- shift scan: 32x32 half-unit shifts within one block period (swap=0, no flips) ---')
res = []
for i in range(33):
    for j in range(33):
        c, n = stat(i*0.5, j*0.5)
        res.append((chi2(c, n), i*0.5, j*0.5, n, 100.0*c.get(VOID, 0)/n))
res.sort(reverse=True)
for r in res[:6]:
    print('   chi2=%8.1f shift=(%.1f,%.1f) n=%d void%%=%.2f' % r)
c0, n0 = stat(0, 0)
s0 = chi2(c0, n0)
rank = sum(1 for r in res if r[0] > s0) + 1
print('   PINNED shift (0,0): chi2=%.1f rank %d of %d ; void%%=%.2f (global %.2f%%) ; n=%d' %
      (s0, rank, len(res), 100.0*c0.get(VOID, 0)/n0, 100.0*gc[VOID]/tot, n0))
vs = sorted(r[4] for r in res)
print('   void%% across the 33x33 shift grid: min %.2f (at pinned=%s) med %.2f max %.2f' % (vs[0], abs(vs[0]-100.0*c0.get(VOID,0)/n0) < 1e-9, vs[len(vs)//2], vs[-1]))
print('   chi2 of the 8 flip/swap variants at zero shift computed in terr_15: pinned is max')

print('--- per-block slope test (is b1 a monotone gradient inside a block?) ---')
b1s = []
for bi in range(nb):
    o = bi*blk
    row = [v[o+k*4+1] for k in range(1024)]
    b1s.append(row)
def corr(a, b):
    n = len(a); ma = sum(a)/n; mb = sum(b)/n
    cov = sum((p-ma)*(q-mb) for p, q in zip(a, b))
    va = sum((p-ma)**2 for p in a)**.5; vb = sum((q-mb)**2 for q in b)**.5
    return cov/(va*vb) if va*vb else 0.0
cr = []; cc = []; rng = collections.Counter(); mono = 0
for bi, row in enumerate(b1s):
    r = [k//32 for k in range(1024)]; c = [k % 32 for k in range(1024)]
    cr.append(abs(corr(row, r))); cc.append(abs(corr(row, c)))
    mn, mx = min(row), max(row)
    rng[(mx-mn)] += 1
    if mx > mn and max(abs(corr(row, r)), abs(corr(row, c))) > 0.9: mono += 1
print('   mean |corr(b1, blockrow)|=%.3f  mean |corr(b1, blockcol)|=%.3f' % (sum(cr)/nb, sum(cc)/nb))
print('   blocks with |corr|>0.9 (ramp-like): %d / %d = %.2f%%' % (mono, nb, 100.0*mono/nb))
print('   per-block b1 range histogram:', sorted(rng.items())[:10])

print('--- numeric reinterpretation table (height candidates) ---')
views = {
 'b1 (byte1)': [v[i+1] for i in range(0, nb*blk, 4)],
 'b2 (byte2)': [v[i+2] for i in range(0, nb*blk, 4)],
 'u16@+0':    struct.unpack('<%dH' % (nb*blk//2), v)[0::2],
 'u16@+2':    struct.unpack('<%dH' % (nb*blk//2), v)[1::2],
 'byte0':     [v[i] for i in range(0, nb*blk, 4)],
 'byte3':     [v[i+3] for i in range(0, nb*blk, 4)],
}
for k, arr in views.items():
    cn = collections.Counter(arr); n = len(arr)
    vals = sorted(cn)
    # contiguity: number of missing integers inside the range
    gaps = sum(1 for x in range(vals[0], vals[-1]+1) if x not in cn)
    adj_equal = 0
    print('   %-10s n=%d distinct=%d min=%s max=%s internal-gaps=%d top3=%s' %
          (k, n, len(vals), vals[0], vals[-1], gaps, cn.most_common(3)))
