"""Parse the JRPC/JBCF resource-path tables and hash-match every embedded path.

`ResourcePath.cfg` is the engine's own path table: length-prefixed virtual paths (the byte before
each path is its length), interleaved with a u32 offset array.  Extracting these gives real names
in bulk instead of guessing tokens.
"""
import collections
import os
import re
import sys

sys.path.insert(0, r'D:\TLGL\.scratch')
from mine2 import batch_hash

HERE = r'D:\TLGL\.scratch'
LEGAL = set(range(0x20, 0x7f)) - set(b'"\'<>|?*(){}[],;:')
FILES = sys.argv[1:] or [r'D:\TLGL\.scratch\out\all\data_1\4b761249ad5d605c.bin',
                         r'D:\TLGL\.scratch\out\all\data\4b761249ad5d605c.bin']


def load_index():
    with open(os.path.join(HERE, 'index.tsv'), encoding='utf-8') as f:
        next(f)
        return set(int(l.split('\t', 1)[0], 16) for l in f)


def load_names():
    names = {}
    for fn in ('names_gen.tsv', 'names_round.tsv', 'dicthits.txt', 'names_new.tsv', 'names.tsv'):
        p = os.path.join(HERE, fn)
        if os.path.isfile(p):
            for l in open(p, encoding='utf-8'):
                if l.startswith('hash\t'):
                    continue
                a = l.rstrip('\n').split('\t')
                if len(a) >= 2 and a[1]:
                    names[a[0]] = a[1]
    return names


def records(d):
    """Yield length-prefixed path records: byte L followed by L path-legal bytes containing '/'."""
    out = []
    i = 0
    n = len(d)
    while i < n - 8:
        L = d[i]
        if 6 <= L <= 200:
            s = d[i + 1:i + 1 + L]
            if len(s) == L and b'/' in s and not (set(s) - LEGAL) and b'  ' not in s:
                out.append(s)
                i += 1 + L
                continue
        i += 1
    return out


def main():
    tset = load_index()
    names = load_names()
    print('index targets %d, already named %d' % (len(tset), len(names)), flush=True)
    allpaths = []
    for f in FILES:
        d = open(f, 'rb').read()
        r = records(d)
        print('%s: %d bytes -> %d records' % (os.path.basename(f), len(d), len(r)), flush=True)
        allpaths += r
    uniq = list(dict.fromkeys(allpaths))
    print('unique embedded paths: %d' % len(uniq), flush=True)
    L = min(max(len(p) for p in uniq), 200)
    new = {}
    for i in range(0, len(uniq), 300000):
        chunk = uniq[i:i + 300000]
        hs = batch_hash([p[:L] for p in chunk], L)
        for p, h in zip(chunk, hs):
            k = '%016x' % int(h)
            if k in tset and k not in names:
                names[k] = p.decode('ascii', 'replace')
                new[k] = names[k]
    with open(os.path.join(HERE, 'names_jrpc.tsv'), 'w', encoding='utf-8') as o:
        o.write('hash\tpath\n')
        for k, v in sorted(names.items()):
            o.write('%s\t%s\n' % (k, v))
    print('NEW %d, total %d' % (len(new), len(names)), flush=True)
    print('sample:')
    for k in list(new)[:15]:
        print('   ', names[k])
    print('top dirs:', collections.Counter('/'.join(v.split('/')[:-1]) for v in new.values()).most_common(15))
    print('exts:', collections.Counter(os.path.splitext(v)[1].lower() for v in new.values()).most_common(20))


if __name__ == '__main__':
    main()
