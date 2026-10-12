#!/usr/bin/env python3
# 混合顶点把边拉成 50 倍，最常见的解释是「一张表不够」：一根骨的影响顶点表
# 若是**分块存**（第二块紧跟第一块），我们只读了第一块，就会给出一半权重。
# 这里不猜：按已知语法读完第一张表之后，立刻拿同一套判据试紧跟的那一段是不是第二张表。
import os, re, struct, sys
from collections import defaultdict

p = sys.argv[1] if len(sys.argv) > 1 else '.scratch/out/sidecar_tree/data\source\npc\quest\w1351_boss_machao\w1351_boss_machao.mesh'
raw = open(p, 'rb').read()
VC = struct.unpack_from('<I', raw, 0x8C)[0]

def mat_ok(off):
    if off + 96 > len(raw):
        return False
    f = struct.unpack_from('<16f', raw, off + 32)
    if f[15] != 1.0:
        return False
    rows = [f[0:4], f[4:8], f[8:12]]
    lens = [sum(x * x for x in r) ** .5 for r in rows]
    if min(lens) < 1e-6 or max(lens) / min(lens) > 1.5:
        return False
    dot = lambda a, b: sum(a[i] * b[i] for i in range(4))
    return all(abs(dot(rows[i], rows[j])) <= 0.02 * lens[i] * lens[j] for i, j in ((0, 1), (0, 2), (1, 2)))

def table(off):
    """按判据读一张表：[u32 N][N×u32 顶点号（互异、<顶点数）][N×f32 权重（0..1]，不全 0]"""
    if off + 4 > len(raw):
        return None
    n = struct.unpack_from('<I', raw, off)[0]
    if n == 0 or n > VC or off + 4 + 8 * n > len(raw):
        return None
    idx = struct.unpack_from('<%dI' % n, raw, off + 4)
    w = struct.unpack_from('<%df' % n, raw, off + 4 + 4 * n)
    if len(set(idx)) != n or max(idx) >= VC:
        return None
    if min(w) <= 0.0 or max(w) > 1.0001 or all(x <= 1e-6 for x in w):
        return None
    return n, list(idx), list(w)

recs = []
for m in re.finditer(rb'[ -~]{3,31}\x00', raw):
    off = m.start()
    if off and 32 <= raw[off - 1] < 127:
        continue
    if raw[off:off + 3] == b'tx_':
        continue
    if mat_ok(off):
        recs.append((off, raw[off:off + 32].split(b'\x00')[0].decode('ascii', 'replace')))

first = second = zero = 0
sums1, sums2 = defaultdict(float), defaultdict(float)
span = []
for off, nm in recs:
    t1 = table(off + 96)
    if t1 is None:
        zero += 1
        continue
    first += 1
    n1, i1, w1 = t1
    for i, k in enumerate(i1):
        sums1[k] += w1[i]
    end1 = off + 96 + 4 + 8 * n1
    t2 = table(end1)
    if t2 is not None:
        second += 1
        n2, i2, w2 = t2
        for i, k in enumerate(i2):
            sums2[k] += w2[i]
            sums1[k] += w2[i]
    span.append((nm, n1, (t2[0] if t2 else 0)))

def stat(d):
    if not d:
        return '（没有）'
    ok = sum(1 for v in d.values() if abs(v - 1.0) < 0.01)
    lo = sum(1 for v in d.values() if v < 0.99)
    hi = sum(1 for v in d.values() if v > 1.01)
    return '顶点 %d · 和≈1.0 的 %d · 和<1 的 %d · 和>1 的 %d' % (len(d), ok, lo, hi)

print('%s · 顶点数 %d' % (os.path.basename(p), VC))
print('记录 %d 条：带第一张表 %d · 紧跟还有第二张表的 %d · 一张都没有的 %d' % (len(recs), first, second, zero))
a = dict(sums1)
only1 = defaultdict(float)
for off, nm in recs:
    t1 = table(off + 96)
    if t1:
        for i, k in enumerate(t1[1]):
            only1[k] += t1[2][i]
print('\n只读第一张表：%s' % stat(only1))
print('两张都读（若第二张存在）：%s' % stat(dict(sums1)))
print('\n前 10 条（骨名 · N1 · N2）：%s' % ', '.join('%s(%d/%d)' % (n, a1, b1) for n, a1, b1 in span[:10]))
