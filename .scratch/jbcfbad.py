"""Why do 9,980 JBCF files have no id-85 chunk? Report the chunk id actually found."""
import collections
import os
import sqlite3
import struct

import jbcf

HERE = r'D:\TLGL\.scratch'
con = sqlite3.connect('file:resources.db?mode=ro', uri=True)
idx = {}
for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
    d = os.path.join(HERE, 'out', 'all', pak)
    if os.path.isdir(d):
        for fn in os.listdir(d):
            idx[fn[:16]] = os.path.join(d, fn)

ok = collections.Counter()
bad = collections.Counter()
ids = collections.Counter()
sizehint = collections.Counter()
for h, ext, path in con.execute("select hash, ext, path from resources where type='JBCF'"):
    f = idx.get(h)
    if not f:
        continue
    raw = open(f, 'rb').read()
    try:
        hdr, soff, flag, strs = jbcf.parse(raw)
        ok[ext] += 1
        continue
    except ValueError as e:
        bad[ext] += 1
    if len(raw) >= 24 and raw[:4] == b'JBCF':
        a = struct.unpack_from('<6I', raw, 0)
        off = jbcf.r8(a[5]) + 24
        if off + 16 <= len(raw):
            sid, ssize = struct.unpack_from('<2I', raw, off)
            ids[(ext, sid)] += 1
            sizehint[(ext, ssize > 8, len(raw) - off)] += 1
        else:
            ids[(ext, 'past EOF')] += 1

print('parsed  :', ok.most_common())
print('unparsed:', bad.most_common())
print('chunk2 id at formula offset:', ids.most_common(18))
print('size>8 / tail bytes:', sizehint.most_common(12))
