#!/usr/bin/env python3
"""给「卡半路」那两族找对照样本：同型号里有没有走得通的兄弟文件。

判据：`hier_census.tsv` 列的是**没解出**的名单，不在名单里 = 解出。
"""
import collections
import glob
import os
import re

unsolved = set()
for ln in open(".scratch/hier_census.tsv", encoding="utf-8"):
    t = ln.rstrip("\n").split("\t")
    if len(t) > 1 and t[1].endswith(".mesh"):
        unsolved.add(os.path.normpath(t[1]).replace("\\", "/"))
print("未解名单", len(unsolved), "份")

stuck = {}
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m:
        p = os.path.normpath(m.group(1).replace("\\", "/"))
        stuck[p] = (m.group(3), m.group(4), m.group(5))

for key in ("25/57", "29/30", "29/35", "25/32"):
    e, d = key.split("/")
    fam = [p for p, v in stuck.items() if v[1] == e and v[2] == d]
    print(f"\n===== 族 吃了 {key}：{len(fam)} 份 =====")
    for p in fam[:3]:
        stem = os.path.basename(p).split("_lian")[0].split("_yifu")[0]
        stem = re.sub(r"_[a-z]+_\d+\.mesh$", "", os.path.basename(p)[:-5])
        sibs = [os.path.normpath(x).replace("\\", "/") for x in glob.glob(os.path.join(os.path.dirname(p), "*.mesh"))]
        ok = [s for s in sibs if s not in unsolved]
        bad = [s for s in sibs if s in unsolved]
        print(f"  {os.path.basename(p)}  同目录 {len(sibs)} 份：解出 {len(ok)} 未解 {len(bad)}")
        for s in ok[:3]:
            print("     解出的兄弟：", os.path.basename(s))
        for s in bad[:3]:
            print("     未解的兄弟：", os.path.basename(s), stuck.get(s, "（不在卡住名单，是别的原因）"))
