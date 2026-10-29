"""pu_scan.py — 全量扫 .pu 树:边界、按文件名聚类、找孪生。

输出 .scratch/pu_scan.json:
  - 每份文件的 (relpath, size, nstr, pool_end, param_len)
  - 文件名 token 聚类统计
"""
import json
import os
import re
import struct
import sys
import collections

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'tree', 'data', 'effect')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pu_scan.json')


def parse(raw):
    """返回 (names, param_start, param_len) 或 None。"""
    if raw[:4] != b'JBPU' or len(raw) < 8:
        return None
    cnt = struct.unpack_from('<I', raw, 4)[0]
    if not 0 < cnt < 4096 or 8 + 8 * cnt > len(raw):
        return None
    tab = struct.unpack_from('<%dI' % (2 * cnt), raw, 8)
    pairs = [(tab[i], tab[i + 1]) for i in range(0, 2 * cnt, 2)]
    pool = 8 + 8 * cnt
    total = sum(l for l, _ in pairs)
    if pool + total > len(raw):
        return None
    out, p = [], pool
    for ln, hv in pairs:
        s = raw[p:p + ln]
        if any(c < 9 or 14 <= c < 0x1c for c in s):
            return None
        out.append(s)
        p += ln
    return out, p, len(raw) - p


def main():
    files = []
    for dirpath, _, fns in os.walk(ROOT):
        for fn in fns:
            if fn.lower().endswith('.pu'):
                files.append(os.path.join(dirpath, fn))
    files.sort()
    recs = []
    fail = 0
    param_lens = collections.Counter()
    nstr_dist = collections.Counter()
    for fp in files:
        raw = open(fp, 'rb').read()
        r = parse(raw)
        if r is None:
            fail += 1
            continue
        names, pstart, plen = r
        rel = os.path.relpath(fp, ROOT).replace('\\', '/')
        recs.append({
            'path': rel,
            'size': len(raw),
            'nstr': len(names),
            'pstart': pstart,
            'plen': plen,
        })
        param_lens[plen] += 1
        nstr_dist[len(names)] += 1
    # 尾部余量检查:plen 是否可能不是 4 的倍数
    not4 = [r for r in recs if r['plen'] % 4]
    # 文件名 token:抽掉数字与已知前缀,看有哪些「类名样」token
    toks = collections.Counter()
    for r in recs:
        stem = os.path.basename(r['path'])[:-3]
        for t in stem.split('_'):
            if re.fullmatch(r'\d+', t):
                continue
            toks[t] += 1
    res = {
        'total': len(files),
        'parsed': len(recs),
        'failed': fail,
        'not4_tail': len(not4),
        'not4_examples': [r['path'] for r in not4[:10]],
        'param_len_top': param_lens.most_common(20),
        'nstr_top': nstr_dist.most_common(15),
        'tokens_top': toks.most_common(80),
        'smallest': sorted(recs, key=lambda r: r['plen'])[:30],
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'recs': recs, 'summary': res}, f, ensure_ascii=False, indent=1)
    print('parsed', len(recs), 'failed', fail, 'not4', len(not4))
    print('top tokens:', json.dumps(toks.most_common(40), ensure_ascii=False))


if __name__ == '__main__':
    main()
