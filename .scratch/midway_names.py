#!/usr/bin/env python3
"""87 份「真卡半路」：卡点附近有没有**长得像骨名**的串。

若有，说明是名字判据（长度/字符集/成对）把它们挡在条目外——那是可修的；
若全是浮点，那卡点前头还有一层没建模的结构，跟 38 份那族同病。
"""
import collections
import os
import re

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m and 0 < int(m.group(4)) < int(m.group(5)):
        rows.append((m.group(1), int(m.group(3), 16), int(m.group(4)), int(m.group(5))))
print("真卡半路", len(rows), "份")


def fix(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


def names_near(b, at, win=48):
    seg = b[max(0, at - win):at + win]
    return [s.decode("ascii", "replace") for s in re.findall(rb"[A-Za-z_][A-Za-z0-9_]{2,31}", seg)]


with_name = collections.Counter()
no_name = 0
for p, stop, e, d in rows:
    b = open(fix(p), "rb").read()
    ns = names_near(b, stop)
    if ns:
        with_name[tuple(sorted(set(ns))[:3])] += 1
    else:
        no_name += 1
        if no_name <= 5:
            print(f"  卡点附近没名字 {os.path.basename(p)[:34]} 吃了 {e}/{d} 卡点 16B={b[stop:stop+16].hex(' ')}")
print(f"\n卡点 ±48 字节里**有**名字样字符串的份数：{sum(with_name.values())} · 没有的：{no_name}")
print("最常见的名字（前 10）：")
for k, v in with_name.most_common(10):
    print(f"   {v:>3} × {k}")
