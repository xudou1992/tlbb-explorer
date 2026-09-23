import os
import re
import sys

d = r'D:\TLGL\.scratch\out\named'
pat = re.compile(rb'[\x20-\x7e]{6,}')
for fn in sorted(os.listdir(d)):
    b = open(os.path.join(d, fn), 'rb').read()
    hits = pat.findall(b[:400000])
    uniq = []
    seen = set()
    for h in hits:
        if h not in seen:
            seen.add(h)
            uniq.append(h)
    print('=== %s  (%d bytes, %d distinct strings in first 400KB)' % (fn, len(b), len(uniq)))
    for h in uniq[:14]:
        print('    %r' % h)
