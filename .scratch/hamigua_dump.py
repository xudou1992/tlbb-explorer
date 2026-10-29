# -*- coding: utf-8 -*-
"""hamigua 变体取证 · 第 2 步：字节级差分（2026-10-05）

对 hamigua 主样本逐字节解尾部，打印：
  * 全部 96B 记录候选的位置与名字（含矩阵第一行）
  * 0x110 声明数 / 0x8C 顶点数 / 尾部可疑起点
  * 从尾部某起点起的原始字节解剖（u32/f32/名字三视图）
"""
import re
import struct
import sys

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


def name_at(b, off):
    if off < 1 or off + 32 > len(b):
        return None
    if re.match(rb"[0-9A-Za-z_\-.]", b[off - 1:off]):
        return None
    m = NAME_OK.match(b, off)
    if not m:
        return None
    s = m.group()
    if len(s) > 31 or b[off + len(s)] != 0:
        return None
    if any(x != 0 for x in b[off + len(s):off + 32]):
        return None
    return s.decode()


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def ortho3(rows):
    lens = [sum(v * v for v in r) ** 0.5 for r in rows]
    if min(lens) < 1e-4 or max(lens) / min(lens) > 1.05:
        return False
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) > 1e-2:
                return False
    return True


def looks_record96(b, pos):
    if pos + 96 > len(b):
        return None
    nm = name_at(b, pos)
    if nm is None:
        return None
    m = struct.unpack_from("<16f", b, pos + 32)
    if not all(abs(v) < 1e7 for v in m):
        return None
    if abs(m[15] - 1.0) > 1e-3:
        return None
    if not ortho3([m[0:3], m[4:7], m[8:11]]):
        return None
    return nm, m


def scan(path):
    b = open(path, "rb").read()
    print("=== %s  size=%d  declared(0x110)=%d  vc(0x8C)=%d" %
          (path.split("\\")[-1], len(b), u32(b, 0x110), u32(b, 0x8C)))
    print("  0x10C=%08x 0x114=%08x 0x118=%08x" % (u32(b, 0x10C), u32(b, 0x114), u32(b, 0x118)))
    # 所有名字槽（步长 4 扫描）
    names = []
    i = 0
    while i + 32 <= len(b):
        nm = name_at(b, i)
        if nm:
            names.append((i, nm))
            i += 32
        else:
            i += 4
    print("  名字槽 %d 个：" % len(names))
    for off, nm in names:
        tag = ""
        r = looks_record96(b, off - 0) if off + 96 <= len(b) else None
        # 记录判定按名字槽位置算
        rec = looks_record96(b, off) if off + 96 <= len(b) else None
        if rec:
            m = rec[1]
            tag = " RECORD96 mat[0..3]=%s t=(%.4f,%.4f,%.4f)" % (
                ["%.4g" % v for v in m[0:3]], m[12], m[13], m[14])
        print("    0x%05x  %-28s%s" % (off, nm, tag))
    # ASCII 字符串全景（>=4 可打印字符）
    print("  可打印串：")
    for m in re.finditer(rb"[ -~]{4,}", b):
        s = m.group().decode()
        if not re.match(rb"[0-9A-Fa-f]{8,}", m.group()):
            print("    0x%05x  %s" % (m.start(), s[:80]))
    return b


for p in sys.argv[1:]:
    scan(p)
    print()
