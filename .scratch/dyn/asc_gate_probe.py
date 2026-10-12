#!/usr/bin/env python3
# 改判据之前先量：把「严格递增」换成「索引互不相同且都落在顶点数内 + 权重在 (0,1]」，
# 全库会多出多少张表？多出来的是真权重还是噪声？
# 判真只用量过的那一条验证式：逐顶点按骨累加，看有多少顶点的和正好 ≈1.0。
import struct, re, sys, glob, os
from collections import defaultdict

def records(raw, vc):
    """按「名字 + 正交等比矩阵」找 96B 节点记录，返回 [(偏移, 名字)]。"""
    out = []
    for m in re.finditer(rb'[ -~]{3,31}\x00', raw):
        off = m.start()
        if off > 0 and 32 <= raw[off - 1] < 127:
            continue                      # 名字前一个字节还是可打印 = 截到的半截名
        f = None
        try:
            f = struct.unpack_from('<16f', raw, off + 32)
        except struct.error:
            continue
        if len(raw) < off + 96 or f[15] != 1.0:
            continue
        rows = [f[0:4], f[4:8], f[8:12]]
        lens = [sum(x * x for x in r) ** .5 for r in rows]
        if min(lens) < 1e-6 or max(lens) / min(lens) > 1.5:
            continue
        dot = lambda a, b: sum(a[i] * b[i] for i in range(4))
        if any(abs(dot(rows[i], rows[j])) > 0.02 * lens[i] * lens[j]
               for i, j in ((0, 1), (0, 2), (1, 2))):
            continue
        out.append((off, raw[off:off + 32].split(b'\x00')[0].decode('ascii', 'replace')))
    return out

def table(raw, t, vc):
    """返回 (N, 索引, 权重) 或 None。"""
    if t + 4 > len(raw):
        return None
    n = struct.unpack_from('<I', raw, t)[0]
    if n == 0 or n > vc or t + 4 + 8 * n > len(raw):
        return None
    idx = struct.unpack_from('<%dI' % n, raw, t + 4)
    w = struct.unpack_from('<%df' % n, raw, t + 4 + 4 * n)
    if max(idx) >= vc or min(w) <= 0.0 or max(w) > 1.0 + 1e-6:
        return None
    return n, idx, w

def scan(path, limit_vc=None):
    raw = open(path, 'rb').read()
    if len(raw) < 0x90 or raw[:9] != b'Copyright':
        return None
    vc = struct.unpack_from('<I', raw, 0x8C)[0]
    if not (0 < vc < 200000):
        return None
    strict, loose_only, bad = [], [], []
    for off, nm in records(raw, vc):
        tb = table(raw, off + 96, vc)
        if not tb:
            continue
        n, idx, w = tb
        asc = all(idx[i] < idx[i + 1] for i in range(n - 1))
        dup = len(set(idx)) != n
        if asc and not dup:
            strict.append(tb)
        elif not dup:
            loose_only.append(tb)
        else:
            bad.append(tb)
    return vc, strict, loose_only, bad

def sums(tables):
    s = defaultdict(float)
    for n, idx, w in tables:
        for i, k in enumerate(idx):
            s[k] += w[i]
    return s

def report(paths, tag):
    gain_files = gain_tables = strict_files = strict_tables = 0
    gain_cov = gain_one = 0
    for p in paths:
        r = scan(p)
        if not r:
            continue
        vc, strict, loose, bad = r
        if strict:
            strict_files += 1
            strict_tables += len(strict)
        if loose:
            gain_files += 1
            gain_tables += len(loose)
            s = sums(loose)
            gain_cov += len(s)
            gain_one += sum(1 for v in s.values() if abs(v - 1.0) < 0.01)
    print('[%s] 扫 %d 份' % (tag, len(paths)))
    print('  严格递增认到的：文件 %d · 表 %d' % (strict_files, strict_tables))
    print('  放宽后才认到的：文件 %d · 表 %d · 覆盖顶点 %d · 其中逐顶点和≈1.0 的 %d（%.1f%%）'
          % (gain_files, gain_tables, gain_cov, gain_one, 100.0 * gain_one / gain_cov if gain_cov else 0))

side = sorted(glob.glob('.scratch/out/sidecar_tree/**/*.mesh', recursive=True))
ctrl = sorted(glob.glob('.scratch/out/tree/**/*.mesh', recursive=True))
step = max(1, len(ctrl) // 120)
report(side, 'sidecar_tree（cfg 身份救回的 468 份）')
report(ctrl[::step][:120], '对照：原有有名网格抽 %d 份' % len(ctrl[::step][:120]))
print('对照全库共 %d 份 .mesh，本轮只抽 %d 份（全跑要另开一次）' % (len(ctrl), len(ctrl[::step][:120])))
