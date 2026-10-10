#!/usr/bin/env python3
"""38 份尾巴上那列递增整数到底是不是蒙皮索引表。

两种排法各验一次：
  A 分开存：[u32 n][n × u32 索引][n × f32 权重]      ← 我们 `tail_is_inf` 认的这种
  B 交错存：[u32 n][(u32 索引, f32 权重) × n]
判据：索引必须 < 顶点数且递增不重复；权重必须在 [0,1]。
"""
import os
import re
import struct

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m and m.group(4) == m.group(5):
        rows.append((m.group(1), int(m.group(3), 16)))

HEAD = 0x118


def fix(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


def vc_of(b):
    return struct.unpack_from("<I", b, 0x8C)[0] if len(b) > 0x90 else 0


def try_split(b, at, vc):
    n = struct.unpack_from("<I", b, at)[0]
    if not 0 < n <= 4096 or at + 4 + 8 * n > len(b):
        return None
    idx = struct.unpack_from(f"<{n}I", b, at + 4)
    w = struct.unpack_from(f"<{n}f", b, at + 4 + 4 * n)
    ok = all(x < vc for x in idx) and all(idx[i] < idx[i + 1] for i in range(n - 1))
    okw = all(x == x and -0.001 <= x <= 1.001 for x in w)
    return n, ok, okw, idx[:4], [round(x, 3) for x in w[:4]]


def try_interleaved(b, at, vc):
    n = struct.unpack_from("<I", b, at)[0]
    if not 0 < n <= 4096 or at + 4 + 8 * n > len(b):
        return None
    idx = [struct.unpack_from("<I", b, at + 4 + 8 * k)[0] for k in range(n)]
    w = [struct.unpack_from("<f", b, at + 4 + 8 * k + 4)[0] for k in range(n)]
    ok = all(x < vc for x in idx) and all(idx[i] < idx[i + 1] for i in range(n - 1))
    okw = all(x == x and -0.001 <= x <= 1.001 for x in w)
    return n, ok, okw, idx[:4], [round(x, 3) for x in w[:4]]


a_ok = b_ok = neither = 0
for p, stop in rows:
    b = open(fix(p), "rb").read()
    vc = vc_of(b)
    at = stop + 64  # 卡点那张矩阵之后
    ra = try_split(b, at, vc)
    rb = try_interleaved(b, at, vc)
    ta = "A过" if ra and ra[1] and ra[2] else "-"
    tb = "B过" if rb and rb[1] and rb[2] else "-"
    if "过" in ta:
        a_ok += 1
    if "过" in tb:
        b_ok += 1
    if "过" not in ta + tb:
        neither += 1
        if neither <= 4:
            print(f"  两式都不过 {os.path.basename(p)[:32]} n={ra[0] if ra else '?'} 顶点数={vc}")
    elif neither + a_ok + b_ok <= 6:
        r = ra if "过" in ta else rb
        print(f"  {os.path.basename(p)[:32]} {ta}{tb} n={r[0]} 索引{r[3]} 权重{r[4]} 顶点数={vc}")
print(f"\n合计 {len(rows)} 份：A 分开存过 {a_ok} · B 交错存过 {b_ok} · 两式都不过 {neither}")
