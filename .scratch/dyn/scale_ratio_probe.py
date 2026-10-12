#!/usr/bin/env python3
"""那 74 份「python 认到的表比 Rust 多」的文件，多出来的到底卡在哪一条？
一个还没验过的嫌疑：Rust 的 `read_node` 要求三轴长度比 ≤1.05（**只认均匀缩放**），
而 10-10 那次「骨上带非均匀缩放」的翻案只改了骨架段（`tail_is_mat64`），**没回头改节点记录**。
如果多出来的记录轴长比都 >1.05，那就是 Rust 的假阴性，会影响导出（整张又挂回根骨）。
"""
import os, re, struct, collections, sys

NAME = re.compile(b'[ -~]{3,31}' + bytes([0]))
SIDE = '.scratch/out/sidecar_tree'
CTRL = '.scratch/out/tree'


def load(path):
    d = {}
    for line in open(path, encoding='utf-8', errors='replace').read().splitlines()[1:]:
        p = line.split('|')
        if len(p) < 5:
            continue
        try:
            d[p[0].replace(chr(92), '/')] = (int(p[1]), int(p[2]), int(p[3]), int(p[4]))
        except ValueError:
            continue
    return d


def rows_stats(raw):
    """返回 [(轴长比, 是否带表)]，按 python 的认记录方式。"""
    vc = struct.unpack_from('<I', raw, 0x8C)[0]
    out = []
    for m in NAME.finditer(raw):
        off = m.start()
        if off and 32 <= raw[off - 1] < 127:
            continue
        if raw[off:off + 3] == b'tx_':
            continue
        if off + 96 > len(raw):
            continue
        f = struct.unpack_from('<16f', raw, off + 32)
        if abs(f[15] - 1.0) > 1e-3:
            continue
        R = [list(f[0:3]), list(f[4:7]), list(f[8:11])]
        lens = [sum(x * x for x in v) ** 0.5 for v in R]
        mn, mx = min(lens), max(lens)
        if mn <= 1e-6:
            continue
        ratio = mx / mn
        ok_orth = True
        for i in range(3):
            for j in range(i + 1, 3):
                dd = sum(R[i][k] * R[j][k] for k in range(3))
                if abs(dd) > 0.02 * lens[i] * lens[j]:
                    ok_orth = False
        if not ok_orth:
            continue
        n = struct.unpack_from('<I', raw, off + 96)[0] if off + 100 <= len(raw) else 0
        has_tab = False
        if 0 < n <= vc and off + 4 + 8 * n + 96 <= len(raw):
            idx = struct.unpack_from('<%dI' % n, raw, off + 100)
            w = struct.unpack_from('<%df' % n, raw, off + 100 + 4 * n)
            if len(set(idx)) == n and max(idx) < vc and min(w) >= 0.0 and max(w) <= 1.0001 and any(x > 1e-6 for x in w):
                has_tab = True
        out.append((ratio, has_tab))
    return out


def main():
    py = load('.scratch/tree_weights_python.txt')
    rs = {}
    rs.update(load('.scratch/tree_weights_rust_both.txt'))
    rs.update(load('.scratch/sidecar_weights_rust_both.txt'))
    py2 = {}
    for k, v in py.items():
        for pre in ('tree/', 'sidecar_tree/'):
            if k.startswith(pre):
                py2[k[len(pre):]] = v
    diff = [k for k in set(py2) & set(rs) if py2[k][1] > rs[k][1]]
    print('python 比 Rust 认到更多表的文件：%d 份' % len(diff))
    buckets = collections.Counter()
    tables_by_bucket = collections.Counter()
    seen = 0
    for k in diff:
        path = None
        for cand in (os.path.join(CTRL, k), os.path.join(SIDE, k),
                     os.path.join('.scratch/out/tree', k), os.path.join('.scratch/out/sidecar_tree', k)):
            if os.path.exists(cand):
                path = cand
                break
        if not path:
            continue
        seen += 1
        if seen > 40:
            break
        for ratio, has_tab in rows_stats(open(path, 'rb').read()):
            b = '≤1.05（Rust 该认）' if ratio <= 1.05 else ('1.05~1.5（Rust 拒）' if ratio <= 1.5 else '>1.5')
            buckets[b] += 1
            if has_tab:
                tables_by_bucket[b] += 1
    print('看了前 %d 份，记录按轴长比分桶：' % seen)
    for b in ('≤1.05（Rust 该认）', '1.05~1.5（Rust 拒）', '>1.5'):
        print('   %-22s 记录 %6d · 其中带表 %6d' % (b, buckets[b], tables_by_bucket[b]))
    tot = sum(buckets.values())
    if tot:
        print('被「≤1.05 均匀缩放」这一条挡掉的记录占比：%.1f%%（带表的占 %.1f%%）'
              % (100.0 * (tot - buckets['≤1.05（Rust 该认）']) / tot,
                 100.0 * (sum(tables_by_bucket.values()) - tables_by_bucket['≤1.05（Rust 该认）'])
                 / max(1, sum(tables_by_bucket.values()))))


main()
