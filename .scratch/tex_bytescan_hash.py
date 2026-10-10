#!/usr/bin/env python3
"""在解出来的文件字节里暴力扫匿名贴图 hash（8 字节小端，8 种对齐）。
命中 = 客户端文件里直接写了这批贴图的身份，归属证据就有了。
"""
import os
import random
import sqlite3
import struct

con = sqlite3.connect("file:.scratch/resources.db?mode=ro", uri=True)
c = con.cursor()
ANON = {bytes.fromhex(h)[::-1] for (h,) in c.execute(
    "select hash from resources where type='texture' and path is null")}
POOL = {bytes.fromhex(h)[::-1] for (h,) in c.execute(
    "select hash from resources where type='texture' and path is null and width>=512 "
    "and height>=512 and codec in ('RGBA32','BC3') and mips>=4")}
print(f"匿名贴图 {len(ANON)}  UV 池 {len(POOL)}")

TREE = ".scratch/out/tree"
files = []
for dp, _, fns in os.walk(TREE):
    for f in fns:
        if f.lower().endswith((".mtl", ".mdl", ".mesh", ".ske", ".pu", ".ani")):
            files.append(os.path.join(dp, f))
print("树里可扫文件", len(files))
random.seed(3)
samp = random.sample(files, 400 if len(files) > 400 else len(files))

hits = {}
tot_bytes = 0
for p in samp:
    b = open(p, "rb").read()
    tot_bytes += len(b)
    found = []
    for i in range(len(b) - 7):
        k = b[i:i + 8]
        if k in ANON:
            found.append((i, k[::-1].hex()))
    if found:
        hits[p] = found[:6]
print(f"扫了 {len(samp)} 份 / {tot_bytes/1e6:.1f} MB，命中文件 {len(hits)}")
for p, v in list(hits.items())[:10]:
    print("  ", os.path.relpath(p, TREE), v, "其中在 UV 池内",
          sum(1 for _, h in v if bytes.fromhex(h)[::-1] in POOL))
