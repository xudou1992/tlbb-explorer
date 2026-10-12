#!/usr/bin/env python3
# 每个顶点被几根骨影响？超过 4 根的那些，导出时被截到权重最大的前 4 根——
# 被丢掉的那一份权重，正好能让相邻两个顶点被不同的骨带跑（纯同骨区不撕、混合区撕 50 倍，
# 与这个形状吻合）。这条只数结构，不改任何东西。
import re, struct, sys
from collections import defaultdict

p = sys.argv[1] if len(sys.argv) > 1 else '.scratch/out/sidecar_tree/data/source/npc/quest/w1351_boss_machao/w1351_boss_machao.mesh'
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

per = defaultdict(list)
tables = 0
for m in re.finditer(rb'[ -~]{3,31}\x00', raw):
    off = m.start()
    if off and 32 <= raw[off - 1] < 127:
        continue
    if raw[off:off + 3] == b'tx_':
        continue
    if not mat_ok(off):
        continue
    t = table(off + 96)
    if t is None:
        continue
    tables += 1
    nm = raw[off:off + 32].split(b'\x00')[0].decode('ascii', 'replace')
    for i, k in enumerate(t[0]):
        per[k].append((nm, t[1][i]))

hist = defaultdict(int)
dropped_w = 0.0
dropped_verts = 0
for k, lst in per.items():
    lst.sort(key=lambda x: -x[1])
    hist[len(lst)] += 1
    if len(lst) > 4:
        dropped_verts += 1
        dropped_w += sum(w for _, w in lst[4:])
print('%s · 声明顶点 %d · 带表 %d 张 · 被覆盖顶点 %d' % (p.split('/')[-1], VC, tables, len(per)))
print('每顶点被几根骨影响（根数 : 顶点数）：')
for n in sorted(hist):
    flag = '  ← 超过 4 根，导出要截前 4' if n > 4 else ''
    print('   %2d 根 : %6d 个（%.2f%%）%s' % (n, hist[n], 100.0 * hist[n] / len(per), flag))
print('被截掉的权重合计 %.1f（平均每顶点 %.4f）· 受影响顶点 %d 个（占覆盖的 %.1f%%）'
      % (dropped_w, dropped_w / max(1, dropped_verts), dropped_verts, 100.0 * dropped_verts / len(per)))
over = [k for k, lst in per.items() if len(lst) > 4]
if over:
    mx = max(over, key=lambda k: len(per[k]))
    print('影响最多的那个顶点 %d 号：%d 根骨，权重 %s' % (mx, len(per[mx]), [round(w, 2) for _, w in sorted(per[mx], key=lambda x: -x[1])][:8]))
