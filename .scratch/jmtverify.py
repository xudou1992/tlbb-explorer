"""Verify the JMT1 mip-table layout: [24B header][per mip: u32 size + data]*, and check
whether the declared codec 4CC matches the block size implied by each mip."""
import os
import sqlite3
import struct

HERE = r'D:\TLGL\.scratch'
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
rows = con.execute("SELECT hash, codec, width, height, mips, original FROM resources "
                   "WHERE type='texture' AND width>0 ORDER BY original DESC LIMIT 400").fetchall()
ok = bad = 0
kinds = {}
notes = []
for h, codec, w, hh, nmip, orig in rows:
    if not w or not hh or not nmip:
        continue
    raw = open(paths[h], 'rb').read()
    declared = struct.unpack_from('<I', raw, 12)[0]
    p = 24
    sizes = []
    good = True
    for i in range(nmip):
        if p + 4 > len(raw):
            good = False
            break
        s = struct.unpack_from('<I', raw, p)[0]
        sizes.append(s)
        p += 4 + s
    expect = []
    for i in range(nmip):
        bw, bh = max(1, w >> i), max(1, hh >> i)
        expect.append((bw + 3) // 4 * ((bh + 3) // 4) * 16)     # BC3 / DXT5
    match = good and sizes == expect
    ok += match
    bad += not match
    blk = 'BC3' if sizes and expect and sizes[0] == expect[0] else (
        'BC1' if sizes and sizes[0] == ((w + 3) // 4) * ((hh + 3) // 4) * 8 else '?')
    if codec == 'RGBA':
        blk = 'RAW32' if sizes and sizes[0] == w * hh * 4 else '?'
    kinds[(codec, blk)] = kinds.get((codec, blk), 0) + 1
    if not match and len(notes) < 6:
        notes.append((h, codec, w, hh, nmip, sizes[:4], expect[:4]))
    if p != 24 + declared:
        notes.append(('tailmismatch', h, codec, p, 24 + declared))

print('mip-table layout confirmed on %d / %d sampled textures' % (ok, ok + bad))
print('declared 4CC vs implied block size:', kinds)
for n in notes:
    print('  ', n)
