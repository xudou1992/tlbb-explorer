# 独立复核第 6 条「递增判据（已修）」：若老判据「顶点号严格递增」还在，
# machao 的 60 张影响表会被误杀多少？记录里写的是「严格递增 0 条」。
# 这里只读文件、不改任何东西，判据与 .scratch/dyn/second_table_probe.py 同一套语法。
import re, struct, sys

p = sys.argv[1] if len(sys.argv) > 1 else \
    r'D:/TLGL/.scratch/out/sidecar_tree/data/source/npc/quest/w1351_boss_machao/w1351_boss_machao.mesh'
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
    if off + 4 > len(raw):
        return None
    n = struct.unpack_from('<I', raw, off)[0]
    if n == 0 or n > VC or off + 4 + 8 * n > len(raw):
        return None
    idx = struct.unpack_from('<%dI' % n, raw, off + 4)
    w = struct.unpack_from('<%df' % n, raw, off + 4 + 4 * n)
    if len(set(idx)) != n or max(idx) >= VC or min(w) <= 0.0 or max(w) > 1.0001:
        return None
    if all(x <= 1e-6 for x in w):
        return None
    return list(idx), list(w)


tables = []
for m in re.finditer(rb'[ -~]{3,31}\x00', raw):
    off = m.start()
    if off and 32 <= raw[off - 1] < 127:
        continue
    if raw[off:off + 3] == b'tx_':
        continue
    if not mat_ok(off):
        continue
    t = table(off + 96)
    if t is not None:
        tables.append(t[0])

strict = sum(1 for idx in tables if all(b > a for a, b in zip(idx, idx[1:])))
asc_allow_eq = sum(1 for idx in tables if all(b >= a for a, b in zip(idx, idx[1:])))
distinct_bounded = len(tables)
print('%s · 顶点数 %d' % (p.replace('\\', '/').split('/')[-1], VC))
print('现判据（互异+有界）认出的表：%d 张' % distinct_bounded)
print('  其中「严格递增」的：%d 张  → 老判据会放行 %d、误杀 %d'
      % (strict, strict, distinct_bounded - strict))
print('  其中「非递减」的：%d 张（顺带一个更松的参照）' % asc_allow_eq)
