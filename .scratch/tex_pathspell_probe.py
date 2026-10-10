#!/usr/bin/env python3
"""匿名贴图的反查试验：它们的 hash 很可能就是 path_hash(真实路径)，只是 ResourcePath.cfg
没登记这些路径，所以库里显示 path is null。
如果是这样，用 mtl 自己所在的目录 + mtl 点名的贴图文件名拼出路径，哈希一算就该撞上。
"""
import json
import os
import random
import sqlite3

M32 = 0xFFFFFFFF


def path_hash(path: str) -> str:
    h1, h2 = 0x4E67C6A7, 0
    for b in path.encode():
        c = b + 32 if 65 <= b <= 90 else (47 if b == 92 else b)
        h1 = (h1 ^ ((c + (h1 * 32 & M32) + (h1 >> 2)) & M32)) & M32
        h2 = (c + 65599 * h2) & M32
    return "%016x" % (h1 | (h2 << 32))


con = sqlite3.connect("file:.scratch/resources.db?mode=ro", uri=True)
c = con.cursor()
ALL = {h for (h,) in c.execute("select hash from resources")}
ANON_TEX = {
    h
    for (h,) in c.execute("select hash from resources where type='texture' and path is null")
}

# 带路径的 mtl 行：看引擎登记的路径长什么样（拼路径时要照这个写法）
named_mtl = list(
    c.execute("select hash, path from resources where ext='.mtl' and path is not null limit 5")
)
print("带路径的 mtl 行样本：")
for h, p in named_mtl:
    print(f"   {p}  hash={h}  复算={path_hash(p)}  {'中' if path_hash(p) == h else '不中'}")
print("带路径的 mtl 总数", list(c.execute("select count(*) from resources where ext='.mtl' and path is not null"))[0][0])

# 抽 300 份 mtl：拿它的 refs 点名 + 它在 out/tree 里的真实目录，拼各种写法试
rows = list(
    c.execute(
        "select from_hash, from_path, name, kind from refs "
        "where kind in ('.tga','.dds') and name is not null and from_path is not null"
    )
)
random.seed(7)
samp = random.sample(rows, 300)

hits = []
tried = 0
for fh, fp, name, kind in samp:
    d = os.path.dirname(fp.lower())
    n = name.lower()
    cands = [
        f"{d}/{n}",
        n,
        f"data/{d}/{n}",
        f"source/{d}/{n}",
        f"{d}/{os.path.basename(n)}",
    ]
    for cand in cands:
        tried += 1
        h = path_hash(cand)
        if h in ALL:
            hits.append((fp, n, cand, h, h in ANON_TEX))
print(f"\n试了 {tried} 个拼法，命中库里的 {len(hits)}  其中落在匿名贴图上的 {sum(1 for x in hits if x[4])}")
for x in hits[:6]:
    print("   ", x)

# 反向确认：mtl 自己所在的目录在库里是以什么路径登记的（决定拼接前缀）
print("\n同目录已登记的文件（看前缀写法）：")
for fh, fp, name, kind in samp[:3]:
    d = os.path.dirname(fp.lower())
    ex = list(c.execute("select path, ext, type from resources where path like ? limit 4", (d + "/%",)))
    print(f"   {fp} 目录里登记的行：{ex}")
