#!/usr/bin/env python3
"""能不能给匿名贴图反查出名字——试 path_hash 桥。

资源库里的行分两个世界：
  带名字（src=resourcepath，2,271 张贴图，全是 ≤60px 的 WEBP 图标）
  匿名（path is null，24,261 张 BC3/RGBA32，UV 试贴的候选池就在这里面）
如果匿名行的 hash 其实是 path_hash(某条路径)，那把 mtl 点名的贴图路径代进去就能命中，
试贴从此有真答案；命不中说明 hash 是内容哈希，名字这条桥得另找。
"""
import json
import sqlite3
import sys

M32 = 0xFFFFFFFF


def path_hash(path: str) -> str:
    h1, h2 = 0x4E67C6A7, 0
    for b in path.encode():
        c = b + 32 if 65 <= b <= 90 else (ord("/") if b == 92 else b)
        h1 = (h1 ^ ((c + (h1 * 32 & M32) + (h1 >> 2)) & M32)) & M32
        h2 = (c + 65599 * h2) & M32
    return "%016x" % (h1 | (h2 << 32))


con = sqlite3.connect("file:.scratch/resources.db?mode=ro", uri=True)
c = con.cursor()

# 1) 先拿已知带名字的行验证函数本身对不对
ok = tot = 0
ex = []
for h, p in c.execute("select hash, path from resources where path is not null limit 4000"):
    tot += 1
    if path_hash(p) == h.lower():
        ok += 1
    elif len(ex) < 3:
        ex.append((h, p, path_hash(p)))
    if tot >= 4000:
        break
print(f"path_hash(库里的 path) == hash ：{ok}/{tot}")
for e in ex:
    print("   不中样本", e)

# 2) 拿 mtl 点名的贴图试各种路径写法
names = []
for n, in c.execute("select name from refs where kind in ('.tga','.dds') and name is not null"):
    names.append(n.lower())
print(f"mtl 点名的贴图字符串 {len(names)} 条（去重 {len(set(names))}）")

hashes = {h for (h,) in c.execute("select hash from resources")}
tex_anon = {h for (h,) in c.execute(
    "select hash from resources where type='texture' and path is null")}

def variants(n):
    base = n[:-4] if n.endswith(".tga") else n
    return [
        n,
        f"resource/{n}",
        f"data/source/texture/{n}",
        f"texture/{n}",
        f"data/source/npc/model/{base}/{base}.tga",
        f"{base}.tga",
        f"{base}.dds",
    ]


hits = []
for n in sorted(set(names))[:1500]:
    for cand in variants(n):
        h = path_hash(cand)
        if h in hashes:
            hits.append((n, cand, h, h in tex_anon))
print(f"命中 {len(hits)}  其中落在匿名贴图上 {sum(1 for x in hits if x[3])}")
for x in hits[:8]:
    print("   ", x)
