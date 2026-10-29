"""pu_token3.py — 稳定版:表固定点 + 多峰检测。

每轮:
  1) 用当前表确定性走全部样本;走通的记录给高权重证据(×8)
  2) 走不通的文件用自由 DP;DP 边给权重 1,用于补缺与纠错
  3) 每键取加权多数;输出多峰键(可能是变长记录)
最后冻结表全量验证。
"""
import os
import struct
import json
import random
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
    for ln, _ in [(tab[i], tab[i + 1]) for i in range(0, 2 * cnt, 2)]:
        names.append(raw[p:p + ln])
        p += ln
    start = (p + 3) & ~3
    n = (len(raw) - start) // 4
    return names, struct.unpack_from('<%dI' % n, raw, start)


def live_edges(words):
    """自由 DP:返回 {pos: [pw]},只留 0 可达且通向终点的边。"""
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
    random.seed(20261005)
    sample = random.sample(allf, 1200)
    sample = list(dict.fromkeys(sample))
    data = {}
    for fp in sample:
        data[fp] = load_words(fp)

    table = {}
    hist = []
    for it in range(15):
        support = defaultdict(Counter)
        n_ok = 0
        for fp, (names, words) in data.items():
            ok, pos, recs = table_walk(words, table)
            if ok:
                n_ok += 1
                for _, cls, fld, pw in recs:
                    support[(cls, fld)][pw] += OK_W
            else:
                live = live_edges(words)
                for p, pws in live.items():
                    w = words[p]
                    for pw in pws:
                        support[(w >> 16, w & 0xffff)][pw] += 1
        newtable = {k: c.most_common(1)[0][0] for k, c in support.items()}
        diff = sum(1 for k in set(newtable) | set(table)
                   if newtable.get(k) != table.get(k))
        multi = {k: dict(c) for k, c in support.items() if len(c) > 1}
        hist.append((n_ok, len(newtable), diff))
        print('iter %2d: ok %4d/%d  entries %3d  diff %3d  multimodal %d'
              % (it, n_ok, len(data), len(newtable), diff, len(multi)))
        table = newtable
        if diff == 0:
            break
    json.dump({'%d,%d' % k: v for k, v in sorted(table.items())},
              open(os.path.join(HERE, 'pu_pw_table.json'), 'w'), indent=1)

    # 多峰键(加权后仍然两峰以上的)
    print('\nmultimodal keys (top):')
    for k, c in sorted(multi.items(), key=lambda kv: -sum(kv[1].values()))[:30]:
        print('  cls=%2d fld=%3d  %s' % (k[0], k[1], dict(c)))

    # 冻结表全量验证
    n_ok_all = 0
    fail_all = []
    for fp in allf:
        _, words = load_words(fp)
        ok, pos, _ = table_walk(words, table)
        if ok:
            n_ok_all += 1
        else:
            fail_all.append((os.path.relpath(fp, ROOT), len(words), pos))
    print('\nFULL: %d/%d (%.2f%%)' % (n_ok_all, len(allf), 100.0 * n_ok_all / len(allf)))
    for f in fail_all[:20]:
        print('  FAIL', f)


if __name__ == '__main__':
    main()
