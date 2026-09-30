"""复刻 geometry.rs 的 read_node，把 .mesh 尾部的「只有名字的骨」与「带矩阵的骨」
按文件顺序排出来，看那 10 根没有矩阵的骨到底挂在哪。"""
import json
import math
import re
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ".scratch/ani/w1351_monster_xiyuqiezei_yifu_001.mesh"
b = open(path, "rb").read()
NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


def name_at(off):
    """名字段：从字段头开始、可打印、NUL 结尾且剩余填 0。"""
    if off > 0:
        prev = b[off - 1:off]
        if re.match(rb"[0-9A-Za-z_\-.]", prev):
            return None
    m = NAME_OK.match(b, off)
    if not m:
        return None
    s = m.group()
    if len(s) > 31:
        return None
    if b[off + len(s)] != 0:
        return None
    if any(x != 0 for x in b[off + len(s):off + 32]):
        return None
    return s.decode()


def matrix_at(off):
    m = struct.unpack_from("<16f", b, off)
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in m):
        return None
    if abs(m[15] - 1.0) > 1e-3:
        return None
    rows = [m[0:3], m[4:7], m[8:11]]
    lens = [math.sqrt(sum(v * v for v in r)) for r in rows]
    mn, mx = min(lens), max(lens)
    if mn <= 1e-6 or mx / mn > 1.05:
        return None
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) > 1e-2:
                return None
    return m


declared = struct.unpack_from("<I", b, 0x110)[0]
rows = []
i = 0
while i + 32 <= len(b):
    n = name_at(i)
    if n is None:
        i += 4
        continue
    mat = matrix_at(i + 32) if i + 96 <= len(b) else None
    rows.append((i, n, mat))
    i += 96 if mat else 4
withmat = [r for r in rows if r[2]]
only = [r for r in rows if not r[2]]
print("声明 %d 根 · 带矩阵 %d 条 · 只有名字 %d 条" % (declared, len(withmat), len(only)))
print()
print("按文件顺序（* = 带矩阵，- = 只有名字）：")
for off, n, mat in rows:
    print("  %s 0x%06x %-30s %s" % ("*" if mat else "-", off, n,
          "" if not mat else "平移=%.3f %.3f %.3f" % (mat[12], mat[13], mat[14])))
json.dump([[o, n, (list(m) if m else None)] for o, n, m in rows],
          open(".scratch/mesh_nodes_ordered.json", "w", encoding="utf-8"), ensure_ascii=False)
