"""P4-A step 1: measure path-order packing correctly, then see what it buys.

The earlier check was wrong (it ranked paths against themselves).  Spearman here
compares offset rank against path rank over the NAMED records of each generation.

If a generation is path-sorted, an unnamed record is constrained to sort strictly
between its named neighbours -- which is the only lever left for naming the 24k
unnamed textures.
"""
import collections
import sqlite3
import sys

HERE = r'D:\TLGL\.scratch'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
con = sqlite3.connect('file:%s?mode=ro' % (HERE + r'\resources.db'), uri=True)

rows = collections.defaultdict(list)
for pak, gen, off, h, p in con.execute(
        'select pak, gen, offset, hash, path from resources where offset is not null'):
    rows[(pak, gen)].append((off, h, p))


def spearman(a, b):
    n = len(a)
    if n < 3:
        return 0.0
    ra = {v: i for i, v in enumerate(sorted(range(n), key=lambda i: a[i]))}
    rb = {v: i for i, v in enumerate(sorted(range(n), key=lambda i: b[i]))}
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


good, bad, tot_unnamed = [], [], 0
for key, v in sorted(rows.items()):
    v.sort()
    named = [(o, h, p) for o, h, p in v if p]
    un = len(v) - len(named)
    tot_unnamed += un
    if len(named) < 20:
        continue
    offs = list(range(len(named)))
    paths = sorted(range(len(named)), key=lambda i: named[i][2])
    rank = {pos: i for i, pos in enumerate(paths)}
    rho = spearman(offs, [rank[i] for i in offs])
    (good if rho > 0.95 else bad).append((key, len(named), un, round(rho, 4)))

print('path-sorted generations : %d  (named %d, unnamed %d)' % (
    len(good), sum(x[1] for x in good), sum(x[2] for x in good)))
print('other generations       : %d  (named %d, unnamed %d)' % (
    len(bad), sum(x[1] for x in bad), sum(x[2] for x in bad)))
print('all unnamed records      : %d' % tot_unnamed)
print('\nbest examples:')
for g in sorted(good, key=lambda x: -x[2])[:6]:
    print('   %s named=%d unnamed=%d rho=%s' % g)

# What does sortedness actually constrain?  Count unnamed records that sit ALONE
# between two named neighbours sharing one directory.
alone_same_dir = alone = 0
for key, n, un, rho in good:
    v = sorted(rows[key])
    for i, (o, h, p) in enumerate(v):
        if p:
            continue
        prv = next((v[j][2] for j in range(i - 1, -1, -1) if v[j][2]), None)
        nxt = next((v[j][2] for j in range(i + 1, len(v)) if v[j][2]), None)
        if not prv or not nxt:
            continue
        if all(v[j][2] is None for j in range(max(0, i - 4), min(len(v), i + 5))
               if j != i):
            pass
        alone += 1
        if prv.rsplit('/', 1)[0] == nxt.rsplit('/', 1)[0]:
            alone_same_dir += 1
print('\nunnamed records with named neighbours on both sides: %d' % alone)
print('   ... of which bracketed by the SAME directory     : %d' % alone_same_dir)
