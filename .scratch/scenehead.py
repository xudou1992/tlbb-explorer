"""Dump a big 753-tag scene head to see whether it embeds object paths."""
import os
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ALL = os.path.join(HERE, 'out', 'all')
paths = {}
for pak in os.listdir(OUT_ALL):
    d = os.path.join(OUT_ALL, pak)
    if not os.path.isdir(d):
        continue
    for fn in os.listdir(d):
        if len(fn) >= 16:
            paths.setdefault(fn[:16], os.path.join(d, fn))

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
q = ("SELECT hash,name,dir,original FROM resources WHERE type='binary' "
     "AND (name LIKE '%.scene' OR dir LIKE '%map%') ORDER BY original DESC LIMIT 5")
for h, name, d, orig in con.execute(q):
    b = open(paths[h], 'rb').read(288)
    print('== %s  dir=%s  size=%d' % (name or h, d, orig))
    for off in range(0, 176, 16):
        ch = b[off:off + 16]
        print('   +%02x %s  |%s|' % (off, ' '.join('%02x' % x for x in ch),
                                     ''.join(chr(x) if 32 <= x < 127 else '.' for x in ch)))
    print('   printable runs:', [s.decode('latin1') for s in
                                 __import__('re').findall(rb'[\x20-\x7e]{8,}', b)][:6])
