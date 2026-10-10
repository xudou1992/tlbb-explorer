#!/usr/bin/env python3
"""卡点那 64 字节到底是什么：同型号部件之间是否逐字节相同 + 行/列两种读法的正交性。

只读、只算，不改判据。目的：把「它是带缩放的矩阵」这个假设查实或打死。
"""
import math
import re
import struct

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m:
        rows.append(m.groups())


def path_of(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


def block(p, stop, n=64):
    with open(path_of(p), "rb") as f:
        f.seek(stop)
        return f.read(n)


def lens_dots(b):
    m = struct.unpack("<16f", b)
    r = [m[0:3], m[4:7], m[8:11]]
    c = [m[0:4:4] if False else (m[0], m[4], m[8]), (m[1], m[5], m[9]), (m[2], m[6], m[10])]

    def stats(vectors, tag):
        L = [math.sqrt(sum(x * x for x in v)) for v in vectors]
        ds = []
        for i in range(3):
            for k in range(i + 1, 3):
                d = sum(vectors[i][t] * vectors[k][t] for t in range(3))
                ds.append(d / (L[i] * L[k]) if L[i] and L[k] else float("nan"))
        print(f"    {tag}: 轴长 {', '.join(f'{x:.3f}' for x in L)} · 归一两点积 {', '.join(f'{x:+.4f}' for x in ds)}")
        return max(abs(x) for x in ds)

    print(f"    w 列 = {m[3]:.2f},{m[7]:.2f},{m[11]:.2f},{m[15]:.2f}  第4行 = {m[12]:.3f},{m[13]:.3f},{m[14]:.3f}")
    a = stats(r, "按行读(轴在行)")
    b = stats(c, "按列读(轴在列)")
    return a, b


# 同型号（同前缀、不同部件）的卡点块是否逐字节相同
by_model = {}
for p, s, st, e, d in rows:
    fn = path_of(p).split("/")[-1]
    stem = re.sub(r"_(lian|yifu|shoutao|tou|001|002|b0|b1|b2|b3)_?\d*\.mesh$", "", fn)
    by_model.setdefault((stem, e, d), []).append((p, st))

same = diff = 0
for (stem, e, d), lst in by_model.items():
    if len(lst) < 2:
        continue
    blocks = [block(p, int(st, 16)) for p, st in lst]
    if all(b == blocks[0] for b in blocks):
        same += 1
    else:
        diff += 1
print(f"同型号多部件的组：卡点 64 字节**完全相同**的组 {same}，不同的组 {diff}")

print("\n两个最大族的样本细看：")
for key in ("25/57", "29/30"):
    e, d = key.split("/")
    pick = [r for r in rows if r[3] == e and r[4] == d][:2]
    for p, s, st, ee, dd in pick:
        print(f"  {path_of(p).split('/')[-1]} 吃了 {ee}/{dd} 卡在 {hex(int(st,16))}")
        lens_dots(block(p, int(st, 16)))
