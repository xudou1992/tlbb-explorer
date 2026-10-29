"""pu_token5.py — 崩溃驱动修复:失败文件 DP 反推挂点 key 的 pw,迭代到全量收敛。"""
import os
import struct
import json
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24
MAXPW = 20


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
    return {p: [pw for pw in edges[p] if to_end[p + 1 + pw]]
            for p in range(n) if reach[p] and to_end[p]}


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

    table = {tuple(int(x) for x in k.split(',')): v
             for k, v in json.load(open(os.path.join(HERE, 'pu_pw_table.json'))).items()}
    for (c, f) in list(table):          # 先吸收 cls7=3 的已知修补
        if table[(c, f)] == 7:
            pass
    for k in list(table):
        if k[0] == 7:
            table[k] = 3

    for it in range(12):
        votes = defaultdict(Counter)
        n_ok = 0
        fails = []
        for fp, (names, words) in data.items():
            ok, pos, recs = table_walk(words, table)
            if ok:
                n_ok += 1
                continue
            fails.append(fp)
            live = live_edges(words)
            # 崩溃点缺表项 → 直接投 DP 可行集
            if pos in live and live[pos]:
                w = words[pos]
                k = (w >> 16, w & 0xffff)
                if table.get(k) is None:
                    for pw in live[pos]:
                        votes[k][pw] += 1
            # 前缀上表 pw 与该文件 DP 可行集矛盾 → 投可行集(矛盾可能早于崩溃点)
            for (p, cls, fld, t) in recs:
                lv = live.get(p)
                if lv and t not in lv:
                    for pw in lv:
                        votes[(cls, fld)][pw] += 1
        changed = 0
        for k, c in votes.items():
            best = c.most_common(1)[0][0]
            if table.get(k) != best:
                table[k] = best
                changed += 1
        print('iter %d: ok %d/%d fails %d changed %d' % (it, n_ok, len(data), len(fails), changed))
        json.dump({'%d,%d' % k: v for k, v in sorted(table.items())},
                  open(os.path.join(HERE, 'pu_pw_table.json'), 'w'), indent=1)
        if changed == 0 or not fails:
            break

    # 终验
    n_ok = 0
    fails = []
    for fp, (names, words) in data.items():
        ok, pos, _ = table_walk(words, table)
        if ok:
            n_ok += 1
        else:
            fails.append((os.path.relpath(fp, ROOT), len(words), pos))
    print('FINAL ok %d/%d (%.2f%%)' % (n_ok, len(data), 100.0 * n_ok / len(data)))
    with open(os.path.join(HERE, 'pu_fail_list.txt'), 'w', encoding='utf-8') as fo:
        for f in sorted(fails):
            fo.write('%s\t%d\t%d\n' % f)
    print('fails %d -> pu_fail_list.txt' % len(fails))


if __name__ == '__main__':
    main()
