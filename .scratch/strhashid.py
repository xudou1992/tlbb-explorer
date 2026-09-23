"""Which 32-bit function produces the JBCF string-table hash?

Candidate space is the two lanes of sub_14059F020 (xor-mix lane h1, sdbm x65599 lane h2)
plus crc32/FNV variants, fed the bare name, the name without extension, or a path form.
"""
import collections
import functools
import os
import sqlite3
import zlib

import jbcf
from jhash import M32, path_hash

HERE = r'D:\TLGL\.scratch'


def lanes(s, lower=True):
    b = s.replace('\\', '/').encode('utf-8')
    h1, h2 = 0x4E67C6A7, 0
    for c in b:
        if lower and 65 <= c <= 90:
            c += 32
        elif c == 92:
            c = 47
        h1 ^= (c + 32 * h1 + (h1 >> 2)) & M32
        h1 &= M32
        h2 = (c + 65599 * h2) & M32
    return h1, h2


def fnv(s):
    return functools.reduce(lambda x, c: ((x * 16777619) ^ c) & M32,
                            s.encode('latin1'), 2166136261)


def fnv_lower(s):
    return fnv(s.lower())


def elf(s):
    h = 0
    for c in s.encode('latin1'):
        h = (h << 4) + c
        g = h & 0xf0000000
        if g:
            h ^= g >> 24
        h &= ~g & M32
    return h


VARIANTS = {
    'lane1': lambda s: lanes(s)[0],
    'lane2': lambda s: lanes(s)[1],
    'lane1_raw': lambda s: lanes(s, False)[0],
    'lane2_raw': lambda s: lanes(s, False)[1],
    'lane1_noext': lambda s: lanes(os.path.splitext(s)[0])[0],
    'lane2_noext': lambda s: lanes(os.path.splitext(s)[0])[1],
    'crc32': lambda s: zlib.crc32(s.encode('latin1')) & M32,
    'crc32_noext': lambda s: zlib.crc32(os.path.splitext(s)[0].encode('latin1')) & M32,
    'fnv': fnv,
    'fnv_lower': fnv_lower,
    'elf': elf,
    'path_hash_low': lambda s: path_hash(s) & M32,
    'path_hash_hi': lambda s: path_hash(s) >> 32,
}


def main():
    con = sqlite3.connect('file:resources.db?mode=ro', uri=True)
    idx = {}
    for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
        d = os.path.join(HERE, 'out', 'all', pak)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                idx[fn[:16]] = os.path.join(d, fn)
    corpus = {}
    n = 0
    for h, in con.execute("select hash from resources where type='JBCF' and ext='.mtl'"):
        f = idx.get(h)
        if not f:
            continue
        try:
            _, _, _, strs = jbcf.parse(open(f, 'rb').read())
        except ValueError:
            continue
        for s, hv in strs:
            if s:
                corpus.setdefault(s, hv)
        n += 1
        if n >= 800:
            break
    print('corpus: %d distinct strings' % len(corpus))
    score = collections.Counter()
    for name, fn in VARIANTS.items():
        for ext in ('', '.tga', '.mtl'):
            for form in ('bare', 'path'):
                key = '%s|%s|%s' % (name, ext, form)
                good = 0
                for s, hv in corpus.items():
                    t = s + ext if ext else s
                    if form == 'path':
                        t = 'data/%s' % t
                    try:
                        if fn(t) == hv:
                            good += 1
                    except Exception:
                        pass
                if good:
                    score[key] = good
    print(score.most_common(10) or 'no variant matched')
    s0 = list(corpus)[0]
    print('sample %r -> %08x  lanes=%08x/%08x crc=%08x' %
          (s0, corpus[s0], lanes(s0)[0], lanes(s0)[1], zlib.crc32(s0.encode('latin1'))))


if __name__ == '__main__':
    main()
