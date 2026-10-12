#!/usr/bin/env python3
# 「道具骨挂在头上」到底是数据就这么写，还是 parse_hierarchy 把孩子名单挂错了条目？
# 这里把指定骨名的每一处出现都摊开：前面 48 字节 + 后面 96 字节，
# 看它是不是紧跟在「某条目的自名两遍 + 孩子数」后面（那样就是数据原文认的父），
# 还是出现在别的位置。
import re, struct, sys

p = sys.argv[1]
names = sys.argv[2:]
raw = open(p, 'rb').read()
VC = struct.unpack_from('<I', raw, 0x8C)[0]

def is_mat(off):
    if off + 64 > len(raw):
        return False
    f = struct.unpack_from('<16f', raw, off)
    if f[15] != 1.0:
        return False
    rows = [f[0:4], f[4:8], f[8:12]]
    lens = [sum(x * x for x in r) ** .5 for r in rows]
    if min(lens) < 1e-6 or max(lens) / min(lens) > 1.5:
        return False
    dot = lambda a, b: sum(a[i] * b[i] for i in range(4))
    return all(abs(dot(rows[i], rows[j])) <= 0.02 * lens[i] * lens[j] for i, j in ((0, 1), (0, 2), (1, 2)))

def name_at(off):
    b = raw[off:off + 32].split(b'\x00')[0]
    try:
        s = b.decode('ascii')
    except Exception:
        return None
    return s if s and all(32 <= ord(c) < 127 for c in s) else None

for nm in names:
    pat = (nm + '\x00').encode('ascii')
    hits = [m.start() for m in re.finditer(re.escape(pat), raw)]
    print('\n=== %s ：出现 %d 处（声明顶点 %d）' % (nm, len(hits), VC))
    for off in hits:
        pre = raw[max(0, off - 40):off]
        pn = None
        # 往前找最近的一个 32 字节对齐的名字
        for back in range(1, 9):
            o = off - 32 * back
            if o < 0:
                break
            s = name_at(o)
            if s and s != nm:
                pn = (s, o)
                break
        mat = is_mat(off + 32)
        nxt = name_at(off + 32) if not mat else None
        tag = '96B 记录（名字后跟矩阵）' if mat else ('后面是个名字 %r' % nxt if nxt else '后面像数字')
        print('  @%-7d %s · 往前最近的别的名字：%s' % (off, tag, pn[0] + ' @%d' % pn[1] if pn else '—'))
        u = struct.unpack_from('<2I', raw, off - 8) if off >= 8 else (0, 0)
        print('           紧邻前 8 字节两个 u32 = %s · 本名后 32 字节起 %s'
              % (str(u), repr(raw[off + 32:off + 64])))
