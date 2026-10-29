"""pu_failstat.py — 统计失败文件挂在哪个 (cls,fld);测试类内统一 pw 的修补效果。"""
import os
import struct
import json
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24


def load_words(path):
    raw = open(path, 'rb').read()
    cnt = struct.unpack_from('<I', raw, 4)[0]
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pool = 8 + 8 * cnt
    p = pool
    names = []
    for i in range(0, 2 * cnt, 2):
        ln = tab[i]
        names.append(raw[p:p + ln])
        p += ln
    start = (p + 3) & ~3
    n = (len(raw) - start) // 4
    return names, struct.unpack_from('<%dI' % n, raw, start)


def table_walk(words, table):
    n = len(words)
    p = 0
    while p < n:
        w = words[p]
        cls, fld = w >> 16, w & 0xffff
        if cls > MAXCLS:
            return False, p, (cls, fld), 'cls-overflow'
        pw = table.get((cls, fld))
        if pw is None:
            return False, p, (cls, fld), 'missing'
        p += 1 + pw
    return True, p, None, None


def main():
    table = {tuple(int(x) for x in k.split(',')): v
             for k, v in json.load(open(os.path.join(HERE, 'pu_pw_table.json'))).items()}
    # 修补:cls=7 类内统一 pw=3
    patch = dict(table)
    for (cls, fld) in list(patch):
        if cls == 7:
            patch[(cls, fld)] = 3

    allf = []
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if fn.lower().endswith('.pu'):
                allf.append(os.path.join(dirpath, fn))
    stop_keys = Counter()
    stop_detail = Counter()
    n_ok = n_ok2 = 0
    fails2 = []
    for fp in allf:
        _, words = load_words(fp)
        ok, pos, key, why = table_walk(words, table)
        if ok:
            n_ok += 1
        else:
            stop_keys[str(key)] += 1
            stop_detail[why] += 1
        ok2, pos2, key2, why2 = table_walk(words, patch)
        if ok2:
            n_ok2 += 1
        else:
            fails2.append((os.path.relpath(fp, ROOT), pos2, key2, why2))
    print('orig ok %d/%d   patched(cls7=3) ok %d/%d' % (n_ok, len(allf), n_ok2, len(allf)))
    print('stop reasons:', dict(stop_detail))
    print('\ntop stop keys (orig table):')
    for k, c in stop_keys.most_common(25):
        print('  %s  x%d' % (k, c))
    print('\npatched fails: %d' % len(fails2))
    k2 = Counter(str(f[2]) for f in fails2)
    for k, c in k2.most_common(20):
        print('  %s x%d' % (k, c))
    with open(os.path.join(HERE, 'pu_fail2.txt'), 'w', encoding='utf-8') as fo:
        for f in sorted(fails2):
            fo.write('%s\t%d\t%s\t%s\n' % f)


if __name__ == '__main__':
    main()
