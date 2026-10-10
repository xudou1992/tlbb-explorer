#!/usr/bin/env python3
"""87 份真卡半路：卡点位置的对齐分布 + 名字在卡点第几个字节上。

上次 157 份的突破就是「整段错开 2 字节」，所以先量对齐，再谈别的。
"""
import collections
import os
import re

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m and 0 < int(m.group(4)) < int(m.group(5)):
        rows.append((m.group(1), int(m.group(2), 16), int(m.group(3), 16)))


def fix(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


for k in (4, 8, 16, 32, 64, 96):
    c = collections.Counter((st - s) % k for _, s, st in rows)
    top = c.most_common(3)
    print(f"(卡点-起点) mod {k:>3}：{top}")
c = collections.Counter(st % 32 for _, _, st in rows)
print("卡点绝对地址 mod 32 top5：", c.most_common(5))

# 名字出现在卡点第几个字节上（往后找 96 字节里第一个 ASCII 名字串的起点偏移）
off = collections.Counter()
none = 0
for p, s, st in rows:
    b = open(fix(p), "rb").read(st + 128) if False else open(fix(p), "rb").read()
    seg = b[st:st + 96]
    m = re.search(rb"[A-Za-z_][A-Za-z0-9_]{2,31}", seg)
    if m:
        off[m.start()] += 1
    else:
        none += 1
print(f"\n卡点往后 96 字节里第一个名字串的偏移：{off.most_common(6)} · 整段没名字 {none} 份")

# 起点本身 mod 4 的分布（对齐扫描是 2 步长，看看有没有系统性错位）
c2 = collections.Counter(s % 4 for _, s, _ in rows)
print("起点 mod 4：", c2.most_common())
