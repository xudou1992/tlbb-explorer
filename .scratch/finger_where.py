#!/usr/bin/env python3
"""关掉那条未定案：`.ani` 驱动而网格没有的 59 根手指骨，到底住在哪个文件里。

先看这一组 8 个成员各是什么，再拿手指骨的名字去每个成员文件的字节里找。
"""
import os
import sqlite3

con = sqlite3.connect("file:.scratch/resources.db?mode=ro", uri=True)
c = con.cursor()
GID = 945
rows = c.execute(
    "select a.role, a.hash, r.path, r.ext, r.type from amembers a "
    "left join resources r on r.hash = a.hash where a.gid = ? order by a.role",
    (GID,),
).fetchall()
print(f"组 {GID} 成员 {len(rows)} 个：")
for role, h, path, ext, typ in rows:
    print(f"   {role:<10} {typ or '?':<8} {path}")

NEEDLE = b"bip01_l_finger01"
TREE = ".scratch/out/tree/"
print(f"\n拿 {NEEDLE.decode()} 去这些成员文件里找：")
for role, h, path, ext, typ in rows:
    if not path:
        continue
    fp = os.path.join(".scratch/out/tree", path.replace("/", os.sep))
    if not os.path.exists(fp):
        print(f"   {role:<10} 树里没这份文件（{path}）")
        continue
    b = open(fp, "rb").read()
    hit = NEEDLE in b
    n = b.count(b"bip01_l_finger")
    print(f"   {role:<10} {os.path.basename(path):<44} 大小 {len(b):>8}  含 finger01={hit}  finger 串出现 {n} 次")

# 对照：整个树里哪些 .mesh 含 finger01（限同一目录树，别全库扫）
d = os.path.dirname(os.path.join(TREE, rows[0][2] or ""))
print(f"\n同目录 {d} 下所有文件里的 finger 计数：")
if os.path.isdir(d):
    for f in sorted(os.listdir(d)):
        fp = os.path.join(d, f)
        if os.path.isdir(fp):
            sub = fp
            for g in sorted(os.listdir(sub)):
                gb = open(os.path.join(sub, g), 'rb').read()
                print(f'      {f}/{g:<46} {gb.count(b"finger"):>4}')
            continue
        b = open(fp, "rb").read()
        print(f"   {f:<52} {b.count(b'finger'):>4}")
