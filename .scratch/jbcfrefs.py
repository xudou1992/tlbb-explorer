"""What do JBCF string tables reference, and how much of it resolves?

For every JBCF resource, pull the strtab strings, bucket them by suffix, and try to
resolve each one against the named corpus (exact basename, then same-directory
basename).  This is the evidence for turning filenames-into-edges into real edges.
"""
import collections
import json
import os
import sqlite3

import jbcf

HERE = r'D:\TLGL\.scratch'


def main():
    con = sqlite3.connect('file:resources.db?mode=ro', uri=True)
    idx = {}
    for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
        d = os.path.join(HERE, 'out', 'all', pak)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                idx[fn[:16]] = os.path.join(d, fn)

    named = {}
    for h, path, typ in con.execute('select hash, path, type from resources where path is not null'):
        named.setdefault(os.path.basename(path).lower(), []).append((h, path, typ))
    by_dir = {}
    for h, path, typ in con.execute('select hash, path, type from resources where path is not null'):
        p = path.lower()
        by_dir.setdefault(os.path.dirname(p), {})[os.path.basename(p)] = h

    bucket = collections.defaultdict(collections.Counter)
    res = collections.defaultdict(lambda: [0, 0])
    per_ext = collections.defaultdict(collections.Counter)
    out = open(os.path.join(HERE, 'jbcf_refs.txt'), 'w', encoding='utf-8')
    edges = open(os.path.join(HERE, 'jbcf_edges.tsv'), 'w', encoding='utf-8')

    for h, ext, path in con.execute(
            "select hash, ext, path from resources where type='JBCF' and path is not null"):
        f = idx.get(h)
        if not f:
            continue
        try:
            _, _, _, strs = jbcf.parse(open(f, 'rb').read())
        except ValueError:
            continue
        for s, _ in strs:
            if not s:
                continue
            low = s.lower()
            e = os.path.splitext(low)[1]
            k = e if e else ('slash' if '/' in low or '\\' in low else 'word')
            per_ext[ext][k] += 1
            if e in ('.tga', '.dds', '.png', '.mtl', '.mesh', '.mdl', '.ani', '.ske', '.scene'):
                cands = named.get(os.path.basename(low))
                d = by_dir.get(os.path.dirname(path.lower()), {})
                tgt = d.get(low) or d.get(low + e.replace(e, ''))
                if not cands and not tgt:
                    res[k][1] += 1
                    continue
                res[k][0] += 1
                tgt = tgt or (cands[0][0] if len(cands) == 1 else None)
                if tgt:
                    edges.write('%s\t%s\t%s\t%s\n' % (h, path, k[1:], tgt))
                elif e == '.mtl':
                    edges.write('%s\t%s\t%s\t%s\n' % (h, path, 'ambig', ''))
            bucket[k][len(s)] += 1
    print('string suffix mix per JBCF ext:', file=out)
    for e, c in per_ext.items():
        print('  %-6s %s' % (e, c.most_common(9)), file=out)
    print('\nresolution (kind -> [resolved, unresolved]):', file=out)
    for k, v in sorted(res.items(), key=lambda x: -sum(x[1])):
        print('  %-7s %6d / %6d' % (k, v[0], v[1]), file=out)
    out.close()
    edges.close()
    print(open(os.path.join(HERE, 'jbcf_refs.txt'), encoding='utf-8').read())
    print('edge lines:', sum(1 for _ in open(os.path.join(HERE, 'jbcf_edges.tsv'), encoding='utf-8')))


if __name__ == '__main__':
    main()
