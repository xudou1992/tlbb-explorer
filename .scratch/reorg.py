"""Materialise named assets into a browsable tree.

The unpacked tree names files `<hash>.<guessed-ext>`; the recovered name map gives real paths.
Hardlink (same volume, no extra space) each named entry into out/tree/<real path>.
"""
import os
import sys

SRC = r'D:\TLGL\.scratch\out\all'
DST = r'D:\TLGL\.scratch\out\tree'


def load_names():
    names = {}
    for fn in ('names_drain.tsv', 'names_jrpc.tsv', 'names_round.tsv', 'dicthits.txt', 'names_new.tsv', 'names.tsv'):
        p = os.path.join(r'D:\TLGL\.scratch', fn)
        if not os.path.isfile(p):
            continue
        for l in open(p, encoding='utf-8'):
            if l.startswith('hash\t'):
                continue
            a = l.rstrip('\n').split('\t')
            if len(a) >= 2 and a[1]:
                names[a[0]] = a[1].replace('\\', '/')
    return names


def main():
    names = load_names()
    # a hash may live in several paks; keep the largest copy (latest generation wins upstream)
    by_hash = {}
    for root, _d, fs in os.walk(SRC):
        for fn in fs:
            if not fn[:16].isalnum():
                continue
            h = fn[:16].lower()
            if h not in names:
                continue
            p = os.path.join(root, fn)
            sz = os.path.getsize(p)
            if h not in by_hash or sz > by_hash[h][1]:
                by_hash[h] = (p, sz)
    link = mkdir = dup = 0
    for h, (src, _sz) in sorted(by_hash.items()):
        rel = names[h]
        dest = os.path.normpath(os.path.join(DST, rel))
        if not dest.startswith(os.path.abspath(DST)):
            dup += 1
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            dest += '.dup'
            dup += 1
        try:
            os.link(src, dest)
            link += 1
        except OSError:
            mkdir += 1
    print('named hashes %d, linked from %d files, fallback-copy %d, dup-names %d' % (
        len(names), link, mkdir, dup))
    print('tree at', DST)


if __name__ == '__main__':
    main()
