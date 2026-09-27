import struct, collections, glob, os, sys, random

def load_map(path):
    d = open(path, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16]); nb = A*B
    end = struct.unpack('<I', d[16:20])[0]
    nrec = struct.unpack('<I', d[20:24])[0]
    fsz = struct.unpack('<I', d[24:28])[0]
    blk = (end-hdr)//nb
    return dict(A=A, B=B, hdr=hdr, nb=nb, end=end, nrec=nrec, fsz=fsz, blk=blk, d=d,
                tail=d[end:], body=d[hdr:end])

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
                out.append((f[12], f[13], f[14], nm, f[0], f[5]))
            return out
    return []

for name in (sys.argv[1:] or ['w1351_ll_dl_002']):
    base = 'out/tree/mobile_maps/' + name
    m = load_map(base + '/' + name + '.map')
    A, B, hdr, nb, blk = m['A'], m['B'], m['hdr'], m['nb'], m['blk']
    v = m['body']
    print('===', name, 'A', A, 'B', B, 'blk', blk, 'nrec', m['nrec'], 'tail bytes', len(m['tail']),
          'per-record', len(m['tail'])/m['nrec'] if m['nrec'] else 0, 'fsz ok', m['fsz'] == os.path.getsize(base+'/'+name+'.map'))
    # ---- 1. byte-plane census over all cells (whole map) ----
    planes = [collections.Counter() for _ in range(4)]
    for k in range(4):
        for i in range(k, len(v), 4):
            planes[k][v[i]] += 1
    for k in range(4):
        print('   byte plane %d: distinct=%d top=%s' % (k, len(planes[k]), planes[k].most_common(6)))
    # ---- 2. joint combos ----
    combos = collections.Counter((v[i+1], v[i+2]) for i in range(0, len(v), 4))
    print('   joint combos %d: %s' % (len(combos), combos.most_common(14)))
    b1s = sorted(set(k[0] for k in combos)); b2s = sorted(set(k[1] for k in combos))
    print('   b1 set', b1s, ' b2 set', b2s)
    # ---- 3. 16-bit views: are bytes0/3 ever nonzero? ----
    print('   plane0 nonzero count', sum(c for k, c in planes[0].items() if k), ' plane3 nonzero', sum(c for k, c in planes[3].items() if k))
    # ---- 4. block sub-structure: 64B tail per block ----
    tb = collections.Counter()
    nz = 0
    for bi in range(nb):
        o = bi*blk
        t = v[o+4096:o+blk]
        tb[len(t)] += 1
        if any(t): nz += 1
    print('   per-block tail len set %s ; blocks with nonzero tail %d/%d' % (sorted(tb), nz, nb))
    for bi in range(nb):
        o = bi*blk
        t = v[o+4096:o+blk]
        if any(t):
            print('     block', bi, 'tail hex', t[:32].hex(' '))
    # ---- 5. 96B trailer records ----
    t = m['tail']
    for i in range(0, min(len(t), 96*4), 96):
        rec = t[i:i+96]
        print('   trailer rec %2d: %s' % (i//96, rec[:48].hex(' ')))
        print('        ascii:', ''.join(chr(c) if 32 <= c < 127 else '.' for c in rec))
    print('   trailer u32 stats first 8 recs:', [struct.unpack('<8I', t[j*96:j*96+32]) for j in range(3)])
    # printable ratio in trailer
    pr = sum(1 for c in t if 32 <= c < 127)/max(1, len(t))
    print('   trailer printable ratio %.3f ; body printable ratio %.5f' % (pr, sum(1 for c in v if 32 <= c < 127)/len(v)))
