"""pu_token.py — 用全局一致性约束求解 .pu 参数区的记录宽度表。

假说(与 .sfl 的 JBCF 记录文法同构):
  记录 = u32 key(高16=cls, 低16=fld) + pw(cls,fld) 个 u32 载荷
约束:
  1) key 位置的 word 高16(cls) 必须 <= MAXCLS(载荷词无此限制)
  2) 同一 (cls,fld) 在所有文件里 pw 一致
  3) 每份文件从参数区起点恰好走到终点
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
CLS_DEFAULT = {0: 0, 1: 1, 2: 2, 3: 1, 4: 2, 5: 3, 6: 2, 7: 3, 8: 1, 9: 1,
               10: 1, 11: 1, 12: 1, 13: 1, 14: 5, 15: 1, 16: 2, 17: 1, 18: 1,
               19: 1, 20: 1, 21: 1, 22: 1, 23: 1}
FALLBACK = [0, 1, 2, 3, 5, 4, 6, 7, 8, 9, 10, 11, 12, 14, 13, 15, 16, 20, 24]

# 眼验过的种子(doaffector/fanli01/lizi01 三份互证)
SEED = {(1, 59): 1, (7, 58): 3, (6, 178): 2, (14, 368): 5,
        (11, 202): 1, (11, 203): 1, (3, 67): 1, (3, 122): 1, (3, 145): 1,
        (2, 309): 2, (2, 459): 2}


def load_words(path):
    raw = open(path, 'rb').read()
    cnt = struct.unpack_from('<I', raw, 4)[0]
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pairs = [(tab[i], tab[i + 1]) for i in range(0, 2 * cnt, 2)]
    pool = 8 + 8 * cnt
    p = pool
    names = []
    for ln, hv in pairs:
        names.append(raw[p:p + ln])
        p += ln
    start = (p + 3) & ~3
    n = (len(raw) - start) // 4
    words = struct.unpack_from('<%dI' % n, raw, start)
    return names, words


def cands_for(cls, fld, table):
    if (cls, fld) in table:
        return [table[(cls, fld)]]
    out = []
    d = CLS_DEFAULT.get(cls)
    if d is not None:
        out.append(d)
    for pw in FALLBACK:
        if pw not in out:
            out.append(pw)
    return out


def dfs(words, table, budget):
    """迭代式带回溯 DFS。成功 True;穷尽 False;超预算 None。"""
    n = len(words)
    frames = []  # [pos, pk, cands, next_idx, added]
    pos = 0
    while True:
        budget[0] -= 1
        if budget[0] <= 0:
            return None
        if pos == n:
            return True
        if pos < n:
            key = words[pos]
            cls = key >> 16
            if cls <= MAXCLS:
                pk = (cls, key & 0xffff)
                frames.append([pos, pk, cands_for(cls, pk[1], table), 0, None])
            elif not frames:
                return False
        # 处理栈顶
        advanced = False
        while frames:
            fr = frames[-1]
            if fr[4] is not None:
                del table[fr[4]]
                fr[4] = None
            pos0, pk, cands, idx = fr[0], fr[1], fr[2], fr[3]
            if idx >= len(cands):
                frames.pop()
                continue
            pw = cands[idx]
            fr[3] = idx + 1
            if pos0 + 1 + pw > n:
                continue
            added = None
            if pk not in table:
                table[pk] = pw
                added = pk
            fr[4] = added
            pos = pos0 + 1 + pw
            advanced = True
            break
        if not advanced:
            return False


def main():
    allf = []
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if fn.lower().endswith('.pu'):
                allf.append(os.path.join(dirpath, fn))
    random.seed(20261005)
    sample = random.sample(allf, 500)
    small = sorted(allf, key=os.path.getsize)[:80]
    sample = list(dict.fromkeys(small + sample))
    sample.sort(key=os.path.getsize)  # 小→大,先用便宜的学表

    table = dict(SEED)
    failed = []
    for i, fp in enumerate(sample):
        _, words = load_words(fp)
        budget = [300000]
        r = dfs(words, table, budget)
        if r is not True:
            failed.append((os.path.relpath(fp, ROOT), r, len(words)))
    print('table entries: %d   sample=%d failed=%d' % (len(table), len(sample), len(failed)))
    for f in failed[:10]:
        print('  FAIL', f)
    bycls = defaultdict(list)
    for (cls, fld), pw in table.items():
        bycls[cls].append((fld, pw))
    lines = []
    for cls in sorted(bycls):
        row = sorted(bycls[cls])
        pws = Counter(pw for _, pw in row)
        lines.append('cls %2d: %3d flds  pw分布 %s' % (cls, len(row), dict(pws)))
        lines.append('   ' + ', '.join('%d:%d' % x for x in row[:40]) +
                     (' ...' if len(row) > 40 else ''))
    txt = '\n'.join(lines)
    print(txt)
    json.dump({'%d,%d' % k: v for k, v in sorted(table.items())},
              open(os.path.join(HERE, 'pu_pw_table.json'), 'w'), indent=1)
    open(os.path.join(HERE, 'pu_pw_table.txt'), 'w', encoding='utf-8').write(txt)


if __name__ == '__main__':
    main()
