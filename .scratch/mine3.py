"""Stage 3: iterative prefix expansion.

The engine mounts roots ("ui", "data", "logic", "3d", ...) and the config/string tables store
paths *relative* to a root, so a token "icon/skill/x.tga" only hashes to an index entry once the
correct ancestor directory is prepended.

Round r hashes every token against every directory that appears as an ancestor of an
already-known name; each new hit contributes new ancestor directories, so the prefix set grows
and naming coverage compounds.
"""
import itertools
import os
import sys
import time

import numpy as np

sys.path.insert(0, r'D:\TLGL\.scratch')
from mine2 import batch_hash

HERE = r'D:\TLGL\.scratch'
CH = 400000
MAXCOMBO = 400000000        # ~320k combos/s measured -> ~20 min per round
MAXLEN = 200
TIMEBOX = 1800


def load_names():
    names = {}
    for fn in ('names_round.tsv', 'dicthits.txt', 'names_new.tsv', 'names.tsv'):
        p = os.path.join(HERE, fn)
        if not os.path.isfile(p):
            continue
        for l in open(p, encoding='utf-8'):
            if l.startswith('hash\t'):
                continue
            a = l.rstrip('\n').split('\t')
            if len(a) >= 2 and a[1]:
                names[a[0]] = a[1]
    return names


def ancestors(path):
    parts = path.replace('\\', '/').split('/')[:-1]
    out = []
    for i in range(len(parts)):
        out.append('/'.join(parts[:i + 1]))
    return out


def main():
    with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
        next(f)
        tset = set(int(l.split('\t', 1)[0], 16) for l in f)
    names = load_names()
    toks = [t for t in open(os.path.join(HERE, 'tokens.bin'), 'rb').read().split(b'\n') if t]
    print('tokens %d, targets %d, seeded names %d' % (len(toks), len(tset), len(names)), flush=True)

    slash = [t for t in toks if b'/' in t]
    bare = [t for t in toks if b'/' not in t]
    prefixes = set()
    prefixes.update(itertools.chain.from_iterable(ancestors(p) for p in names.values()))
    for r in ('ui', 'data', 'logic', '3d', 'dx11', 'Pc', 'webview_x64', 'scripts', 'res',
              'scene', 'mobile_maps', 'sound', 'texture', 'model'):
        prefixes.add(r)
    matched = set()                      # tokens whose hashed form already named an entry

    def save():
        with open(os.path.join(HERE, 'names_round.tsv'), 'w', encoding='utf-8') as o:
            o.write('hash\tpath\n')
            for k, v in sorted(names.items()):
                o.write('%s\t%s\n' % (k, v))

    for rnd in range(1, 9):
        pool = [t for t in toks if t not in matched]
        P = sorted(prefixes, key=lambda p: (p.count('/'), p))
        combos = len(pool) * len(P)
        print('round %d: %d tokens x %d prefixes = %.0fM combos' % (rnd, len(pool), len(P), combos / 1e6), flush=True)
        if combos > MAXCOMBO:
            print('  over budget, keeping slash tokens only', flush=True)
            pool = [t for t in pool if b'/' in t]
        t0 = time.time()
        last_save = t0
        added = []
        for pf in P:
            pb = (pf + '/').encode()
            for i in range(0, len(pool), CH):
                chunk = pool[i:i + CH]
                padded = [pb + t for t in chunk]
                L = min(max(len(t) for t in padded), MAXLEN)
                hs = batch_hash(padded, L)
                for t, h in zip(chunk, hs):
                    H = int(h)
                    if H not in tset:
                        continue
                    matched.add(t)
                    k = '%016x' % H
                    if k not in names:
                        names[k] = pf + '/' + t.decode('gbk', 'replace')
                        added.append(k)
                if time.time() - last_save > 60:
                    save()
                    last_save = time.time()
                    print('  %s +%d (elapsed %.0fs)' % (pf, len(added), time.time() - t0), flush=True)
            if time.time() - t0 > TIMEBOX:
                print('  round time-box reached', flush=True)
                break
        prefixes.update(d for k in added for d in ancestors(names[k]))
        save()
        print('  +%d names (total %d), %d prefixes now (%.0fs)' % (
            len(added), len(names), len(prefixes), time.time() - t0), flush=True)
        if not added:
            break


if __name__ == '__main__':
    main()
