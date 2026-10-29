"""pu_values.py — 每键值域总账:全库走一遍,按 (cls,fld) 统计载荷词的 int/f32 两口径。

输出 pu_values.json + 控制台摘要。
"""
import os
import struct
import json
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24
HARD = {0: 0, 7: 3}
TABLE = {tuple(int(x) for x in k.split(',')): v
         for k, v in json.load(open(os.path.join(HERE, 'pu_pw_table.json'))).items()}


def f32(w):
    return struct.unpack('<f', struct.pack('<I', w))[0]


def main():
    stats = defaultdict(lambda: {'n': 0, 'words': 0,
                                 'zero': 0, 'one': 0, 'smallint': 0,
                                 'floatish': 0, 'other': 0,
                                 'fmin': None, 'fmax': None,
                                 'imin': None, 'imax': None,
                                 'neg': 0})
    allf = []
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if fn.lower().endswith('.pu'):
                allf.append(os.path.join(dirpath, fn))
    nfiles = 0
    for fp in allf:
        raw = open(fp, 'rb').read()
        cnt = struct.unpack_from('<I', raw, 4)[0]
        tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
        pool = 8 + 8 * cnt
        p = pool
        for i in range(0, 2 * cnt, 2):
            p += tab[i]
        start = (p + 3) & ~3
        n = (len(raw) - start) // 4
        words = struct.unpack_from('<%dI' % n, raw, start)
        nfiles += 1
        q = 0
        while q < n:
            w = words[q]
            cls, fld = w >> 16, w & 0xffff
            pw = HARD[cls] if cls in HARD else TABLE[(cls, fld)]
            st = stats[(cls, fld)]
            st['n'] += 1
            for x in words[q + 1:q + 1 + pw]:
                st['words'] += 1
                fv = f32(x)
                if x == 0:
                    st['zero'] += 1
                elif x == 0x3f800000:
                    st['one'] += 1
                elif 0 < x < 100000:
                    st['smallint'] += 1
                    if st['imin'] is None or x < st['imin']:
                        st['imin'] = x
                    if st['imax'] is None or x > st['imax']:
                        st['imax'] = x
                elif 1e-3 <= abs(fv) <= 1e5:
                    st['floatish'] += 1
                    if fv < 0:
                        st['neg'] += 1
                    if st['fmin'] is None or fv < st['fmin']:
                        st['fmin'] = fv
                    if st['fmax'] is None or fv > st['fmax']:
                        st['fmax'] = fv
                else:
                    st['other'] += 1
            q += 1 + pw

    rows = []
    for k, st in sorted(stats.items()):
        w = st['words']
        if w == 0:
            continue
        kind = ('ZERO' if st['zero'] == w else
                'INT' if st['smallint'] + st['zero'] + st['one'] == w else
                'FLOAT' if st['floatish'] + st['zero'] + st['one'] == w else
                'MIXED')
        fr = '' if st['fmin'] is None else ' f32∈[%.4g,%.4g] neg=%d' % (st['fmin'], st['fmax'], st['neg'])
        ir = '' if st['imin'] is None else ' int∈[%d,%d]' % (st['imin'], st['imax'])
        rows.append({'cls': k[0], 'fld': k[1], 'occ': st['n'], 'pw': TABLE.get(k, HARD.get(k[0])),
                     'kind': kind, 'words': w,
                     'zero%': round(100.0 * st['zero'] / w, 1),
                     'one%': round(100.0 * st['one'] / w, 1),
                     'smallint%': round(100.0 * st['smallint'] / w, 1),
                     'floatish%': round(100.0 * st['floatish'] / w, 1),
                     'fmin': st['fmin'], 'fmax': st['fmax'],
                     'imin': st['imin'], 'imax': st['imax']})
    json.dump(rows, open(os.path.join(HERE, 'pu_values.json'), 'w'), indent=1)
    print('files %d, keys %d' % (nfiles, len(rows)))
    bykind = Counter(r['kind'] for r in rows)
    print('kinds:', dict(bykind))
    print('\nFLOAT keys (occ>=100):')
    for r in rows:
        if r['kind'] == 'FLOAT' and r['occ'] >= 100:
            print('  (%3d,%3d) occ=%-6d pw=%d z%5.1f%% o%5.1f%% f%5.1f%% f32∈[%8.4g,%8.4g]'
                  % (r['cls'], r['fld'], r['occ'], r['pw'], r['zero%'], r['one%'],
                     r['floatish%'], r['fmin'], r['fmax']))
    print('\nINT keys (occ>=100):')
    for r in rows:
        if r['kind'] == 'INT' and r['occ'] >= 100:
            print('  (%3d,%3d) occ=%-6d pw=%d z%5.1f%% o%5.1f%% i%5.1f%% int∈[%s,%s]'
                  % (r['cls'], r['fld'], r['occ'], r['pw'], r['zero%'], r['one%'],
                     r['smallint%'], r['imin'], r['imax']))
    print('\nMIXED keys (occ>=100):')
    for r in rows:
        if r['kind'] == 'MIXED' and r['occ'] >= 100:
            print('  (%3d,%3d) occ=%-6d pw=%d z%5.1f%% o%5.1f%% i%5.1f%% f%5.1f%%'
                  % (r['cls'], r['fld'], r['occ'], r['pw'], r['zero%'], r['one%'],
                     r['smallint%'], r['floatish%']))


if __name__ == '__main__':
    main()
