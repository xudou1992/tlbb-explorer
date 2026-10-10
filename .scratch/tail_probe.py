#!/usr/bin/env python3
"""「条目已齐、尾巴后还有东西」那 38 份：把卡点到文件末尾的尾巴摊出来找结构。

长度是离散值（804/964/948/292/548…），先看是不是「计数 + 定长记录」这类形状。
"""
import collections
import os
import re
import struct

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m:
        rows.append(m.groups())
full = [r for r in rows if int(r[3]) == int(r[4])]
print("条目已齐那族", len(full), "份")

by_len = collections.defaultdict(list)
for p, s, st, e, d in full:
    fp = p.replace("\\", "/")
    i = fp.find("/.scratch/")
    fp = fp[i + 1:] if i >= 0 else fp
    by_len[os.path.getsize(fp) - int(st, 16)].append((fp, int(st, 16)))

for n in sorted(by_len, key=lambda k: -len(by_len[k]))[:4]:
    lst = by_len[n]
    print(f"\n===== 尾巴 {n} 字节：{len(lst)} 份（例 {os.path.basename(lst[0][0])}）=====")
    fp, stop = lst[0]
    tail = open(fp, "rb").read()[stop:]
    print("  头 64 字节：", tail[:64].hex(" "))
    u32 = struct.unpack(f"<{min(len(tail)//4,12)}I", tail[: min(len(tail), 48)])
    f32 = struct.unpack(f"<{min(len(tail)//4,12)}f", tail[: min(len(tail), 48)])
    print("  当 u32 读：", list(u32))
    print("  当 f32 读：", [round(x, 4) for x in f32])
    asc = "".join(chr(x) if 32 <= x < 127 else "." for x in tail[:96])
    print("  当文本读：", asc)
    # 每份的尾巴头 4 字节是否一致（同族同形状 = 结构，不是数据）
    heads = collections.Counter(open(f, "rb").read()[s:][:16].hex() for f, s in lst)
    print(f"  同长度组里头 16 字节相同的：{heads.most_common(2)}")
