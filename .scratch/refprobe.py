"""Do the asset containers reference each other by u64 path hash?

If a `.scene` / `.mesh` / config file stores child assets as u64 hashes, then every unnamed entry
can be attributed to the container that loads it, which recovers the real folder even when the
original file name is gone.  Probe: pull every little-endian u64 out of a sample of named assets
of each type and test membership in the pak index hash set.
"""
import collections
import os
import struct
import sys

HERE = r'D:\TLGL\.scratch'
sys.path.insert(0, HERE)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 25


def main():
    with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
        next(f)
        tset = set(int(l.split('\t', 1)[0], 16) for l in f)
    names = {}
    for fn in ('names_round.tsv', 'dicthits.txt', 'names_new.tsv', 'names.tsv'):
        p = os.path.join(HERE, fn)
        if os.path.isfile(p):
            for l in open(p, encoding='utf-8'):
                if l.startswith('hash\t'):
                    continue
                a = l.rstrip('\n').split('\t')
                if len(a) >= 2 and a[1]:
                    names[a[0]] = a[1]
    loc = {}
    SRC = os.path.join(HERE, 'out', 'all')
    for root, _d, fs in os.walk(SRC):
        for fn in fs:
            loc.setdefault(fn[:16].lower(), os.path.join(root, fn))
    by_ext = collections.defaultdict(list)
    for h, p in names.items():
        by_ext[os.path.splitext(p)[1].lower()].append(h)
    print('%-8s %6s %6s %8s %8s %10s' % ('ext', 'named', 'sampled', 'u64s', 'in-index', 'distinct-h'))
    import numpy as np
    tbl = np.fromiter(tset, dtype=np.uint64, count=len(tset))

    def scan(b):
        """u64 members of the index at 4-byte-aligned positions (structs are dword-aligned)."""
        base = np.frombuffer(b, dtype=np.uint8)
        L = (len(base) - 8) // 4 + 1
        if L <= 0:
            return []
        v = np.zeros(L, dtype=np.uint64)
        for k in range(8):
            v |= base[k::4][:L].astype(np.uint64) << np.uint64(8 * k)
        return v[np.isin(v, tbl)]

    for e, hs in sorted(by_ext.items(), key=lambda kv: -len(kv[1]))[:14]:
        tot = hits = 0
        found = set()
        for h in hs[:N]:
            p = loc.get(h)
            if not p:
                continue
            b = open(p, 'rb').read()
            for v in scan(b):
                hits += 1
                found.add('%016x' % int(v))
            tot += len(b)
        print('%-8s %6d %6d %9d %9d %10d' % (e, len(hs), min(N, len(hs)), tot, hits, len(found)))
        if found:
            print('           e.g.', [names.get(k) or '(unnamed)' for k in list(found)[:5]])


if __name__ == '__main__':
    main()
