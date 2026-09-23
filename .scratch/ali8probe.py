"""Is ALI8 raw 8-bit, or a block format? Adjacent-pixel statistics decide."""
import sqlite3

import numpy as np

import pv_jmt1 as P

con = sqlite3.connect('file:resources.db?mode=ro', uri=True)
sel = []
for (h,) in con.execute("select hash from resources where type='texture'"):
    p = P.FIND.get(h)
    if not p:
        continue
    j = P.parse(p)
    if j and j['codec'] == 'ALI8':
        sel.append((h, j))
    if len(sel) >= 12:
        break

print('ALI8 samples:', len(sel))
for h, j in sel[:8]:
    w, hh = j['w'], j['h']
    blk = ((w + 3) // 4) * ((hh + 3) // 4)
    raw = j['raw'][28:28 + j['l0']]
    a = np.frombuffer(raw, dtype=np.uint8).reshape(hh, w).astype(np.int16)
    mad = np.abs(np.diff(a, axis=1)).mean()
    mad2 = np.abs(np.diff(a, axis=0)).mean()
    print('  %s %4dx%-4d l0=%-7d w*h=%-7d b0*16=%-7d b0*8=%-7d  MAD h=%.1f v=%.1f  min=%d max=%d uniq=%d' % (
        h[:8], w, hh, j['l0'], w * hh, blk * 16, blk * 8, mad, mad2,
        a.min(), a.max(), len(np.unique(a))))
