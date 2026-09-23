# -*- coding: utf-8 -*-
import sqlite3, re, collections, sys
sys.stdout.reconfigure(encoding='utf-8')

M = {}
for l in open('pinyin_map.tsv', encoding='utf-8'):
    a, b = l.rstrip('\n').split('\t')
    M[a] = b
REA = set(M.values())
print('reachable syllables:', len(REA), sorted(REA, key=lambda s: (len(s), s))[:14])

db = sqlite3.connect('file:resources.db?mode=ro', uri=True)
stems = [r[0] for r in db.execute('select stem from agroups')]
dirs = [r[0] for r in db.execute('select dir from agroups')]
SEP = re.compile(r'[_\-/. ]')
def norm(s):
    return SEP.sub('', s.lower())

leaves = [d.rstrip('/').split('/')[-1] for d in dirs]
HAY = set()
for x in stems + leaves:
    if not x:
        continue
    n = norm(x)
    if n:
        HAY.add(n)
print('haystacks', len(HAY))


def runs(h):
    return [m.group(0) for m in re.finditer(r'[a-z]+', h)]


def segment(r, dic):
    n = len(r)
    best = [None] * (n + 1)
    best[0] = ''
    for i in range(n):
        if best[i] is None:
            continue
        for L in range(min(13, n - i), 0, -1):
            piece = r[i:i + L]
            if piece in dic and best[i + L] is None:
                best[i + L] = (best[i] + ' ' + piece).strip()
    return best[n]


bad = collections.Counter()
for h in HAY:
    for r in runs(h):
        if segment(r, REA) is None:
            bad[r] += 1
print('UNSEGMENTABLE alpha runs:', len(bad))
for k, v in bad.most_common(40):
    print('  ', k, v)
