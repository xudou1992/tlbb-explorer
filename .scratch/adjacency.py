"""Do related resources sit next to each other in the pak?

The name->blob mapping for textures is gone, but the packer wrote resources in some
order.  If a material and its textures were packed together, offset distance is a
recoverable signal -- and that would let effects be previewed without any names.

Ground truth: the 25 .mtl -> .tga references that DO resolve to a named texture.
Compare their offset distance against random material/texture pairs.
"""
import collections
import random
import sqlite3
import sys

HERE = r'D:\TLGL\.scratch'
con = sqlite3.connect('file:%s?mode=ro' % (HERE + r'\resources.db'), uri=True)

pos = {h: (p, g, o) for h, p, g, o in con.execute(
    'select hash, pak, gen, offset from resources')}
pairs = con.execute(
    "select from_hash, to_hash from relations where rel='use-tex'").fetchall()
print('resolved material->texture edges:', len(pairs))

tex = [h for (h,) in con.execute(
    "select hash from resources where type='texture' and pak is not null")]
mtl = [h for (h,) in con.execute("select hash from resources where ext='.mtl'")]


def dist(a, b):
    pa, ga, oa = pos[a]
    pb, gb, ob = pos[b]
    if pa != pb or ga != gb:
        return None
    return abs(ob - oa)


same = [d for d in (dist(a, b) for a, b in pairs) if d is not None]
print('pairs in the same pak+generation: %d / %d' % (len(same), len(pairs)))
if same:
    same.sort()
    print('  referenced distance  min=%s median=%s max=%s' %
          (f'{same[0]:,}', f'{same[len(same)//2]:,}', f'{same[-1]:,}'))

rnd = random.Random(7)
base = []
for _ in range(3000):
    d = dist(rnd.choice(mtl), rnd.choice(tex))
    if d is not None:
        base.append(d)
base.sort()
print('random same-pak material/texture distance: median=%s (n=%d)' %
      (f'{base[len(base)//2]:,}', len(base)))
if same and base:
    med_s, med_b = same[len(same) // 2], base[len(base) // 2]
    print('ratio referenced/random = %.3f  -> %s' % (
        med_s / med_b, '有相邻信号' if med_s < med_b / 3 else '无信号，打包顺序不携带关系'))

# how are offsets ordered at all? is it hash order, path order, or size order?
row = con.execute("select pak, gen, offset, hash from resources where pak is not null "
                  "order by pak, gen, offset limit 12").fetchall()
print('\nfirst records of one generation (offset order):')
for r in row:
    p = con.execute('select path, type, original from resources where hash=?',
                    (r[3],)).fetchone()
    print('   %14s %-8s %s' % (f'{r[2]:,}', (p[1] or '')[:8], (p[0] or r[3])[:56]))
