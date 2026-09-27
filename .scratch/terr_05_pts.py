import struct, glob, os, collections, statistics, sys

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
                recs.append((f, nm))
            return stride, recs
    return None, []

d = 'out/tree/mobile_maps/w1351_ll_dl_002'
pts = []
w4 = collections.Counter()
strides = collections.Counter()
for f in sorted(glob.glob(d + '/*.scene')):
    st, recs = load_scene(f)
    strides[st] += 1
    for m, nm in recs:
        pts.append((m[12], m[13], m[14], m[15], nm))
print('strides', strides.most_common(), 'pts', len(pts))
print('m[15] values', collections.Counter(round(p[3], 4) for p in pts).most_common(5))
xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
print('x %.2f .. %.2f   span %.1f' % (min(xs), max(xs), max(xs)-min(xs)))
print('y %.2f .. %.2f   span %.1f' % (min(ys), max(ys), max(ys)-min(ys)))
print('z %.2f .. %.2f   span %.1f' % (min(zs), max(zs), max(zs)-min(zs)))
cy = collections.Counter(round(y, 1) for y in ys)
print('y hist top20', cy.most_common(20))
print('y distinct', len(cy))
qx = collections.Counter(round(x/32) for x in xs)
print('x/32 bucket top', sorted(qx.items())[:15])
open('terr_pts.txt', 'w').write('\n'.join('%g %g %g %s' % p for p in pts))
print('names sample', [p[4] for p in pts[:5]])
