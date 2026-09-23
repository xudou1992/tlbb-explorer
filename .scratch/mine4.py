"""Stage 4: directory-string x filename cross product.

Config/Lua/UI code frequently stores a folder as its own literal ("ui/icon/skill/") and appends
the file name at runtime, so the full path never appears verbatim in any asset.  Mine every
folder-looking literal from the extracted tree and hash `folder + token` for all filename
tokens already collected; a 64-bit index hit proves the concatenation.
"""
import os
import re
import sys
import time
from collections import Counter

sys.path.insert(0, r'D:\TLGL\.scratch')
from mine2 import batch_hash

HERE = r'D:\TLGL\.scratch'
ROOT = os.path.join(HERE, 'out', 'all')
CH = 300000
MAXLEN = 200
TIMEBOX = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
NC = br'A-Za-z0-9_\-.\\\x81-\xfe'
DIRRE = re.compile(b'(?:[A-Za-z0-9_+\\-]{1,60}/){1,12}[A-Za-z0-9_+\\-]{0,60}/(?![A-Za-z0-9])')


def mine_dirs():
    """Scan the extracted tree once; count folder literals."""
    cnt = Counter()
    n = 0
    for stem in sorted(os.listdir(ROOT)):
        base = os.path.join(ROOT, stem)
        if not os.path.isdir(base):
            continue
        for root, _d, fs in os.walk(base):
            for fn in fs:
                p = os.path.join(root, fn)
                try:
                    if os.path.getsize(p) > 60 * 1024 * 1024:
                        continue
                    b = open(p, 'rb').read()
                except OSError:
                    continue
                n += 1
                cnt.update(m.group()[:-1] for m in DIRRE.finditer(b))
                if n % 20000 == 0:
                    print('  scanned %d files, %d distinct dirs (%ds)' % (
                        n, len(cnt), time.time() - T0), flush=True)
    print('dir mining: %d files -> %d distinct folder literals' % (n, len(cnt)), flush=True)
    return cnt


def load():
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
    toks = [t for t in open(os.path.join(HERE, 'tokens.bin'), 'rb').read().split(b'\n') if t]
    with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
        next(f)
        tset = set(int(l.split('\t', 1)[0], 16) for l in f)
    return names, toks, tset


T0 = time.time()


def main():
    names, toks, tset = load()
    print('seeded names %d, tokens %d, targets %d' % (len(names), len(toks), len(tset)), flush=True)
    dirs = mine_dirs()
    # keep literals that look like real mount-relative folders
    cand = [d for d, c in dirs.items() if len(d) >= 4 and b'\x00' not in d]
    cand.sort(key=lambda d: (-dirs[d], len(d)))
    print('candidate folders: %d (top freq %d)' % (len(cand), dirs[cand[0]]), flush=True)
    pool = toks
    t0 = time.time()
    added = 0
    out = os.path.join(HERE, 'names_dir.tsv')
    for i, d in enumerate(cand):
        pb = d.replace(b'\\', b'/') + b'/'
        for j in range(0, len(pool), CH):
            chunk = pool[j:j + CH]
            padded = [pb + t for t in chunk]
            L = min(max(len(t) for t in padded), MAXLEN)
            hs = batch_hash(padded, L)
            for t, h in zip(chunk, hs):
                k = '%016x' % int(h)
                if k in tset and k not in names:
                    names[k] = pb.decode('gbk', 'replace') + t.decode('gbk', 'replace')
                    added += 1
        if (i + 1) % 200 == 0 or time.time() - t0 > 60:
            with open(out, 'w', encoding='utf-8') as o:
                o.write('hash\tpath\n')
                for k, v in sorted(names.items()):
                    o.write('%s\t%s\n' % (k, v))
            t0 = time.time()
            print('  %d/%d folders, +%d names (total %d, %.0fs)' % (
                i + 1, len(cand), added, len(names), time.time() - T0), flush=True)
        if time.time() - T0 > TIMEBOX:
            print('  time box', flush=True)
            break
    print('done: +%d names, total %d (%.0fs)' % (added, len(names), time.time() - T0), flush=True)


if __name__ == '__main__':
    main()
