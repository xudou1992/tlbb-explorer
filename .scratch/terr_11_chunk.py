import struct, collections, glob, os, sys, random

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

base = 'out/tree/mobile_maps/w1351_ll_dl_002'
print('--- per-scene-file coordinate ranges (chunk-name test) ---')
for f in sorted(glob.glob(base + '/*.scene')):
    b = os.path.basename(f).replace('.scene', '')
    recs = load_scene(f)
    if not recs: continue
    xs = [r[0] for r in recs]; zs = [r[2] for r in recs]
    print('%-16s n=%-5d x %8.2f..%8.2f  z %8.2f..%8.2f' % (b, len(recs), min(xs), max(xs), min(zs), max(zs)))
