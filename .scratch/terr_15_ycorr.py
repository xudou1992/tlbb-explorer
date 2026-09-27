import struct, collections, glob, os, sys, random

def load_map(path):
    d = open(path, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16]); nb = A*B
    end = struct.unpack('<I', d[16:20])[0]
    blk = (end-hdr)//nb
    W, H = A*32, B*32
    g = [0]*(W*H)
    v = d[hdr:end]
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
                out.append((f[12], f[13], f[14], nm, min(abs(f[0]), abs(f[5]), abs(f[10]))))
            return out
    return []

for name in (sys.argv[1:] or ['w1351_ll_dl_002']):
    base = 'out/tree/mobile_maps/' + name
    A, B, W, H, g = load_map(base + '/' + name + '.map')
    pts = []
    for f in glob.glob(base + '/*.scene'):
        pts += load_scene(f)
    pts = [p for p in pts if p[3].endswith('.mesh')]
    tot = W*H
    gc = collections.Counter(g)
    print('===', name, 'objects', len(pts))
    print('  global: ground(5,8)=%.1f%% void(0,0)=%.1f%%' % (100.0*gc[168]/tot, 100.0*gc[0]/tot))
    byb2 = collections.defaultdict(list)
    byb1 = collections.defaultdict(list)
    for (x, y, z, nm, s) in pts:
        u = int(x*2); w = int((-z)*2)
        if not (0 <= u < W and 0 <= w < H): continue
        c = g[w*W+u]
        byb2[c & 31].append(y); byb1[c >> 5].append(y)
    print('  object y by b2 value:')
    for k in sorted(byb2):
        v = byb2[k]
        print('    b2=%-3d n=%-5d y mean %6.2f med %6.2f  frac(y==0) %.2f frac(y>=8) %.2f' %
              (k, len(v), sum(v)/len(v), sorted(v)[len(v)//2],
               sum(1 for t in v if abs(t) < .01)/len(v), sum(1 for t in v if t >= 8)/len(v)))
    print('  object y by b1 value:')
    for k in sorted(byb1):
        v = byb1[k]
        print('    b1=%-3d n=%-5d y mean %6.2f med %6.2f frac(y==0) %.2f' % (k, len(v), sum(v)/len(v), sorted(v)[len(v)//2], sum(1 for t in v if abs(t) < .01)/len(v)))
    # correlation coefficients
    xs = []; ys = []
    for (x, y, z, nm, s) in pts:
        u = int(x*2); w = int((-z)*2)
        if not (0 <= u < W and 0 <= w < H): continue
        c = g[w*W+u]; xs.append(c >> 5); ys.append(y)
    def corr(a, b):
        n = len(a); ma = sum(a)/n; mb = sum(b)/n
        cov = sum((p-ma)*(q-mb) for p, q in zip(a, b))
        va = sum((p-ma)**2 for p in a)**.5; vb = sum((q-mb)**2 for q in b)**.5
        return cov/(va*vb) if va*vb else 0
    print('  pearson r(b1, y) = %.4f  n=%d' % (corr(xs, ys), len(xs)))
    xs2 = []
    for (x, y, z, nm, s) in pts:
        u = int(x*2); w = int((-z)*2)
        if 0 <= u < W and 0 <= w < H: xs2.append(g[w*W+u] & 31)
    print('  pearson r(b2, y) = %.4f' % corr(xs2, ys))
    # object class enrichment vs same-block background
    print('  per-(b1,b2) share under objects vs global (top):')
    oc = collections.Counter()
    n = 0
    for (x, y, z, nm, s) in pts:
        u = int(x*2); w = int((-z)*2)
        if 0 <= u < W and 0 <= w < H: oc[g[w*W+u]] += 1; n += 1
    for k, c in oc.most_common(10):
        print('    (%2d,%2d) obj %6.2f%%  global %6.2f%%  ratio %.2f' % (k >> 5, k & 31, 100.0*c/n, 100.0*gc[k]/tot, (c/n)/(gc[k]/tot)))
