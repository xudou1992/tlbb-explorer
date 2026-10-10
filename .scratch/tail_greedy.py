#!/usr/bin/env python3
"""38 份「只差尾巴」的尾巴到底由什么排成：从卡点贪心吃 64B 矩阵，看断在哪。"""
import collections
import os
import re
import struct

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m:
        rows.append(m.groups())
full = [(p, int(st, 16), int(e), int(d)) for p, s, st, e, d in rows if int(e) == int(d)]


def fix(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


def mat(b, at):
    if at + 64 > len(b):
        return False
    m = struct.unpack("<16f", b[at:at + 64])
    if not all(x == x and abs(x) < 1e7 for x in m):
        return False
    if abs(m[3]) > 1e-3 or abs(m[7]) > 1e-3 or abs(m[11]) > 1e-3 or abs(m[15] - 1.0) > 1e-3:
        return False
    return True


stats = collections.Counter()
for p, stop, e, d in full:
    path = fix(p)
    b = open(path, "rb").read()
    n = len(b) - stop
    k = 0
    at = stop
    while mat(b, at):
        at += 64
        k += 1
    left = len(b) - at
    stats[(k, left % 64 if left else 0, left)] += 1
    if k == 0:
        stats[("头一块就不是矩阵", os.path.basename(path)[-28:], left)] += 1

print("尾巴里连续吃掉的 64B 矩阵块数 k · 剩下字节：")
for key, v in sorted(stats.items(), key=lambda x: -x[1])[:12]:
    print("  ", key, "×", v)
