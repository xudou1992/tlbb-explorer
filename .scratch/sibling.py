"""Are texture blobs stored at the material's own path with a different extension?

If `data/effect/textures/mask/w1351_mask_h011.mtl` has a sibling resource at the same
virtual path with `.tga`, then every named material immediately yields its texture --
which is all a preview needs.
"""
import collections
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jhash import path_hash

HERE = os.path.dirname(os.path.abspath(__file__))
con = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'resources.db'), uri=True)
known = {int(h, 16) for (h,) in con.execute('select hash from resources')}
types = dict(con.execute('select hash, type from resources'))

stat = collections.Counter()
ex = collections.defaultdict(list)
for h, p, t in con.execute(
        "select hash, path, type from resources where path is not null and ext in "
        "('.mtl','.mesh','.ske','.mdl','.pu','.scene','.ani')"):
    stem = p.rsplit('.', 1)[0]
    for cand in (stem + '.tga', stem + '.dds', stem + '.png', stem, stem + '.TGA',
                 p.replace('/textures/', '/texture/')):
        k = path_hash(cand)
        if k in known:
            key = (t, cand[len(stem):] or '(no ext)')
            stat[key] += 1
            if len(ex[key]) < 3:
                ex[key].append((cand, types.get('%016x' % k)))
            break
    else:
        stat[(t, 'MISS')] += 1

for k, v in stat.most_common(24):
    print('%-12s %-14s %6d   %s' % (k[0], k[1], v, ex.get(k, [''])[0] if k[1] != 'MISS' else ''))
