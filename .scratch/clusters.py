"""Map header clusters to extension mix, and dump representative heads."""
import collections
import json
import os
import sqlite3
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ALL = os.path.join(HERE, 'out', 'all')
paths = {}
for pak in os.listdir(OUT_ALL):
    d = os.path.join(OUT_ALL, pak)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if len(fn) >= 16:
            paths.setdefault(fn[:16], os.path.join(d, fn))

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
rows = con.execute("SELECT hash, ext, original FROM resources WHERE type IN ('binary','unknown')")
mix = collections.defaultdict(collections.Counter)
for h, ext, orig in rows:
    p = paths.get(h)
    head = open(p, 'rb').read(8) if p else b''
    if len(head) == 8 and head[4:] in (b'\xf1\x02\x00\x00', b'\x18\x01\x00\x00'):
        k = 'u32@4=%s' % struct.unpack('<I', head[4:8])[0]
    elif head[:8] == b'\x00' * 8:
        k = 'zero8'
    else:
        k = 'other:' + head[:6].hex()
    mix[k][ext or '(unnamed)'] += 1
with open(os.path.join(HERE, 'clusters.txt'), 'w', encoding='utf-8') as o:
    for k, c in sorted(mix.items(), key=lambda x: -sum(x[1].values()))[:14]:
        o.write('%-16s total=%-7d %s\n' % (k, sum(c.values()), c.most_common(6)))

for probe in ('w1351_nv_clip5.anis',):
    hit = con.execute('SELECT hash FROM resources WHERE name=?', (probe,)).fetchone()
    if hit:
        p = paths[hit[0]]
        b = open(p, 'rb').read(160)
        o = ['== %s (%s bytes) ==' % (probe, os.path.getsize(p))]
        for off in range(0, 128, 16):
            ch = b[off:off + 16]
            o.append('   +%02x %s  |%s|' % (off, ' '.join('%02x' % x for x in ch),
                                            ''.join(chr(x) if 32 <= x < 127 else '.' for x in ch)))
        o.append('   ints: %s' % ' '.join(map(str, struct.unpack('<20I', b[:80]))))
        open(os.path.join(HERE, 'anis_head.txt'), 'w', encoding='utf-8').write('\n'.join(o))
print('ok')
