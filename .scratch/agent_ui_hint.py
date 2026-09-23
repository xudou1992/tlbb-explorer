"""只读补充统计：
 (1) 「立体模型」区块出现/隐藏时，界面上到底有没有一句解释（canDo 口径）
 (2) 面板出现的组里，画出来的是不是这条资产自己的网格（张冠李戴度量）
输出 D:\TLGL\.scratch\agent_ui_hint.txt
"""
import os
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

con = sqlite3.connect(r"file:D:/TLGL/.scratch/resources.db?mode=ro", uri=True)
res = {}
for h, p, n, e in con.execute("select hash, path, name, ext from resources"):
    cur = res.get(h)
    if cur is None or (not cur[0] and p):
        res[h] = (p or "", n or "", e or "")
members = defaultdict(list)
for gid, h, role in con.execute("select gid, hash, role from amembers"):
    members[gid].append((role, h))
refs_by = defaultdict(list)
for fh, n, k, th in con.execute("select from_hash, name, kind, to_hash from refs"):
    refs_by[fh].append((n, k, th))
groups = list(con.execute("select id, stem, kind, n, n_mesh, n_mtl, n_ske, n_ani, n_tex from agroups"))
out = []
def w(s=""): out.append(str(s))

hint = Counter()
mismatch = Counter()
mm_examples = []
mdl_variants = Counter()
for gid, stem, kind, n, n_mesh, n_mtl, n_ske, n_ani, n_tex in groups:
    rows = sorted([(ro, res.get(h, ("", "", ""))[0], h) for ro, h in members.get(gid, [])],
                  key=lambda x: (x[0], x[1]))
    paths = [p for _r, p, _h in rows if p]
    mdl = next(((p, h) for (_ro, p, h) in rows if p.lower().endswith(".mdl")), None)
    mdl_paths = [p for p in paths if p.lower().endswith(".mdl")]
    has_tex = n_tex > 0 or any(p.lower().endswith((".tga", ".dds", ".png", ".jpg", ".jpeg", ".bmp", ".webp")) for p in paths)
    if mdl is None:
        hits = 0
    else:
        mr = [(nm, th) for (nm, k, th) in refs_by.get(mdl[1], []) if k == ".mesh"]
        hits = sum(1 for _nm, th in mr if th)
    # inspector.rs:566-575 的 canDo 口径 + detail.js:168 的隐藏规则
    if hits > 0:
        hint["面板出现，且明说「立体预览（N 个网格）」"] += 1
    elif n_mesh > 0:
        hint["面板隐藏，但 canDo 会说「立体预览：这些网格没对上文件」"] += 1
    elif has_tex:
        hint["面板隐藏，无 3D 相关提示（只有贴图预览等）"] += 1
    else:
        hint["面板隐藏，且「还能看什么」整块被 hidden：屏幕上没有任何解释"] += 1
    # 张冠李戴：面板出现时，首个网格是否落在本资产目录下 / 文件名是否含本组 stem
    if hits > 0:
        nmdl = len(mdl_paths)
        mdl_variants[nmdl] += 1
        first = next(((nm, th) for (nm, k, th) in refs_by.get(mdl[1], []) if k == ".mesh" and th), None)
        fp = res.get(first[1], ("", "", ""))[0]
        if stem and stem.lower() not in os.path.basename(fp).lower():
            mismatch["首个网格文件名不含本组茎名（画的是别的东西）"] += 1
            if len(mm_examples) < 10:
                mm_examples.append((gid, stem, kind, mdl[0], fp))
        else:
            mismatch["首个网格与本组同名"] += 1

w("=== 3D 面板出现/隐藏时界面给了什么话（按 13,080 组） ===")
for k, v in hint.most_common():
    w(f"  {v:6d}  {v*100.0/len(groups):5.1f}%  {k}")
w("")
w("=== 面板出现的组：画的网格与所选资产是否同一个东西 ===")
for k, v in mismatch.most_common():
    w(f"  {v:6d}  {k}")
w("  样本（组名 → 实际渲染的网格）：")
for gid, stem, kind, mp, fp in mm_examples:
    w(f"   gid={gid} [{kind}] {stem}")
    w(f"      用的 .mdl = {mp}")
    w(f"      实际画   = {fp}")
w("")
w(f"面板出现的组里，组内 .mdl 个数分布（>1 时后端只取 path 字典序最小那个）：{sorted(mdl_variants.items())}")
Path(r"D:\TLGL\.scratch\agent_ui_hint.txt").write_text("\n".join(out), encoding="utf-8")
print("written")
