"""pu_token4.py — 全量 7806 作训练集跑到不动点;输出表 + 剩余失败清单。"""
import os
import struct
import json
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24
MAXPW = 20
OK_W = 8


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


def live_edges(words):
    n = len(words)
    edges = defaultdict(list)
    for p in range(n):
        if words[p] >> 16 > MAXCLS:
            continue
        for pw in range(MAXPW + 1):
            q = p + 1 + pw
            if q > n:
                break
            if q == n or (words[q] >> 16) <= MAXCLS:
                edges[p].append(pw)
    reach = [False] * (n + 1)
    reach[0] = True
    changed = True
    while changed:
        changed = False
        for p in range(n):
            if not reach[p]:
                continue
            for pw in edges[p]:
                q = p + 1 + pw
                if not reach[q]:
                    reach[q] = True
                    changed = True
    to_end = [False] * (n + 1)
    to_end[n] = True
    for p in range(n - 1, -1, -1):
        if reach[p] and any(to_end[p + 1 + pw] for pw in edges[p]):
            to_end[p] = True
    live = defaultdict(list)
    for p in range(n):
        if reach[p] and to_end[p]:
            for pw in edges[p]:
                if to_end[p + 1 + pw]:
                    live[p].append(pw)
    return live


def table_walk(words, table):
    n = len(words)
    p = 0
    recs = []
    while p < n:
        w = words[p]
        cls, fld = w >> 16, w & 0xffff
        if cls > MAXCLS:
            return None, p, recs
        pw = table.get((cls, fld))
        if pw is None:
            return None, p, recs
        recs.append((p, cls, fld, pw))
        p += 1 + pw
    return True, p, recs


def main():
    allf = []
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if fn.lower().endswith('.pu'):
                allf.append(os.path.join(dirpath, fn))
    allf.sort()
    data = {}
    for fp in allf:
        data[fp] = load_words(fp)

    table = json.load(open(os.path.join(HERE, 'pu_pw_table.json')))
    table = {tuple(int(x) for x in k.split(',')): v for k, v in table.items()}

    for it in range(10):
        support = defaultdict(Counter)
        n_ok = 0
        fails = []
        for fp, (names, words) in data.items():
            ok, pos, recs = table_walk(words, table)
            if ok:
                n_ok += 1
                for _, cls, fld, pw in recs:
                    support[(cls, fld)][pw] += OK_W
            else:
                fails.append((fp, pos))
                live = live_edges(words)
                for p, pws in live.items():
                    w = words[p]
                    for pw in pws:
                        support[(w >> 16, w & 0xffff)][pw] += 1
        newtable = {k: c.most_common(1)[0][0] for k, c in support.items()}
        diff = sum(1 for k in set(newtable) | set(table)
                   if newtable.get(k) != table.get(k))
        print('iter %d: ok %d/%d entries %d diff %d fails %d'
              % (it, n_ok, len(data), len(newtable), diff, len(fails)))
        table = newtable
        json.dump({'%d,%d' % k: v for k, v in sorted(table.items())},
                  open(os.path.join(HERE, 'pu_pw_table.json'), 'w'), indent=1)
        if diff == 0:
            break

    # 最终失败清单
    n_ok = 0
    fail = []
    for fp, (names, words) in data.items():
        ok, pos, _ = table_walk(words, table)
        if ok:
            n_ok += 1
        else:
            fail.append((os.path.relpath(fp, ROOT), len(words), pos))
    print('FINAL ok %d/%d (%.2f%%)' % (n_ok, len(data), 100.0 * n_ok / len(data)))
    # 失败按失败位置词数聚类
    bypos = Counter(f[2] for f in fail)
    print('fail-position histogram (top):', bypos.most_common(12))
    with open(os.path.join(HERE, 'pu_fail_list.txt'), 'w', encoding='utf-8') as fo:
        for f in sorted(fail):
            fo.write('%s\t%d\t%d\n' % f)
    print('fail list -> pu_fail_list.txt (%d)' % len(fail))


if __name__ == '__main__':
    main()
