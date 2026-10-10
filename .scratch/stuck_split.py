#!/usr/bin/env python3
"""把 186 份「卡住」按形状切三族，并量已齐那族在卡点之后还剩多少字节。

只读普查输出 + 文件大小，不改任何判据。
"""
import collections
import os
import re

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m:
        rows.append(m.groups())
print("普查行数", len(rows))


def norm(p):
    return p.replace("\\", "/").replace("/D:/", "D:/").lstrip("/")


def path_of(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


full = [r for r in rows if int(r[3]) == int(r[4])]
zero = [r for r in rows if int(r[3]) == 0]
mid = [r for r in rows if 0 < int(r[3]) < int(r[4])]
print(f"条目已齐却卡住 {len(full)} · 吃 0 条 {len(zero)} · 真卡半路 {len(mid)}")

rem = collections.Counter()
missing = 0
for p, s, st, e, d in full:
    fp = path_of(p)
    if not os.path.exists(fp):
        missing += 1
        continue
    rem[os.path.getsize(fp) - int(st, 16)] += 1
print(f"已齐那族：文件末尾在卡点之后的字节数分布 top12（读不到文件 {missing}）")
for k, v in rem.most_common(12):
    print(f"   剩 {k:>8} B × {v} 份")

z = collections.Counter()
for p, s, st, e, d in zero:
    fp = path_of(p)
    if not os.path.exists(fp):
        continue
    with open(fp, "rb") as f:
        f.seek(int(s, 16))
        head = f.read(12)
    z[head[:8].hex(" ")] += 1
print("吃 0 条那族：起点头 8 字节 top8")
for k, v in z.most_common(8):
    print(f"   {k} × {v}")

m2 = collections.Counter()
for p, s, st, e, d in mid:
    m2[(int(e) - int(d)) // 4] += 1
print("真卡半路那族：吃掉比例分桶（吃了/声明）top8")
r2 = collections.Counter()
for p, s, st, e, d in mid:
    a, b = int(e), int(d)
    r2[f"{a}/{b}"] += 1
for k, v in sorted(r2.items(), key=lambda x: -x[1])[:8]:
    print(f"   {k} × {v}")
