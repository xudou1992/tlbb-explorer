"""Harvest self-described virtual paths (GATA ref, Copyright embedded runs) into a name map.

A container whose payload opens with its own virtual path names itself; hashing that
string with the canonical engine hash proves the match, so these are ground-truth names
for otherwise hash-only resources.
"""
import json
import os
import sqlite3
import sys

HERE = r'D:\TLGL\.scratch'
sys.path.insert(0, HERE)
import jhash

con = sqlite3.connect(os.path.join(HERE, 'resources.db'))
rows = list(con.execute("SELECT hash, path, props, type FROM resources "
                         "WHERE props LIKE '%ref%' OR props LIKE '%embedded%'"))
byhex = {h: p for h, p in con.execute("SELECT hash, path FROM resources WHERE path IS NOT NULL")}
new = {}
selfs = 0
for h, p, props, t in rows:
    d = json.loads(props or '{}')
    cands = [d.get('ref')] + (d.get('embedded') or [])
    for cand in filter(None, cands):
        cand = cand.replace('\\', '/').lstrip('/')
        if len(cand) < 6:
            continue
        k = '%016x' % jhash.path_hash(cand)
        if k == h:
            selfs += 1
            new[h] = cand
        elif k in byhex:
            new.setdefault(k, byhex[k])
out = [l for l in open(os.path.join(HERE, 'names_jrpc.tsv'), encoding='utf-8')][0]
added = 0
with open(os.path.join(HERE, 'names_self.tsv'), 'w', encoding='utf-8') as o:
    o.write('hash\tpath\n')
    for k, v in sorted(new.items()):
        o.write('%s\t%s\n' % (k, v))
        added += 1
print('rows scanned %d   self-describing %d   mapped names %d' % (len(rows), selfs, added))
print('newly named (previously hash-only): %d' % len([k for k in new if k not in byhex]))
