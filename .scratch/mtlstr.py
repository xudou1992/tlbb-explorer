"""Do JBCF .mtl / .mdl / .ske bodies carry plaintext asset references?

This is the mesh->mtl->texture question restated: if the material containers name
their textures in the clear, the dependency graph comes from the files themselves
instead of from filename guessing.
"""
import collections
import os
import re
import sqlite3

HERE = r'D:\TLGL\.scratch'
RUN = re.compile(rb'[\x20-\x7e]{4,}')


def main():
    con = sqlite3.connect('file:%s?mode=ro' % os.path.join(HERE, 'resources.db'), uri=True)
    idx = {}
    for pak in os.listdir(os.path.join(HERE, 'out', 'all')):
        d = os.path.join(HERE, 'out', 'all', pak)
        if os.path.isdir(d):
            for fn in os.listdir(d):
                idx[fn[:16]] = os.path.join(d, fn)

    for ext in ('mtl', 'mdl', 'ske', 'sfl', ''):
        rows = con.execute(
            "select hash, original, path from resources where type='JBCF' and ext=?",
            ('.' + ext,)).fetchall()
        ext = ext or '(unnamed)'
        withslash = 0
        dotext = collections.Counter()
        tot = collections.Counter()
        ex = []
        for h, orig, path in rows:
            f = idx.get(h)
            if not f:
                continue
            raw = open(f, 'rb').read()
            runs = [r.decode('latin1') for r in RUN.findall(raw) if len(r) > 4]
            hit = [r for r in runs if '/' in r or '\\' in r]
            if hit:
                withslash += 1
                if len(ex) < 6:
                    ex.append((path[:48], hit[:6]))
            for r in runs:
                e = os.path.splitext(r)[1].lower()
                if e and len(e) <= 6:
                    dotext[e] += 1
            for r in runs:
                tot[r] += 1
        print('\n=== %s  n=%d  with slash-ish runs: %d ===' % (ext, len(rows), withslash))
        print('  ext-looking runs:', dotext.most_common(8))
        print('  top runs:', [(k, v) for k, v in tot.most_common(12)])
        for p, h in ex:
            print('  -', p, h)


if __name__ == '__main__':
    main()
