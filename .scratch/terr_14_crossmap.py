import struct, collections, glob, os, sys, re

# ---- cross-map value-set census ----
MAPS = sys.argv[1:] or []
if not MAPS:
    cand = sorted(glob.glob('out/tree/mobile_maps/*/*.map'))
    pick = {}
    for p in cand:
        n = os.path.basename(os.path.dirname(p))
        kind = n.split('_')[2] if len(n.split('_')) > 2 else '?'
        pick.setdefault(kind, []).append(p)
    for k, v in sorted(pick.items()):
        MAPS += v[:3]
print('maps sampled:', len(MAPS))
rows = []
for p in MAPS:
    d = open(p, 'rb').read()
    magic, A, B, hdr = struct.unpack('<4I', d[:16]); nb = A*B
    end = struct.unpack('<I', d[16:20])[0]
    blk = (end-hdr)//nb
    body = d[hdr:end]
    per_block_tail = body[4096:blk]
    cells = [i for bi in range(nb) for i in range(bi*blk, bi*blk+4096, 4)]
    b1 = collections.Counter(body[i+1] for i in cells)
    b2 = collections.Counter(body[i+2] for i in cells)
    comb = collections.Counter((body[i+1], body[i+2]) for i in cells)
    top = comb.most_common(1)[0]
    rows.append((os.path.basename(p)[:-4], A, B, blk, len(b1), len(b2), len(comb),
                 sorted(b1), sorted(b2), 100.0*top[1]/len(cells), top[0],
                 100.0*comb[(0, 0)]/len(cells), nb))
hdrs = ('map', 'A', 'B', 'blk', 'nb1', 'nb2', 'ncomb', 'top%', 'top', 'zero%')
print('%-40s %3s %3s %5s %3s %3s %5s %6s %-9s %6s' % ('map', 'A', 'B', 'blk', 'n1', 'n2', 'nc', 'top%', 'top', 'zero%'))
for r in sorted(rows, key=lambda r: (r[0].split('_')[2], r[0])):
    print('%-40s %3d %3d %5d %3d %3d %5d %6.2f %-9s %6.2f  b1=%s b2=%s' %
          (r[0][:40], r[1], r[2], r[3], r[4], r[5], r[6], r[9], str(r[10]), r[11], r[7], r[8]))
allb1 = collections.Counter(); allb2 = collections.Counter(); allcomb = collections.Counter()
for r in rows:
    for x in r[7]: allb1[x] += 1
    for x in r[8]: allb2[x] += 1
print('union b1 across sampled maps:', sorted(allb1))
print('union b2 across sampled maps:', sorted(allb2))
print('maps whose b1 set == {0,1,2,3,4,5,8,16}:', sum(1 for r in rows if set(r[7]) == {0, 1, 2, 3, 4, 5, 8, 16}), '/', len(rows))
