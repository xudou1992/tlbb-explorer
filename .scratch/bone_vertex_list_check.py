"""验一件事：每条 96B 骨记录后面那串 [u32 N][N 个递增 u32]，是不是「这根骨影响哪些顶点」。

判据（都过才算数）：
 ① 每个值 < 文件头 0x8C 声明的顶点数 vc；
 ② 所有骨的并集覆盖大部分顶点，且每个顶点被 1~4 根骨影响（超过 4 就是别的东西）；
 ③ 换一份骨数不同的 .mesh，同一结论要重演。
"""
import glob
import math
import re
import struct
import sys
from collections import Counter

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


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
    out, i = [], 0
    while i + 96 <= len(b):
        n = name_at(b, i)
        if n is not None and matrix_at(b, i + 32) is not None:
            out.append((i, n))
            i += 96
            continue
        i += 4
    return out


def check(path):
    b = open(path, "rb").read()
    if len(b) < 0x114:
        return
    vc = struct.unpack_from("<I", b, 0x8C)[0]
    fc = struct.unpack_from("<I", b, 0x90)[0]
    sm = struct.unpack_from("<I", b, 0x94)[0]
    declared = struct.unpack_from("<I", b, 0x110)[0]
    recs = records(b)
    if len(recs) < 2:
        return
    lists = []
    for off, nm in recs:
        p = off + 96
        if p + 4 > len(b):
            continue
        n = struct.unpack_from("<I", b, p)[0]
        if n == 0 or n > 200000 or p + 4 + 4 * n > len(b):
            lists.append((nm, None))
            continue
        vals = list(struct.unpack_from("<%dI" % n, b, p + 4))
        lists.append((nm, vals))
    got = [(nm, v) for nm, v in lists if v]
    if not got:
        return
    over_vc = [(nm, max(v)) for nm, v in got if max(v) >= vc]
    union = set()
    cnt = Counter()
    for _, v in got:
        for x in v:
            union.add(x)
            cnt[x] += 1
    dist = Counter(cnt.values())
    print("== %s" % path.split("/")[-1])
    print("   vc=%d fc=%d sm=%d 声明骨=%d 记录=%d 带索引表=%d" % (vc, fc, sm, declared, len(recs), len(got)))
    print("   最大值超 vc 的骨：%s" % (over_vc[:4] if over_vc else "无"))
    print("   并集覆盖 %d/%d 顶点 = %.1f%% · 每顶点被影响骨数分布 %s"
          % (len(union), vc, 100.0 * len(union) / max(1, vc), sorted(dist.items())[:8]))
    print("   各表长度（前 10）：%s" % [len(v) for _, v in got[:10]])


paths = sys.argv[1:] or sorted(glob.glob(".scratch/exports/**/*.mesh", recursive=True))[:5]
paths.append(".scratch/ani/w1351_monster_xiyuqiezei_yifu_001.mesh")
for p in paths:
    check(p.replace("\\", "/"))
