"""把 .mesh 尾部(节点表区)整段按 u32/u8 两种口径排出来,
对账「每条 96B 记录后面的变长段」:头 u32 到底是字节数还是元素数,
以及它跟「到下一条 96B 记录的距离」的关系。结果写 txt,避免 cp936 乱码。"""
import json
import math
import re
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ".scratch/ani/w1351_monster_xiyuqiezei_yifu_001.mesh"
out = sys.argv[2] if len(sys.argv) > 2 else ".scratch/parent_tail_dump.txt"
b = open(path, "rb").read()
NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


def name_at(off):
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


# 找所有 96B 带矩阵记录(排除 tx_ 挂点表:名字以 tx_ 开头的槽)
recs = []
i = 0
while i + 96 <= len(b):
    n = name_at(i)
    if n is None:
        i += 4
        continue
    mat = matrix_at(i + 32) if i + 96 <= len(b) else None
    if mat:
        recs.append([i, n, mat])
        i += 96
    else:
        i += 4

lines = []
w = lines.append
w("file=%s size=%d declared_bones@0x110=%d matrix_records=%d" %
  (path, len(b), struct.unpack_from("<I", b, 0x110)[0], len(recs)))
w("")

# 记录起点列表(区分骨架区与 tx_ 挂点区)
starts = [r[0] for r in recs]
for idx, (off, nm, mat) in enumerate(recs):
    end = off + 96
    nxt = starts[idx + 1] if idx + 1 < len(recs) else len(b)
    w("=== rec#%d @0x%06x(%d) %-28s gap_to_next=%d  (next=0x%06x)" %
      (idx, off, off, nm, nxt - end, nxt))
    # gap 区逐 4 字节:u32 与「按 u8 读」两口径都给
    gap = b[end:nxt]
    for j in range(0, len(gap), 16):
        chunk = gap[j:j + 16]
        hexs = " ".join("%02x" % c for c in chunk)
        u32s = []
        for k in range(0, len(chunk) - 3, 4):
            v = struct.unpack_from("<I", chunk, k)[0]
            u32s.append("%d" % v if v < 1000000 else "0x%08x" % v)
        f32s = []
        for k in range(0, len(chunk) - 3, 4):
            fv = struct.unpack_from("<f", chunk, k)[0]
            f32s.append("%.4g" % fv if abs(fv) < 1e5 and abs(fv) > 1e-4 else "-")
        w("  +0x%04x %s" % (j, hexs))
        w("           u32: %s" % " ".join(u32s))
        w("           f32: %s" % " ".join(f32s))
    w("")

open(out, "w", encoding="utf-8").write("\n".join(lines))
print("written", out, len(lines), "lines")
