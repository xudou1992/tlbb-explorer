"""Identify the per-string u32 in the JBCF string table.

Two questions: (1) is it stable for a given string across files (i.e. a hash, not a
runtime id)? (2) does it equal the u32 'marker' in JMT1 texture headers, which would
let material references resolve to unnamed textures.
"""
import collections
import json
import os
import sqlite3

import jbcf

HERE = r'D:\TLGL\.scratch'
con = sqlite3.connect('file:resources.db?mode=ro', uri=True)
idx = {}
for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
    d = os.path.join(HERE, 'out', 'all', pak)
    if os.path.isdir(d):
        for fn in os.listdir(d):
            idx[fn[:16]] = os.path.join(d, fn)

seen = collections.defaultdict(collections.Counter)
n = 0
for h, in con.execute("select hash from resources where type='JBCF'"):
    f = idx.get(h)
    if not f:
        continue
    try:
        _, _, _, strs = jbcf.parse(open(f, 'rb').read())
    except ValueError:
        continue
    for s, hv in strs:
        if s:
            seen[s][hv] += 1
    n += 1
    if n >= 3000:
        break

multi = [(s, c) for s, c in seen.items() if len(c) > 1]
print('strings seen: %d   with >1 distinct u32: %d' % (len(seen), len(multi)))
print('sample multi:', [(s, dict(c)) for s, c in multi[:5]])

# Compare against JMT1 markers
mark = collections.Counter()
for props, in con.execute("select props from resources where type='texture'"):
    try:
        p = json.loads(props or '{}')
    except ValueError:
        continue
    if 'marker' in p:
        mark[p['marker']] += 1
names = {s: next(iter(c)) for s, c in seen.items() if len(c) == 1}
hits = sum(1 for s, v in names.items() if v in mark)
print('JMT1 distinct markers: %d ; strtab names with stable u32: %d ; cross-hits: %d'
      % (len(mark), len(names), hits))
print('example stable:', list(names.items())[:6])
print('top markers:', mark.most_common(6))
