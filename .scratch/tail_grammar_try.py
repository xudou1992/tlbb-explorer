#!/usr/bin/env python3
"""尾巴语法试验：从卡点起，按 [64B 矩阵] / [A 式索引表] / [96B 记录] 循环吃，看能否恰好吃到 EOF。

这不是改判据，是先看「有没有这样一条语法能走通」——走不通就不许进判据。
"""
import collections
import os
import re
import struct

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m and m.group(4) == m.group(5):
        rows.append((m.group(1), int(m.group(3), 16)))


def fix(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


def is_mat(b, at):
    if at + 64 > len(b):
        return False
    m = struct.unpack_from("<16f", b, at)
    if not all(x == x and abs(x) < 1e7 for x in m):
        return False
    return abs(m[3]) < 1e-3 and abs(m[7]) < 1e-3 and abs(m[11]) < 1e-3 and abs(m[15] - 1.0) < 1e-3


def inf_len(b, at, vc):
    """A 式索引表在这儿的长度（吃不下回 0）。"""
    if at + 4 > len(b):
        return 0
    n = struct.unpack_from("<I", b, at)[0]
    if not 0 < n <= max(1, vc) or at + 4 + 8 * n > len(b):
        return 0
    idx = struct.unpack_from(f"<{n}I", b, at + 4)
    w = struct.unpack_from(f"<{n}f", b, at + 4 + 4 * n)
    if not all(x < vc for x in idx):
        return 0
    if not all(x == x and -0.001 <= x <= 1.001 for x in w):
        return 0
    return 4 + 8 * n


res = collections.Counter()
detail = []
for p, stop in rows:
    b = open(fix(p), "rb").read()
    vc = struct.unpack_from("<I", b, 0x8C)[0]
    at = stop
    steps = collections.Counter()
    guard = 0
    while at < len(b) and guard < 4000:
        guard += 1
        if is_mat(b, at):
            at += 64
            steps["矩阵"] += 1
            continue
        n = inf_len(b, at, vc)
        if n:
            at += n
            steps["索引表"] += 1
            continue
        if at + 96 <= len(b) and is_mat(b, at + 32):
            at += 96
            steps["96B记录"] += 1
            continue
        break
    left = len(b) - at
    res[(at == len(b), left)] += 1
    detail.append((os.path.basename(p)[:34], dict(steps), left))

print("吃到 EOF 的份数：", sum(v for k, v in res.items() if k[0]), "/", len(rows))
print("剩余字节分布：", sorted(res.items(), key=lambda x: -x[1])[:6])
print("\n前 8 份吃掉的块：")
for d in detail[:8]:
    print("  ", d)
