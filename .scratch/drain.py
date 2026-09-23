"""Drain every extracted asset for embedded resource-path tables.

`ResourcePath.cfg` proved the engine ships tables of length-prefixed virtual paths.  Rather than
assuming which file holds them, scan the whole extracted tree for that record grammar and
hash-match every candidate; a 64-bit index hit names the asset.
"""
import collections
import os
import re
import sys
import time

sys.path.insert(0, r'D:\TLGL\.scratch')
from mine2 import batch_hash

HERE = r'D:\TLGL\.scratch'
ROOT = os.path.join(HERE, 'out', 'all')
LEGAL = set(range(0x21, 0x7f)) - set(b'"\'<>|?*(){}[],;: ')
EXTRE = re.compile(rb'\.[A-Za-z0-9]{1,6}$')
PREF = (b'data', b'ui/', b'3d', b'res', b'set', b'log', b'mob', b'tex', b'sou', b'sce', b'web',
        b'Pc/', b'pc/', b'mod', b'eff', b'fx/', b'anm', b'ani', b'sha', b'scr', b'mesh', b'npc')
PREFB = (b'data/', b'ui/', b'mobile_maps', b'settings/', b'data\\', b'3d/', b'res/', b'source/')
CH = 300000
MAXLEN = 200
MINFILE = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
MAXFILE = 30 * 1024 * 1024


STRT = re.compile(b'|'.join(PREFB))


def records(d):
    """Fast path: locate a known root, then read the length byte immediately before it."""
    out = []
    app = out.append
    n = len(d)
    for m in STRT.finditer(d):
        i = m.start()
        if i == 0:
            continue
        L = d[i - 1]
        if 6 <= L <= 200:
            s = d[i:i + L]
            if (len(s) == L and EXTRE.search(s) and b'/' in s and not (set(s) - LEGAL)):
                app(s)
    return out


def main():
    with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
        next(f)
        tset = set(int(l.split('\t', 1)[0], 16) for l in f)
    names = {}
    for fn in ('names_jrpc.tsv', 'names_round.tsv', 'dicthits.txt', 'names_new.tsv', 'names.tsv'):
        p = os.path.join(HERE, fn)
        if os.path.isfile(p):
            for l in open(p, encoding='utf-8'):
                if l.startswith('hash\t'):
                    continue
                a = l.rstrip('\n').split('\t')
                if len(a) >= 2 and a[1]:
                    names[a[0]] = a[1]
    print('targets %d, seeded %d' % (len(tset), len(names)), flush=True)
    pool = {}
    T0 = time.time()
    nf = nb = 0
    for stem in sorted(os.listdir(ROOT)):
        base = os.path.join(ROOT, stem)
        if not os.path.isdir(base):
            continue
        for root, _d, fs in os.walk(base):
            for fn in fs:
                p = os.path.join(root, fn)
                try:
                    sz = os.path.getsize(p)
                    if not (MINFILE <= sz <= MAXFILE):
                        continue
                    b = open(p, 'rb').read()
                except OSError:
                    continue
                nf += 1
                if not any(x in b for x in PREFB):
                    continue
                nb += len(b)
                r = records(b)
                if len(r) >= 3:
                    for s in r:
                        pool[s] = None
                if nf % 8000 == 0:
                    print('  %d files %.2f GB, path pool %d (%.0fs)' % (
                        nf, nb / 1e9, len(pool), time.time() - T0), flush=True)
    print('scanned %d files / %.2f GB -> %d candidate paths (%.0fs)' % (
        nf, nb / 1e9, len(pool), time.time() - T0), flush=True)
    uniq = list(pool)
    new = {}
    for i in range(0, len(uniq), CH):
        chunk = uniq[i:i + CH]
        L = min(max(len(t) for t in chunk), MAXLEN)
        for t, h in zip(chunk, batch_hash([x[:L] for x in chunk], L)):
            k = '%016x' % int(h)
            if k in tset and k not in names:
                names[k] = t.decode('ascii', 'replace')
                new[k] = names[k]
    with open(os.path.join(HERE, 'names_drain.tsv'), 'w', encoding='utf-8') as o:
        o.write('hash\tpath\n')
        for k, v in sorted(names.items()):
            o.write('%s\t%s\n' % (k, v))
    print('NEW %d, total %d (%.0fs)' % (len(new), len(names), time.time() - T0), flush=True)
    print('dirs:', collections.Counter('/'.join(v.split('/')[:-1]) for v in new.values()).most_common(20))
    print('exts:', collections.Counter(os.path.splitext(v)[1].lower() for v in new.values()).most_common(20))


if __name__ == '__main__':
    main()
