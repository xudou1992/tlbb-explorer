#!/usr/bin/env python3
# machao 那份 .mesh 有 63 条 96B 骨记录、一条影响表都没认出来。这里去源文件看一眼
# 记录后面到底跟的是什么：已知的编码是 [u32 顶点数 N][N 个递增顶点号 u32][N 个权重 f32]，
# 读不出来只有两种可能——数据真没有，或者这 126 份用了另一种写法。
import struct, sys, re

p = r'.scratch/out/sidecar_tree/data\source\npc\quest\w1351_boss_machao\w1351_boss_machao.mesh'
raw = open(p, 'rb').read()
print('文件大小 %d 字节' % len(raw))

# 记录 = char[32] 名字 + f32[16]。名字在文件里以 0 结尾的 ASCII 出现，先抓位置。
names = [m.start() for m in re.finditer(rb'bip01', raw)]
print('出现 "bip01" 的字节位置 %d 处，前 12 个：%s' % (len(names), names[:12]))

def ok_matrix(off):
    try:
        f = struct.unpack_from('<16f', raw, off)
    except struct.error:
        return None
    if f[15] != 1.0:
        return None
    rows = [f[0:4], f[4:8], f[8:12]]
    lens = [sum(x * x for x in r) ** .5 for r in rows]
    if min(lens) < 1e-6 or max(lens) / min(lens) > 1.5:
        return None
    dot = lambda a, b: sum(a[i] * b[i] for i in range(4))
    if abs(dot(rows[0], rows[1])) > 0.02 * lens[0] * lens[1]:
        return None
    if abs(dot(rows[0], rows[2])) > 0.02 * lens[0] * lens[2]:
        return None
    if abs(dot(rows[1], rows[2])) > 0.02 * lens[1] * lens[2]:
        return None
    return lens

hits = []
for off in names:
    lens = ok_matrix(off + 32)
    if lens:
        hits.append(off)
print('名字后 32 处对齐到「正交等比 + m15=1」的记录：%d 条' % len(hits))

for off in hits[:8]:
    nm = raw[off:off + 32].split(b'\x00')[0].decode('ascii', 'replace')
    tail = off + 96
    u = struct.unpack_from('<5I', raw, tail)
    fl = struct.unpack_from('<6f', raw, tail)
    print('  %-22s @%7d  记录后 5×u32=%s  前 6 个 f32=%s' % (
        nm, off, u, [round(x, 4) for x in fl]))
