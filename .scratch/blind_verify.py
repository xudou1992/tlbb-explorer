"""Prove/disprove the recovered grid-scene paths with an independent signal:
instance world positions must fall inside the cell the file name claims.
Control group = the 9,288 NAMED grid753 files; test group = the 1,126 RECOVERED ones.
Read-only.
"""
import collections
import math
import re
import struct
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from blind_reader import conn, Reader  # noqa: E402
from jhash import path_hash  # noqa: E402

C = conn()
R = Reader()


def first_positions(b):
    """Return up to 8 (x,z) translation pairs, scanning the record stride."""
    if not b or len(b) < 92:
        return []
    n, tag = struct.unpack_from('<II', b, 0)
    if tag not in (749, 753):
        return []
    stride = 761 if tag == 753 else 757
    out = []
    for i in range(min(int(n), 8)):
        p = 12 + i * stride
        if p + 76 > len(b):
            break
        m = struct.unpack_from('<16f', b, p)
        x, z = m[12], m[14]
        if math.isfinite(x) and math.isfinite(z) and abs(x) < 4000 and abs(z) < 4000:
            out.append((x, z))
    return out


def rate(rows_iter, label):
    good = bad = 0
    files_ok = files = 0
    for row, cy, cz in rows_iter:
        pos = first_positions(R.get(row)[0])
        if not pos:
            continue
        files += 1
        g = sum(1 for x, z in pos if int(math.floor(x / 32.0)) == cy and int(math.floor(z / 32.0)) == cz)
        good += g
        bad += len(pos) - g
        if g:
            files_ok += 1
    print('  %-28s files=%d files-with-a-hit=%d instances match=%d mismatch=%d rate=%.3f'
          % (label, files, files_ok, good, bad, good / max(1, good + bad)))
    return good, bad


print('=== control: NAMED grid753 (path comes from ResourcePath.cfg) ===')
it = []
for row in C.execute("select * from resources where subtype='grid753' and named=1 limit 600"):
    m = re.match(r'^\d+_(-?\d+)_(-?\d+)\.scene$', row['name'])
    if m:
        it.append((row, int(m.group(1)), int(m.group(2))))
rate(it, 'named 600 files')

print('=== recovered by <map>/<1>_<y>_<z>.scene path-hash enumeration ===')
un = {}
for row in C.execute("select * from resources where subtype='grid753' and named=0"):
    un[row['hash']] = row
dirs = [d for (d,) in C.execute("select distinct dir from resources where dir like 'mobile_maps/%'").fetchall()]
found = {}
for d in dirs:
    for a in range(0, 4):
        for y in range(-6, 18):
            for z in range(-18, 6):
                k = '%016x' % path_hash('%s/%d_%d_%d.scene' % (d, a, y, z))
                if k in un:
                    found[k] = (d, a, y, z)
print('  recovered', len(found), 'of', len(un))
it = [(un[h], y, z) for h, (d, a, y, z) in found.items()]
rate(it, 'recovered 1126 files')

print('=== negative control: deliberately WRONG cell index (y+1, z-1) ===')
it2 = [(un[h], y + 1, z - 1) for h, (d, a, y, z) in found.items()]
rate(it2, 'shifted index')

print('=== sanity: how many candidate paths collide with an existing named .scene? ===')
allh = {r[0]: r[1] for r in C.execute("select hash,path from resources").fetchall()}
n = 0
for d in dirs[:40]:
    for y in range(-6, 18):
        for z in range(-18, 6):
            k = '%016x' % path_hash('%s/1_%d_%d.scene' % (d, y, z))
            if k in allh:
                n += 1
print('  in 40 dirs: %d of %d grid paths hash to an existing resource row' % (n, 40 * 24 * 24))
