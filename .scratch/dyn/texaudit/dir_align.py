# -*- coding: utf-8 -*-
"""机器侧对齐（只读）：同干槽位的 cfg 登记目录 vs 榜首贴图由包内顺序夹出的目录。

这是「还差什么才能让人工标注最省」的关键一问：如果两条独立线索经常一致，
就能不靠人工把候选池从 1,650 缩到「同一目录里的几张」。
对照组：把榜首换成池内随机一张，看撞一致的概率（基线）。
"""
import collections
import json
import os
import random
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
RES = os.path.join(ROOT, ".scratch/uvfit_batch/results")
SLOTS = os.path.join(ROOT, ".scratch/dyn/texaudit/mesh_slots.json")
CFG = os.path.join(ROOT, ".scratch/dyn/texaudit/cfg_tex_paths.json")
POOLDIR = os.path.join(ROOT, ".scratch/dyn/texaudit/pool_dir_map.json")
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/dir_align.txt")
L = []


def say(s=""):
    L.append(str(s))


def main():
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/"), uri=True)
    slots = json.loads(open(SLOTS, encoding="utf-8").read())
    cj = json.loads(open(CFG, encoding="utf-8").read())
    cfgpath, keys = cj["cfg_registered_path_for_dangling"], cj["dangling_tex_keys"]
    pdir = json.loads(open(POOLDIR, encoding="utf-8").read())
    say("索引顺序能夹出目录的池内贴图: %d 张，目录 %d 个" % (len(pdir), len(set(pdir.values()))))

    mesh_dir = {}
    for h, p in con.execute("select hash,path from resources where type='mesh' and path is not null"):
        mesh_dir[p.replace(BS, "/").split("/")[-1].lower()] = p.replace(BS, "/").lower().rsplit("/", 1)[0]

    cases = []
    for f in sorted(os.listdir(RES)):
        v = json.loads(open(os.path.join(RES, f), encoding="utf-8").read())
        c = v.get("candidates") or []
        if not c:
            continue
        cands = sorted(c, key=lambda x: -x["adjustedScore"]) if all(x.get("adjustedScore") is not None for x in c) else c
        mesh = v["mesh"]
        stem = mesh.lower()[:-5]
        exact = [n for n in slots.get(mesh, []) if n.lower().rsplit(".", 1)[0] == stem]
        if not exact:
            continue
        n = exact[0]
        cp = cfgpath.get(n)
        md = mesh_dir.get(mesh.lower())
        cases.append((mesh, n, cp.lower().rsplit("/", 1)[0] if cp else "", md or "", cands[0]["hash"]))
    say("同干槽位 + 有榜首的样本: %d 只 mesh；其中槽位在 cfg 登记过路径的: %d 只" % (
        len(cases), sum(1 for c in cases if c[2])))

    exact_dir = parent = meshdir_eq = tot = 0
    ex = []
    for mesh, n, cdir, mdir, h in cases:
        if h not in pdir or not cdir:
            continue
        tot += 1
        td = pdir[h]
        if td == cdir:
            exact_dir += 1
            if len(ex) < 6:
                ex.append(("精确一致", mesh, n, cdir, h, td))
        elif td.rstrip("/").split("/")[-1] == cdir.rstrip("/").split("/")[-1] or cdir.startswith(td) or td.startswith(cdir):
            parent += 1
            if len(ex) < 10:
                ex.append(("近邻/父子", mesh, n, cdir, h, td))
        if mdir and td == mdir:
            meshdir_eq += 1
    say()
    say("可检样本（榜首夹得出目录 且 槽位有 cfg 目录）: %d 只" % tot)
    if tot:
        say("  榜首贴图夹出目录 == 该贴图 cfg 登记目录: %d (%.2f%%)" % (exact_dir, 100.0 * exact_dir / tot))
        say("  末段同名或父子关系: %d (%.2f%%)" % (parent, 100.0 * parent / tot))
        say("  == mesh 自己所在目录: %d (%.2f%%)" % (meshdir_eq, 100.0 * meshdir_eq / tot))
        rnd = random.Random(5)
        ks = list(pdir)
        cdirs = [c[2] for c in cases if c[2]]
        b_exact = b_near = 0
        N = 40000
        for _ in range(N):
            td = pdir[rnd.choice(ks)]
            cd = rnd.choice(cdirs)
            b_exact += 1 if td == cd else 0
            b_near += 1 if (td.split("/")[-1] == cd.split("/")[-1] or cd.startswith(td) or td.startswith(cd)) else 0
        say("  随机基线: 精确 %.2f%% / 近邻 %.2f%%" % (100.0 * b_exact / N, 100.0 * b_near / N))
    for e in ex:
        say("   %s: mesh=%s 槽位=%s cfg目录=%s 榜首=%s 夹出=%s" % e)

    # 缩小效应：如果按「cfg 目录 == 夹出目录」筛池，每只 mesh 平均剩几张
    by_dir = collections.defaultdict(list)
    for h, d in pdir.items():
        by_dir[d].append(h)
    sizes = [len(by_dir[c[2]]) for c in cases if c[2] in by_dir]
    say()
    say("若把「夹出目录==槽位 cfg 目录」当硬过滤：有可筛对象的 mesh %d 只，平均每目录 %d 张贴图（池 1,650）" % (
        len(sizes), sum(sizes) / len(sizes) if sizes else 0))
    say("槽位 cfg 目录能落进「夹出目录表」的目录数: %d / %d" % (
        len(set(c[2] for c in cases if c[2]) & set(by_dir)), len(set(c[2] for c in cases if c[2]))))
    say("⇒ 也就是说这条硬过滤今天能覆盖到的 mesh 极少，池内贴图大多夹不出目录（610/1,650）")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
