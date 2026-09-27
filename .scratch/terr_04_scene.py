import struct, os, glob, math, collections, sys

def parse_scene(path):
    d = open(path, 'rb').read()
    n, stride, z = struct.unpack('<3I', d[:12])
    recs = []
    if 12 + n*stride <= len(d) and stride in (761, 757):
        for i in range(n):
            o = 12 + i*stride
            m = struct.unpack('<16f', d[o:o+64])
            name = d[o+64:o+stride].split(b'\x00')[0].decode('gbk', 'replace')
            recs.append((m, name))
        return n, stride, recs, len(d)
    return n, stride, None, len(d)

d = 'out/tree/mobile_maps/w1351_ll_dl_002'
xs, ys, zs = [], [], []
tot = 0
byfile = {}
for f in sorted(glob.glob(d + '/*.scene')):
    n, stride, recs, size = parse_scene(f)
    if recs is None:
        print('HDR?', os.path.basename(f), n, stride, size)
        continue
    tot += len(recs)
    pts = [(m[3], m[7], m[11]) for m, nm in recs]
    byfile[os.path.basename(f)] = pts
    xs += [p[0] for p in pts]; ys += [p[1] for p in pts]; zs += [p[2] for p in pts]
print('total recs', tot)
import statistics
for nm, arr in (('x', xs), ('y', ys), ('z', zs)):
    print(nm, 'min %.2f max %.2f mean %.2f' % (min(arr), max(arr), statistics.mean(arr)))
# per-file bbox for a few
ks = sorted(byfile)[:8]
for k in ks:
    pts = byfile[k]
    print(k, len(pts), 'x %.1f..%.1f y %.1f..%.1f z %.1f..%.1f' % (
        min(p[0] for p in pts), max(p[0] for p in pts),
        min(p[1] for p in pts), max(p[1] for p in pts),
        min(p[2] for p in pts), max(p[2] for p in pts)))
# main scene file
n, stride, recs, size = parse_scene(d + '/w1351_ll_dl_002.scene')
print('main scene recs', n if recs is None else len(recs), 'stride', stride, 'size', size)
if recs:
    pts = [(m[3], m[7], m[11]) for m, nm in recs]
    print('main x %.1f..%.1f y %.1f..%.1f z %.1f..%.1f' % (min(p[0] for p in pts), max(p[0] for p in pts),
        min(p[1] for p in pts), max(p[1] for p in pts), min(p[2] for p in pts), max(p[2] for p in pts)))
    print('sample names', [nm for m, nm in recs[:6]])
    print('sample mat4 row4', recs[0][0][3], recs[0][0][7], recs[0][0][11])
