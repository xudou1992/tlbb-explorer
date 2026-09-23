"""Bootstrap naming, fast version.

Stage 1: scan every extracted asset for path-shaped tokens (tight charset, must contain '/'),
         dedupe globally into .scratch/tokens.bin.
Stage 2: batch-hash the unique tokens with numpy (port of sub_14059F020), match against index.tsv.
Read-only over out/all.
"""
import os
import re
import sys
import time

import numpy as np

HERE = r'D:\TLGL\.scratch'
ROOT = os.path.join(HERE, 'out', 'all')
MAXLEN = 160
BARECAP = 4000000
NC = br'A-Za-z0-9_\-.\\\x81-\xfe'
ML = str(MAXLEN).encode()
# any "dir/leaf.ext" path; extension is 1-8 letters, no whitelist
slashre = re.compile(b'[' + NC + b']{2,' + ML + b'}/[' + NC + b']{0,' + ML + b'}\\.[A-Za-z0-9]{1,8}(?![A-Za-z0-9])')
# bare "leaf.ext" (ASCII only, keeps binary junk down)
barere = re.compile(b'[A-Za-z0-9_+\\-]{2,60}\\.[A-Za-z]{2,5}(?![A-Za-z0-9])')


def batch_hash(tokens, lens_max):
    """np.uint64 array of sub_14059F020 hashes for a list of byte tokens."""
    n = len(tokens)
    buf = b''.join(t[:lens_max].ljust(lens_max, b'\x00') for t in tokens)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(n, lens_max)
    lens = np.fromiter((min(len(t), lens_max) for t in tokens), dtype=np.int32, count=n)
    h1 = np.full(n, 0x4E67C6A7, dtype=np.uint32)
    h2 = np.zeros(n, dtype=np.uint32)
    for j in range(lens_max):
        live = lens > j
        if not live.any():
            continue
        c = arr[:, j].astype(np.uint32)
        c = np.where((c >= 65) & (c <= 90), c + np.uint32(32), c)
        c = np.where(c == 92, np.uint32(47), c)
        t = (c + (h1 << np.uint32(5)) + (h1 >> np.uint32(2))).view(np.uint32)
        h1 = np.where(live, h1 ^ t, h1)
        h2 = np.where(live, (c + h2 * np.uint32(65599)).view(np.uint32), h2)
    return (h1.astype(np.uint64) | (h2.astype(np.uint64) << np.uint64(32)))


def stage1():
    toks = set()
    add = toks.add
    nfiles = 0
    nbytes = 0
    t0 = time.time()
    for stem in sorted(os.listdir(ROOT)):
        base = os.path.join(ROOT, stem)
        if not os.path.isdir(base):
            continue
        for root, _d, fs in os.walk(base):
            for fn in fs:
                p = os.path.join(root, fn)
                try:
                    b = open(p, 'rb').read()
                except OSError:
                    continue
                nfiles += 1
                nbytes += len(b)
                for m in slashre.finditer(b):
                    add(m.group())
                if len(toks) < BARECAP:
                    for m in barere.finditer(b):
                        add(m.group())
                if nfiles % 20000 == 0:
                    print('  %d files %.2f GB %d tokens %.0fs' % (
                        nfiles, nbytes / 1e9, len(toks), time.time() - t0), flush=True)
        print('stage1 %s: %d files %.2f GB, %d tokens (%.0fs)' % (
            stem, nfiles, nbytes / 1e9, len(toks), time.time() - t0), flush=True)
    with open(os.path.join(HERE, 'tokens.bin'), 'wb') as o:
        o.write(b'\n'.join(sorted(toks)))
    print('stage1 done: %d files, %.2f GB, %d unique tokens' % (
        nfiles, nbytes / 1e9, len(toks)), flush=True)


def stage2():
    with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
        next(f)
        tset = set(int(l.split('\t', 1)[0], 16) for l in f)
    toks = open(os.path.join(HERE, 'tokens.bin'), 'rb').read().split(b'\n')
    print('tokens: %d, targets: %d' % (len(toks), len(tset)), flush=True)
    seeds = {}
    if os.path.isfile(os.path.join(HERE, 'names.tsv')):
        with open(os.path.join(HERE, 'names.tsv'), encoding='utf-8') as f:
            next(f)
            for l in f:
                a = l.rstrip('\n').split('\t')
                seeds[a[0]] = a[1]
    hits = {}
    t0 = time.time()
    CH = 300000
    for i in range(0, len(toks), CH):
        chunk = [t for t in toks[i:i + CH] if t]
        if not chunk:
            continue
        L = min(max(len(t) for t in chunk), MAXLEN)
        hs = batch_hash(chunk, L)
        for t, h in zip(chunk, hs):
            H = int(h)
            if H in tset:
                k = '%016x' % H
                if k in hits:
                    continue
                hits[k] = t.decode('gbk', 'replace')
        print('stage2 %d/%d -> %d hits (%.0fs)' % (
            i + len(chunk), len(toks), len(hits), time.time() - t0), flush=True)
    with open(os.path.join(HERE, 'names_new.tsv'), 'w', encoding='utf-8') as o:
        o.write('hash\tpath\n')
        for k, v in sorted(hits.items()):
            o.write('%s\t%s\n' % (k, v))
    print('new names: %d (seeds %d, targets %d)' % (len(hits), len(seeds), len(tset)))


if __name__ == '__main__':
    if '1' in sys.argv[1:]:
        stage1()
    stage2()
