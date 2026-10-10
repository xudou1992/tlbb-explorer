#!/usr/bin/env python3
"""抽样本：客户端 mtl 点名的贴图，在资源库里到底是哪一行（有名字/匿名、什么编码、多大）。

只看事实不打分。目的：判断 UV 池（SQL 里 path is null + ≥512 + BC3/RGBA32 + mips≥4）
到底有没有把这些「真答案」筛掉。
"""
import collections
import json
import os
import sqlite3

con = sqlite3.connect("file:.scratch/resources.db?mode=ro", uri=True)
c = con.cursor()

rows = [
    json.loads(ln)
    for ln in open(".scratch/uvfit_batch/manifest.json", encoding="utf-8")
    if ln.strip().startswith("{") and "mesh" in ln
]

tex = collections.defaultdict(list)
for h, n, codec, w, hh, named, pth in c.execute(
    "select hash, name, codec, width, height, named, path from resources "
    "where name like '%.tga' or name like '%.dds' or name like '%.png'"
):
    tex[n.lower()].append((h, codec, w, hh, named, pth))

print("带名字贴图行的编码分布：", collections.Counter(x[1] for v in tex.values() for x in v).most_common())
big = [x for v in tex.values() for x in v if (x[2] or 0) >= 512 and (x[3] or 0) >= 512]
print(f"带名字且 ≥512 的行：{len(big)}  其中 BC3/RGBA32 {sum(1 for x in big if x[1] in ('BC3','RGBA32'))}")

m2mtl = collections.defaultdict(list)
for fp, th, tp in c.execute("select from_path, to_hash, to_path from relations where rel='use-mtl'"):
    if fp:
        m2mtl[fp.lower()].append((th, tp))

n_res = n_unres = 0
for g in ("high", "unknown"):
    print(f"\n===== {g} =====")
    for r in [x for x in rows if x.get("gradedV2") == g][:6]:
        stem = r["mesh"].lower()
        mtl = m2mtl.get(stem) or [v for k, v in m2mtl.items() if k.endswith("/" + stem)]
        if not mtl:
            print(f"  {r['mesh']}  无 use-mtl 边")
            continue
        names = set()
        for mh, _ in mtl:
            for (n,) in c.execute(
                "select name from refs where from_hash=? and kind in ('.tga','.dds','.png')", (mh,)
            ):
                if n:
                    names.add(n.lower())
        got = [n for n in names if tex.get(n)]
        lost = [n for n in names if not tex.get(n)]
        n_res += len(got)
        n_unres += len(lost)
        detail = [(n, tex[n][:2]) for n in got][:3]
        print(f"  {r['mesh']}  声明 {len(names)}（解出 {len(got)}／库里没有 {len(lost)}）")
        for n, d in detail:
            print(f"      {n} -> {d}")
        if lost:
            print(f"      库里没有的样本：{lost[:3]}")

print(f"\n合计：点名的贴图能查到行的 {n_res} 个名字，查不到行的 {n_unres} 个名字")
