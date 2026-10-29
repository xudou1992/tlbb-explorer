"""pu_token2.py — DP + 不动点迭代求 (cls,fld)->pw 表,再确定性全量验证。

记录 = u32 key(cls<<16|fld) + pw(cls,fld) 个 u32 词。
每份文件必须从参数区起点恰好走到终点。
"""
import os
import struct
import json
import random
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24
MAXPW = 16


def load_words(path):
    raw = open(path, 'rb').read()
    cnt = struct.unpack_from('<I', raw, 4)[0]
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pairs = [(tab[i], tab[i + 1]) for i in range(0, 2 * cnt, 2)]
    pool = 8 + 8 * cnt
    p = pool
    names = []
    for ln, _ in pairs:
        names.append(raw[p:p + ln])
        p += ln
    start = (p + 3) & ~3
    n = (len(raw) - start) // 4
    words = struct.unpack_from('<%dI' % n, raw, start)
    return names, words


def feasible_records(words):
    """所有从 0 可达的 (pos, pw) 记录边。返回 {pos: [(pw)...]}, 只含能继续走或正好到终点的。"""
    n = len(words)
    reach = [False] * (n + 1)
    reach[0] = True
    edges = defaultdict(list)  # pos -> [pw]
    # 边收集与 reach 无关:位置 p 能当 key 当且仅当 cls<=MAXCLS(位置局部判据)
    for p in range(n):
        cls = words[p] >> 16
        if cls > MAXCLS:
            continue
        for pw in range(MAXPW + 1):
            q = p + 1 + pw
            if q > n:
                break
            if q == n or (words[q] >> 16) <= MAXCLS or q == n:
                edges[p].append(pw)
    # 传播 reach
    changed = True
    while changed:
        changed = False
        for p in range(n):
            if not reach[p]:
                continue
            for pw in edges[p]:
                q = p + 1 + pw
                if q <= n and not reach[q]:
                    reach[q] = True
                    changed = True
    # 只保留通向终点的边(反向可达)
    to_end = [False] * (n + 1)
    to_end[n] = True
    for p in range(n - 1, -1, -1):
        if not reach[p]:
            continue
        ok = False
        for pw in edges[p]:
            if to_end[p + 1 + pw]:
                ok = True
                break
        to_end[p] = ok
    live = defaultdict(list)
    for p in range(n):
        if reach[p] and to_end[p]:
            for pw in edges[p]:
                if to_end[p + 1 + pw]:
                    live[p].append(pw)
    return live, to_end


def table_walk(words, table):
    """确定性单向走。返回 (ok, pos, nrec)。"""
    n = len(words)
    p = 0
    nrec = 0
    while p < n:
        cls = words[p] >> 16
        if cls > MAXCLS:
            return False, p, nrec
        pw = table.get((cls, words[p] & 0xffff))
        if pw is None:
            return False, p, nrec
        p += 1 + pw
        nrec += 1
    return p == n, p, nrec


def main():
    allf = []
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if fn.lower().endswith('.pu'):
                allf.append(os.path.join(dirpath, fn))
    random.seed(20261005)
    sample = random.sample(allf, 800)
    small = sorted(allf, key=os.path.getsize)[:100]
    sample = list(dict.fromkeys(small + sample))
    sample.sort(key=os.path.getsize)

    data = {}
    for fp in sample:
        names, words = load_words(fp)
        data[fp] = (names, words)

    table = {}
    for it in range(12):
        # 1) 每份文件在当前表约束下走;失败的用自由 DP 找证据
        support = defaultdict(Counter)  # (cls,fld) -> Counter{pw: 文件数}
        n_ok = 0
        fails = []
        for fp, (names, words) in data.items():
            ok, pos, _ = table_walk(words, table)
            if ok:
                n_ok += 1
                continue
            live, to_end = feasible_records(words)
            if not to_end[0]:
                fails.append((fp, 'no-path', pos))
                continue
            # 收集该文件里每个 (cls,fld) 的可行 pw
            for p, pws in live.items():
                cls = words[p] >> 16
                fld = words[p] & 0xffff
                for pw in pws:
                    support[(cls, fld)][pw] += 1
        # 2) 更新表:取多数
        newtable = {}
        for k, c in support.items():
            newtable[k] = c.most_common(1)[0][0]
        changed = sum(1 for k in set(newtable) | set(table)
                      if newtable.get(k) != table.get(k))
        table = newtable
        print('iter %d: ok %d/%d  table %d entries  changed %d  hard-fails %d'
              % (it, n_ok, len(data), len(table), changed, len(fails)))
        if changed == 0:
            break

    # 冻结表:全量验证
    n_all = n_ok_all = 0
    fail_all = []
    rec_total = 0
    for fp in allf:
        n_all += 1
        _, words = load_words(fp)
        ok, pos, nrec = table_walk(words, table)
        rec_total += nrec
        if ok:
            n_ok_all += 1
        else:
            fail_all.append((os.path.relpath(fp, ROOT), len(words), pos))
    print('FULL: %d/%d walk exactly to end (%.2f%%), %d records total'
          % (n_ok_all, n_all, 100.0 * n_ok_all / n_all, rec_total))
    for f in fail_all[:15]:
        print('  FAIL', f)
    json.dump({'%d,%d' % k: v for k, v in sorted(table.items())},
              open(os.path.join(HERE, 'pu_pw_table.json'), 'w'), indent=1)
    bycls = defaultdict(list)
    for (cls, fld), pw in table.items():
        bycls[cls].append((fld, pw))
    lines = []
    for cls in sorted(bycls):
        row = sorted(bycls[cls])
        pws = Counter(pw for _, pw in row)
        lines.append('cls %2d: %3d flds  pw分布 %s' % (cls, len(row), dict(pws)))
        lines.append('   ' + ', '.join('%d:%d' % x for x in row[:48]) +
                     (' ...' if len(row) > 48 else ''))
    open(os.path.join(HERE, 'pu_pw_table.txt'), 'w', encoding='utf-8').write('\n'.join(lines))


if __name__ == '__main__':
    main()
