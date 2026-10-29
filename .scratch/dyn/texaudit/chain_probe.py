# -*- coding: utf-8 -*-
"""贴图名 -> 模型 的可用链（只读）：
   正确走法是 relations.rel='model-part'（mesh -> .mdl/.mtl/.ske/.ani），
   use-mtl 是 mtl -> sharematerial 模板，不是 mesh -> mtl。
   再用 refs(kind in .tga/.dds/.png) 把 mtl 声明的贴图名取出来。
"""
import collections
import json
import os
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
RES = os.path.join(ROOT, ".scratch/uvfit_batch/results")
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/chain_probe.txt")
L = []


def say(s=""):
    L.append(str(s))


def main():
    db = os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/")
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)

    say("rel 口径核对：use-mtl 两端类型 = %s" % c.execute(
        "select count(*) from relations where rel='use-mtl' and lower(from_path) like '%.mtl'").fetchone()[0])
    say("model-part 里 from 是 mesh 的边: %d" % c.execute(
        "select count(*) from relations where rel='model-part' and lower(from_path) like '%.mesh'").fetchone()[0])
    say("model-part 里 to 是 mtl 且 from 是 mesh 的边: %d" % c.execute(
        "select count(*) from relations where rel='model-part' and lower(from_path) like '%.mesh' and lower(to_path) like '%.mtl'").fetchone()[0])

    h2b = {}
    for h, p in c.execute("select hash,path from resources where path is not null"):
        b = (p or "").replace(BS, "/").split("/")[-1].lower()
        h2b.setdefault(h, set()).add(b)
    b2h = collections.defaultdict(set)
    for h, bs in h2b.items():
        for b in bs:
            b2h[b].add(h)

    # mesh basename -> 它的 mtl 的 basename
    mesh2mtl = collections.defaultdict(set)
    for fp, tp in c.execute(
        "select from_path,to_path from relations where rel='model-part' and lower(from_path) like '%.mesh' and lower(to_path) like '%.mtl'"
    ):
        mb = fp.replace(BS, "/").split("/")[-1].lower()
        tb = tp.replace(BS, "/").split("/")[-1].lower()
        mesh2mtl[mb].add(tb)
    say("有 mtl 边的 mesh（按裸名）: %d" % len(mesh2mtl))

    # mtl basename -> 声明的贴图名（未解析 hash 的那些）
    mtl2tex = collections.defaultdict(set)
    for fp, n in c.execute("select from_path,name from refs where kind in ('.tga','.dds','.png')"):
        mb = (fp or "").replace(BS, "/").split("/")[-1].lower()
        if mb.endswith(".mtl") or mb.endswith(".pu") or mb.endswith(".sfl"):
            mtl2tex[mb].add(n)

    scored = set(f[:-5] for f in os.listdir(RES))
    mesh_tex = {}
    for st in scored:
        bn = st.lower() + ".mesh"
        names = set()
        for m in mesh2mtl.get(bn, ()):
            names |= mtl2tex.get(m, set())
        if names:
            mesh_tex[st] = names
    say("已评分 %d 只 mesh 中能拿到「声明贴图名」的: %d 只" % (len(scored), len(mesh_tex)))

    # 同干率：贴图名裸干 vs mesh 裸干
    same = 0
    ex = []
    for st, names in mesh_tex.items():
        stems = set(n.lower().rsplit(".", 1)[0] for n in names)
        if st.lower() in stems or any(s == st.lower() for s in stems):
            same += 1
        if len(ex) < 8:
            ex.append((st, sorted(names)[:4]))
    say("mesh 名与某个声明贴图名逐字同干: %d / %d" % (same, len(mesh_tex)))
    for e in ex:
        say("  例 %s -> %s" % e)

    # 槽位共享度
    vote = collections.Counter()
    for st, names in mesh_tex.items():
        for n in names:
            vote[n] += 1
    dang = dict(c.execute("select name, n_refs from dangling where ext in ('.tga','.dds','.png')").fetchall())
    say("声明槽位名去重: %d；其中 dangling 有记录的: %d" % (len(vote), len([k for k in vote if k in dang])))
    say("被最多已评分 mesh 共享的槽位名 前 12: %s" % vote.most_common(12))
    say("只被 1 只 mesh 使用的槽位名: %d 个" % sum(1 for k, v in vote.items() if v == 1))
    say("dangling.n_refs 分布（全表贴图名）: %s" % collections.Counter(
        ("1" if v == 1 else "2-5" if v <= 5 else "6-20" if v <= 20 else ">20")
        for v in dang.values()).most_common())

    # 已评分 mesh 的槽位名 ∩ 候选池：如果人工标了这些名字，能带多少 mesh
    say()
    say("按槽位名标注的「带动量」（同一槽位名可被多只 mesh 声明）：")
    top = vote.most_common(12)
    for n, k in top:
        say("  %-42s 覆盖 mesh %d 只, dangling.n_refs=%s" % (n, k, dang.get(n)))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
