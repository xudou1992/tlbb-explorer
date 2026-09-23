"""Second-round dictionary: harvest path candidates from loose game binaries + logs."""
import os
import re
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from jhash import path_hash

HERE = r'D:\TLGL\.scratch'
targets = set()
with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
    next(f)
    for line in f:
        targets.add(int(line.split('\t', 1)[0], 16))
print('targets: %d' % len(targets))

SRC = [r'D:\TLGL\tlbbgl_x64.exe', r'D:\TLGL\gameupdater.log', r'D:\TLGL\debug.log',
       r'D:\TLGL\tlbb_gwobzb11_full.exe', r'D:\TLGL\tlbb_gwobzb11_full_x64.exe',
       r'D:\TLGL\NEP2_64.dll']
for d in (r'D:\TLGL\tmg_x64', r'D:\TLGL\webview_x64', r'D:\TLGL\DirectX'):
    if os.path.isdir(d):
        for root, _dd, fs in os.walk(d):
            for fn in fs:
                SRC.append(os.path.join(root, fn))

pat = re.compile(rb'[\x20-\x7e]{4,250}')
cands = set()
for p in SRC:
    if not os.path.isfile(p):
        continue
    try:
        b = open(p, 'rb').read()
    except OSError:
        continue
    for m in pat.finditer(b):
        s = m.group()
        if b'.' not in s and b'/' not in s:
            continue
        if s.count(b' ') > 2 or b'%' in s or b'*' in s:
            continue
        cands.add(s.decode('ascii'))
    print('scanned %s (%d bytes), cands so far %d' % (os.path.basename(p), len(b), len(cands)))

hits = {}
for c in cands:
    h = path_hash(c)
    if h in targets:
        hits[h] = c
print('hits: %d' % len(hits))
with open(os.path.join(HERE, 'dict2.txt'), 'w', encoding='utf-8') as o:
    for h, c in sorted(hits.items()):
        o.write('%016x\t%s\n' % (h, c))
