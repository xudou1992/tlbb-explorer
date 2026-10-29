"""pu_token6.py — 干净管线:类硬规则(cls0→0, cls7→3)+ fixpoint + 带闸门的崩溃修复。"""
import os
import struct
import json
from collections import defaultdict, Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'out', 'tree', 'data', 'effect')
MAXCLS = 24
MAXPW = 20
OK_W = 8
HARD = {0: 0, 7: 3}   # cls -> 固定 pw(全类)


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
        pw = HARD[cls] if cls in HARD else table.get((cls, fld))
        if pw is None:
            return None, p, recs
        recs.append((p, cls, fld, pw))
        p += 1 + pw
    return True, p, recs


def count_ok(data, table):
    n = 0
    for names, words in data.values():
        ok, _, _ = table_walk(words, table)
        if ok:
            n += 1
    return n


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

    # Phase 1: fixpoint(带硬规则)
    table = {}
    for it in range(10):
        support = defaultdict(Counter)
        n_ok = 0
        for names, words in data.values():
            ok, pos, recs = table_walk(words, table)
            if ok:
                n_ok += 1
                for _, cls, fld, pw in recs:
                    if cls not in HARD:
                        support[(cls, fld)][pw] += OK_W
            else:
                live = live_edges(words)
                for p, pws in live.items():
                    w = words[p]
                    cls = w >> 16
                    if cls in HARD:
                        continue
                    for pw in pws:
                        support[(cls, w & 0xffff)][pw] += 1
        newtable = {k: c.most_common(1)[0][0] for k, c in support.items()}
        diff = sum(1 for k in set(newtable) | set(table)
                   if newtable.get(k) != table.get(k))
        print('fixpoint iter %d: ok %d/%d entries %d diff %d'
              % (it, n_ok, len(data), len(newtable), diff))
        table = newtable
        if diff == 0:
            break

    # Phase 2: 崩溃修复,带闸门(改完必须不降)
    base_ok = count_ok(data, table)
    print('phase2 start ok=%d' % base_ok)
    for it in range(10):
        votes = defaultdict(Counter)
        fails = []
        for fp, (names, words) in data.items():
            ok, pos, recs = table_walk(words, table)
            if ok:
                continue
            fails.append(fp)
            live = live_edges(words)
            if pos in live and live[pos]:
                w = words[pos]
                cls = w >> 16
                if cls not in HARD and table.get((cls, w & 0xffff)) is None:
                    for pw in live[pos]:
                        votes[(cls, w & 0xffff)][pw] += 1
            for (p, cls, fld, t) in recs:
                if cls in HARD:
                    continue
                lv = live.get(p)
                if lv and t not in lv and len(lv) <= 4:  # 少歧义的矛盾才投
                    for pw in lv:
                        votes[(cls, fld)][pw] += 1
        if not votes:
            break
        cand = {k: c.most_common(1)[0][0] for k, c in votes.items()}
        cand = {k: v for k, v in cand.items() if table.get(k) != v}
        if not cand:
            break
        trial = dict(table)
        trial.update(cand)
        trial_ok = count_ok(data, trial)
        print('repair iter %d: fails %d cand %s trial_ok %d (base %d)'
              % (it, len(fails), cand, trial_ok, base_ok))
        if trial_ok > base_ok:
            table = trial
            base_ok = trial_ok
        else:
            # 逐键试,接受单键改进
            improved = False
            for k, v in sorted(cand.items()):
                trial = dict(table)
                trial[k] = v
                t_ok = count_ok(data, trial)
                if t_ok > base_ok:
                    table = trial
                    base_ok = t_ok
                    improved = True
                    print('   accept single key', k, '->', v, 'ok=%d' % t_ok)
            if not improved:
                print('   no improvement, stop')
                break

    n_ok = 0
    fails = []
    for fp, (names, words) in data.items():
        ok, pos, _ = table_walk(words, table)
        if ok:
            n_ok += 1
        else:
            fails.append((os.path.relpath(fp, ROOT), len(words), pos))
    print('FINAL ok %d/%d (%.2f%%)' % (n_ok, len(data), 100.0 * n_ok / len(data)))
    json.dump({'%d,%d' % k: v for k, v in sorted(table.items())},
              open(os.path.join(HERE, 'pu_pw_table.json'), 'w'), indent=1)
    with open(os.path.join(HERE, 'pu_fail_list.txt'), 'w', encoding='utf-8') as fo:
        for f in sorted(fails):
            fo.write('%s\t%d\t%d\n' % f)
    print('fails %d; table entries %d' % (len(fails), len(table)))


if __name__ == '__main__':
    main()
