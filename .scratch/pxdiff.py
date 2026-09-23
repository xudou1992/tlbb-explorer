"""Pixel-parity gate: Rust previews vs an independent Pillow/DDS reference.

Regenerate the Rust side with
    target/release/preview-scan.exe --pick 900 --out D:/TLGL/.scratch/m2px2
then run this. Expected: RGBA exact, BC1/BC3 within ±1 (palette interpolation
rounding), WebP byte-identical, ALI8 skipped (Pillow's 8-bit DDS path divides by a
zero pitch in pv_jmt1, so it is checked by eye in m2_ali8.png instead).
"""
import collections
import io
import os
import sys

import pv_jmt1 as P
from PIL import Image

D = sys.argv[1] if len(sys.argv) > 1 else r'D:\TLGL\.scratch\m2px2\texture_preview'
res = collections.Counter()
bad = []
for fn in sorted(os.listdir(D)):
    h = fn.split('.')[0]
    if len(h) != 16:
        continue
    p = P.FIND.get(h)
    if not p:
        res['no raw payload'] += 1
        continue
    j = P.parse(p)
    if not j or j['codec'] in ('COLR', 'ALI8'):
        res['skipped ' + str(j and j['codec'])] += 1
        continue
    got = Image.open(os.path.join(D, fn)).convert('RGBA')
    dds, kind = P.to_dds(j)
    if kind == 'webp':
        res[('webp bytes identical', open(os.path.join(D, fn), 'rb').read() == dds)] += 1
        continue
    ref = Image.open(io.BytesIO(dds)).convert('RGBA')
    if ref.size != got.size:
        res['size differ'] += 1
        continue
    a = ref.tobytes()
    b = got.tobytes()
    md = max((abs(x - y) for x, y in zip(a, b)), default=0)
    # Pixels fully transparent in the source carry junk RGB; Pillow zeroes them.
    if md and 'RGBA' == j['codec']:
        import numpy as np
        ra = np.frombuffer(a, dtype=np.uint8).reshape(-1, 4)
        rb = np.frombuffer(b, dtype=np.uint8).reshape(-1, 4)
        opaque = ra[:, 3] > 0
        md = int(np.abs(ra[opaque].astype(int) - rb[opaque].astype(int)).max()) if opaque.any() else 0
        res[('RGBA', 'exact on alpha>0' if md == 0 else 'maxdiff%d' % md)] += 1
    else:
        res[(j['codec'], 'exact' if a == b else 'maxdiff%d' % md)] += 1
    if md > 1 and len(bad) < 6:
        bad.append((h, j['codec'], md))

print('compared', sum(v for k, v in res.items() if isinstance(v, int)))
for k, v in sorted(res.items(), key=lambda x: -x[1]):
    print('  ', k, v)
print('out of tolerance:', bad)
sys.exit(1 if bad else 0)
