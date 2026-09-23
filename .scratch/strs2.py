"""Scan extracted named tables for path-like ASCII strings (whole file)."""
import os
import re
import sys

d = r'D:\TLGL\.scratch\out\named'
# require a '/' or '\' separator or a known asset extension
pat = re.compile(rb'[\x20-\x7e]{5,}')
ext = re.compile(rb'\.(?:lua|xml|png|tga|jpg|dds|wav|ogg|mp4|ini|cfg|txt|tab|jstr|mesh|jmdl|jmt|usm|bytes|json|glsl|hlsl|fx|sprite|atlas|skel|anim|prefab|res)$', re.I)

total = {}
for fn in sorted(os.listdir(d)):
    b = open(os.path.join(d, fn), 'rb').read()
    cands = []
    for m in pat.finditer(b):
        s = m.group()
        if b'/' in s or b'\\' in s or ext.search(s):
            cands.append(s)
    uniq = sorted(set(cands))
    total[fn] = uniq
    print('=== %s (%d bytes) -> %d path-like strings' % (fn, len(b), len(uniq)))
    for s in uniq[:12]:
        print('    %r' % s)

with open(os.path.join(r'D:\TLGL\.scratch', 'tablestrings.txt'), 'w', encoding='utf-8') as o:
    for fn, u in total.items():
        for s in u:
            o.write('%s\t%s\n' % (fn, s.decode('ascii', 'replace')))
print('wrote tablestrings.txt')
