"""对 .mesh 尾部节点表做「变长块」体检：
每条 96B 记录之后到底跟了什么，长度字段能不能对上「元素个数」或「字节数」。
用法：python node_block_probe.py 文件1.mesh 文件2.mesh ...
"""
import glob
import math
import re
import struct
import sys

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


def load(path):
    return open(path, "rb").read()


def name_at(b, off):
    if off > 0 and re.match(rb"[0-9A-Za-z_\-.]", b[off - 1:off]):
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


def matrix_at(b, off):
    if off + 64 > len(b):
        return None
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


def records(b):
    out = []
    i = 0
    while i + 96 <= len(b):
        n = name_at(b, i)
        if n is not None and matrix_at(b, i + 32) is not None:
            out.append((i, n))
            i += 96
            continue
        i += 4
    return out


def probe(path):
    b = load(path)
    if len(b) < 0x114:
        return
    declared = struct.unpack_from("<I", b, 0x110)[0]
    recs = records(b)
    if len(recs) < 3:
        return
    print("== %s · 声明 %d · 记录 %d 条" % (path.split("/")[-1], declared, len(recs)))
    heads = []
    for idx, (off, nm) in enumerate(recs[:12]):
        p = off + 96
        h = struct.unpack_from("<I", b, p)[0]
        second = struct.unpack_from("<I", b, p + 4)[0]
        # 从 p+8 起数「严格递增的小整数」有多长
        vals = []
        q = p + 8
        while q + 4 <= len(b):
            v = struct.unpack_from("<I", b, q)[0]
            if v > 4096 or (vals and v <= vals[-1]):
                break
            vals.append(v)
            q += 4
        nxt = recs[idx + 1][0] if idx + 1 < len(recs) else len(b)
        heads.append((nm, h, second, len(vals), nxt - p))
        print("   %-26s 头=%-6d 次=%-3d 递增串长=%-3d 到下一条记录=%d 字节"
              % (nm, h, second, len(vals), nxt - p))
    # 头与「到下一条记录的距离」「递增串长」的关系
    for nm, h, sec, nv, dist in heads[:8]:
        print("   %-26s 头=%d vs 距离=%d (差 %d) vs 8+4*串长=%d"
              % (nm, h, dist, dist - h, 8 + 4 * nv))


paths = sys.argv[1:]
if not paths:
    paths = sorted(glob.glob(".scratch/exports/**/*.mesh", recursive=True))[:6]
    paths.append(".scratch/ani/w1351_monster_xiyuqiezei_yifu_001.mesh")
for p in paths:
    probe(p.replace("\\", "/"))
