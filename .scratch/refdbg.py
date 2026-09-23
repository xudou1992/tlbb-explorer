import json
import sqlite3
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
import jhash

con = sqlite3.connect(r'D:\TLGL\.scratch\resources.db')
c = con.cursor()
paths = dict(c.execute('SELECT hash, path FROM resources WHERE path IS NOT NULL'))
known = {int(h, 16) for h in paths}
sel = list(c.execute("SELECT hash, props FROM resources WHERE props LIKE '%ref%' "
                     "OR props LIKE '%embedded%'"))
print('rows selected:', len(sel))
noc = hit = 0
misses = []
for h, props in sel:
    d = json.loads(props or '{}')
    cands = [x for x in filter(None, [d.get('ref')] + (d.get('embedded') or []))]
    if not cands:
        noc += 1
        continue
    p = paths.get(h) or ''
    base = p.rsplit('/', 1)[0] if '/' in p else ''
    for cand in cands:
        cand = cand.replace('\\', '/').lstrip('/')
        trials = [cand] if '/' in cand else ([base + '/' + cand] if base else []) + [cand]
        for t in trials:
            k = jhash.path_hash(t)
            if ('%016x' % k) in paths:
                hit += 1
                break
        else:
            if len(misses) < 4:
                misses.append((h, cand))
print('rows without candidates:', noc, 'hits:', hit)
for m in misses:
    print('  MISS', m)
