import struct, os, glob, collections, sys

BASE = 'out/tree/mobile_maps'
paths = sorted(glob.glob(BASE + '/*/*.map'))
print('num .map', len(paths))
rows = []
for p in paths:
    sz = os.path.getsize(p)
    with open(p, 'rb') as f:
        h = f.read(32)
    v = struct.unpack('<8I', h)
    rows.append((p, sz, v))

# check header consistency
bad = 0
for p, sz, v in rows[:40]:
    print(os.path.basename(p), 'size', sz, v[:6])

print()
c = collections.Counter()
for p, sz, v in rows:
    c[(v[0], v[3])] += 1
print('counter (magic, 4th u32):', c.most_common(10))
c2 = collections.Counter(v[4] for p, sz, v in rows)
print('counter u32[4] (offset-after-blocks?):', c2.most_common(5), 'distinct', len(c2))

# test hypothesis: u32[1]=A, u32[2]=B, hdr=152, blksize=4160, u32[3]=152+? or =hdrsize
okA = 0
resid = collections.Counter()
detail = []
for p, sz, v in rows:
    A, B, f4 = v[1], v[2], v[3]
    u16, u17, u18 = v[4], v[5], v[6]
    if f4 != 152:
        resid['hdr152'] += 1
    if u16 == f4 + A*B*4160:
        okA += 1
    else:
        resid['u16!=hdr+A*B*4160'] += 1
        if len(detail) < 25:
            detail.append((os.path.basename(p), A, B, f4, u16, u17, u18, sz, A*B, (u16-f4)/(A*B) if A*B else 0))
    if u18 != sz:
        resid['u18!=filesize'] += 1
print('A*B*4160+152==u16 :', okA, '/', len(rows))
print('resid', resid.most_common(10))
for d in detail:
    print('  detail', d)

# trailer arithmetic
for p, sz, v in rows[:12]:
    A, B = v[1], v[2]
    tail = sz - v[4]
    n = v[5]
    print(os.path.basename(p), 'A', A, 'B', B, 'blocks', A*B, 'tailbytes', tail, 'u17', n,
          'tail/n' , tail/n if n else 0, 'tail/(A*B)', tail/(A*B))
