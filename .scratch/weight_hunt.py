"""承 bone_vertex_list_check：既然每条骨记录后面是 [u32 N][N 个递增 u32 顶点号]，
那权重在哪？三种候选一次测：
  A) 紧跟在顶点号之后的 N 个 f32（每骨一条与索引表等长的权重表）
  B) 每骨 N 个 (u32 顶点号, f32 权重) 交替——即那串「递增 u32」其实每 6 字节一个数
  C) 没有权重：那 N 个顶点就是这根骨独占（刚性）——用「同一顶点出现在多根骨」否掉
判据：A 成立时，对每个顶点把落在各骨表里的 f32 加起来应当 ≈1。
"""
import glob
import math
import re
import struct
from collections import Counter, defaultdict

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


def look(path):
    b = open(path, "rb").read()
    if len(b) < 0x114:
        return
    vc = struct.unpack_from("<I", b, 0x8C)[0]
    recs = records(b)
    if len(recs) < 3:
        return
    tables = []
    for off, nm in recs:
        p = off + 96
        if p + 4 > len(b):
            continue
        n = struct.unpack_from("<I", b, p)[0]
        if n == 0 or n > 5000 or p + 4 + 4 * n > len(b):
            continue
        vals = list(struct.unpack_from("<%dI" % n, b, p + 4))
        if max(vals) >= vc:
            continue
        q = p + 4 + 4 * n
        floats = list(struct.unpack_from("<%df" % n, b, q)) if q + 4 * n <= len(b) else []
        tables.append((nm, vals, floats))
    if not tables:
        return
    # A：紧跟的 f32 是否像权重（0~1、非零、和≈1）
    ok_range = [t for t in tables if t[2] and all(0.0 <= v <= 1.0001 and math.isfinite(v) for v in t[2])]
    print("== %s · vc=%d · 记录 %d · 认出的索引表 %d · 其中后面 f32 全在 0~1 的 %d"
          % (path.split("/")[-1], vc, len(recs), len(tables), len(ok_range)))
    if ok_range:
        acc = defaultdict(float)
        for nm, vals, fl in ok_range:
            for v, f in zip(vals, fl):
                acc[v] += f
        s = Counter(round(x, 2) for x in acc.values())
        print("   按 A 累加每个顶点的权重，取值分布前 8：%s" % s.most_common(8))
    for nm, vals, fl in tables[:4]:
        print("   %-26s 顶点号 %d 个（%s…）后随 f32：%s"
              % (nm, len(vals), vals[:6], [round(x, 4) for x in fl[:6]] if fl else "无"))


for p in sorted(glob.glob(".scratch/exports/**/*.mesh", recursive=True)) + \
     glob.glob(".scratch/ani/*.mesh") + glob.glob(".scratch/bug-audit-20260928/**/effectmodel/*.mesh", recursive=True):
    look(p.replace("\\", "/"))
