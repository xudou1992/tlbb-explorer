#!/usr/bin/env python3
# 接着上一条：machao 的记录后面明明跟着 [N][N 个顶点号][N 个 f32]，只是**不递增**。
# 现有读取器的认表判据是「顶点号严格递增」，所以这 126 份整张表被判没有。
# 这里不靠猜：把 19 条表全读出来，看索引是否都落在顶点数内、权重是否在 (0,1]、
# 逐顶点累加有多少正好等于 1.0 —— 三条都中，才敢说「表是真的，判据太严」。
import struct, re, sys
from collections import defaultdict

p = sys.argv[1] if len(sys.argv) > 1 else r'.scratch/out/sidecar_tree/data\source\npc\quest\w1351_boss_machao\w1351_boss_machao.mesh'
raw = open(p, 'rb').read()
VC = 3641  # GLB 里记的顶点数（两份 SkinnedMesh 各 3641）

def ok_matrix(off):
    try:
        f = struct.unpack_from('<16f', raw, off)
    except struct.error:
        return False
    if f[15] != 1.0:
        return False
    rows = [f[0:4], f[4:8], f[8:12]]
    lens = [sum(x * x for x in r) ** .5 for r in rows]
    if min(lens) < 1e-6 or max(lens) / min(lens) > 1.5:
        return False
    dot = lambda a, b: sum(a[i] * b[i] for i in range(4))
    return all(abs(dot(rows[i], rows[j])) <= 0.02 * lens[i] * lens[j]
               for i, j in [(0, 1), (0, 2), (1, 2)])

recs = []
for m in re.finditer(rb'[ -~]{4,31}\x00', raw[150000:]):
    off = m.start() + 150000
    if ok_matrix(off + 32):
        recs.append((off, raw[off:off + 32].split(b'\x00')[0].decode('ascii', 'replace')))
print('按「名字 + 正交等比矩阵」找到的记录：%d 条（Rust 那边报 63 条，这里只扫了后半段）' % len(recs))

sums = defaultdict(float)
cov = set()
asc = nonasc = zero = 0
print('\n骨名'.ljust(24), 'N', '索引范围', '递增?', '权重范围', '权重和')
for off, nm in recs:
    t = off + 96
    n = struct.unpack_from('<I', raw, t)[0]
    if n == 0:
        zero += 1
        continue
    idx = struct.unpack_from('<%dI' % n, raw, t + 4)
    w = struct.unpack_from('<%df' % n, raw, t + 4 + 4 * n)
    if max(idx) >= VC or min(w) <= 0 or max(w) > 1.001:
        print('  %-22s %5d  ★不像表：索引最大 %d / 权重范围 %.3f~%.3f' % (nm, n, max(idx), min(w), max(w)))
        continue
    a = all(idx[i] < idx[i + 1] for i in range(n - 1))
    asc += a
    nonasc += (not a)
    for i, k in enumerate(idx):
        sums[k] += w[i]
        cov.add(k)
    print('  %-22s %5d  0..%-5d %-4s %.3f~%.3f  %.3f' % (
        nm, n, max(idx), '递增' if a else '不递增', min(w), max(w), sum(w)))

print('\n合计：带表的记录 %d 条（严格递增 %d · 不递增 %d）· 0 影响的 %d 条' % (asc + nonasc, asc, nonasc, zero))
print('覆盖顶点 %d / %d = %.1f%%' % (len(cov), VC, 100.0 * len(cov) / VC))
one = sum(1 for k in cov if abs(sums[k] - 1.0) < 0.01)
print('逐顶点累加正好≈1.0 的：%d / %d' % (one, len(cov)))
