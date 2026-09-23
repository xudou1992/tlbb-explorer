"""Dictionary attack: hash ASCII strings from extracted tables, intersect pak hash set."""
import os
import re
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from jhash import path_hash

HERE = r'D:\TLGL\.scratch'
targets = set()
for line in open(os.path.join(HERE, 'hashes.txt')):
    line = line.strip()
    if line:
        targets.add(int(line, 16))
print('pak hashes: %d' % len(targets))

pat = re.compile(rb'[\x20-\x7e]{4,200}')
cands = set()
d = os.path.join(HERE, 'out', 'named')
for fn in os.listdir(d):
    b = open(os.path.join(d, fn), 'rb').read()
    keep = 0
    for m in pat.finditer(b):
        s = m.group()
        if s.count(b'/') + s.count(b'\\') + s.count(b'.') < 1:
            continue
        if b' ' in s or b'%' in s:
            continue
        cands.add(s.decode('ascii'))
        keep += 1
print('candidate strings: %d (from %d)' % (len(cands), keep))

hits = {}
for c in cands:
    for p in ('', 'data/', 'res/', 'scripts/', 'ui/', 'scene/', '_tlbb/'):
        try:
            h = path_hash(p + c)
        except Exception:
            continue
        if h in targets:
            hits.setdefault(h, []).append(p + c)
            break

print('hash hits: %d' % len(hits))
with open(os.path.join(HERE, 'dicthits.txt'), 'w', encoding='utf-8') as o:
    for h, ps in sorted(hits.items()):
        o.write('%016x\t%s\n' % (h, ps[0]))
for h, ps in sorted(hits.items())[:40]:
    print('  %016x  %s' % (h, ps[0]))
