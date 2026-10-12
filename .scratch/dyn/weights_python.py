#!/usr/bin/env python3
"""给 Rust 的每份权重表明细配一只独立的眼：同一批 `.mesh` 用 python 再数一遍，
然后逐文件比 `withSkin`（带影响表的权利记录数），把两边不一致的名单拉出来。
为什么要做：10-12 那次总量对不上——python 认到 2,212 份有表、Rust 认到 2,090 份，差 122 份。
不对齐就不能说「覆盖率是多少」是硬的。
"""
import os, re, struct, sys

NAME = re.compile(b'[ -~]{3,31}' + bytes([0]))


def mat_ok(raw, off):
    if off + 64 > len(raw):
        return False
    f = struct.unpack_from('<16f', raw, off)
    if f[15] != 1.0:
        return False
    rows = [f[0:4], f[4:8], f[8:12]]
    lens = [sum(x * x for x in r) ** 0.5 for r in rows]
    if min(lens) < 1e-6 or max(lens) / min(lens) > 1.5:
        return False
    for i, j in ((0, 1), (0, 2), (1, 2)):
        d = sum(rows[i][k] * rows[j][k] for k in range(4))
        if abs(d) > 0.02 * lens[i] * lens[j]:
            return False
    return True


def table(raw, off, vc):
    if off + 4 > len(raw):
        return None
    n = struct.unpack_from('<I', raw, off)[0]
    if n == 0 or n > vc or off + 4 + 8 * n > len(raw):
        return None
    idx = struct.unpack_from('<%dI' % n, raw, off + 4)
    w = struct.unpack_from('<%df' % n, raw, off + 4 + 4 * n)
    if len(set(idx)) != n or max(idx) >= vc:
        return None
    if min(w) <= 0.0 or max(w) > 1.0001 or all(x <= 1e-6 for x in w):
        return None
    return n


def scan(path):
    raw = open(path, 'rb').read()
    if len(raw) < 0x90 or not raw.startswith(b'Copyright'):
        return None
    vc = struct.unpack_from('<I', raw, 0x8C)[0]
    if not (0 < vc < 400000):
        return None
    recs = 0
    with_skin = 0
    covered = set()
    for m in NAME.finditer(raw):
        off = m.start()
        if off and 32 <= raw[off - 1] < 127:
            continue
        if raw[off:off + 3] == b'tx_':
            continue
        if not mat_ok(raw, off + 32):
            continue
        recs += 1
        t = table(raw, off + 96, vc)
        if t is None:
            continue
        with_skin += 1
        idx = struct.unpack_from('<%dI' % t, raw, off + 96 + 4)
        covered.update(idx)
    return recs, with_skin, len(covered), vc


def main():
    trees = sys.argv[1:] or ['.scratch/out/tree', '.scratch/out/sidecar_tree']
    out = open('.scratch/tree_weights_python.txt', 'w', encoding='utf-8')
    out.write('file|nodes|withSkin|covered|verts\n')
    n = 0
    for root in trees:
        for dirpath, _dirs, files in os.walk(root):
            for fn in files:
                if not fn.lower().endswith('.mesh'):
                    continue
                p = os.path.join(dirpath, fn)
                r = scan(p)
                if r is None:
                    continue
                rel = os.path.relpath(p, '.scratch/out').replace(os.sep, '/')
                out.write('%s|%d|%d|%d|%d\n' % (rel, r[0], r[1], r[2], r[3]))
                n += 1
    out.close()
    print('python 数了 %d 份 → .scratch/tree_weights_python.txt' % n)


main()
