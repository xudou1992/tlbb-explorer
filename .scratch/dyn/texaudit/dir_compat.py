# -*- coding: utf-8 -*-
"""把两条独立线索对上：索引顺序推出来的「贴图目录」vs uvfit 榜首。

零标注判证方法：
  · A 侧：用包内邻居夹出每张池内贴图的目录（order_probe 口径，具名行上实测 90% 准）；
  · B 侧：用 mesh -> .mdl/.mtl -> 声明的贴图名（chain_probe 口径，474 只有名）；
  如果 A、B 独立，那么「mesh 的 mtl 所在目录」与「它的榜首贴图的夹出目录」应当
  比随机更常一致。一致 ⇒ 这是能机械缩小候选池的旁证；不一致 ⇒ 如实报告它连不上。
"""
import collections
import json
import os
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
RES = os.path.join(ROOT, ".scratch/uvfit_batch/results")
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/dir_compat.txt")
SIDE = os.path.join(ROOT, ".scratch/dyn/texaudit/pool_dir_map.json")
L = []


def say(s=""):
    L.append(str(s))


def d_of(p):
    p = (p or "").replace(BS, "/").lower()
    return p.rsplit("/", 1)[0] if "/" in p else ""


def top1_of(v):
    """与后端 rank() 同口径：全部有 adjustedScore 时按它降序，否则保持缓存原序。"""
    c = v.get("candidates") or []
    if not c:
        return None
    if all(x.get("adjustedScore") is not None for x in c):
        return sorted(c, key=lambda x: -x["adjustedScore"])[0]
    return c[0]


def main():
    db = os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)

    # ---- A 侧：池内贴图的夹出目录 ----
    rows = con.execute(
        """select r.pak, r.gen, r.offset, r.hash, x.path, x.type
           from records r left join resources x on x.hash=r.hash""").fetchall()
    seq = collections.defaultdict(list)
    for pak, gen, off, h, path, typ in rows:
        seq[(pak, gen)].append((int(off), h, path, typ))
    for k in seq:
        seq[k].sort(key=lambda t: t[0])
    pool = set(r[0] for r in con.execute(
        "select hash from resources where type='texture' and path is null and width>=512 and height>=512 and codec in ('RGBA32','BC3') and mips>=4"))
    pdir = {}
    for k, lst in seq.items():
        for i, (off, h, path, typ) in enumerate(lst):
            if path is not None or typ != "texture" or h not in pool:
                continue
            prev = next((lst[j] for j in range(i - 1, -1, -1) if lst[j][2]), None)
            nxt = next((lst[j] for j in range(i + 1, len(lst)) if lst[j][2]), None)
            if not prev or not nxt:
                continue
            pd, nd = d_of(prev[2]), d_of(nxt[2])
            if pd == nd:
                pdir[h] = pd
    say("池内 1,650 张里夹得出目录的: %d 张，涉及目录 %d 个" % (len(pdir), len(set(pdir.values()))))
    say("目录分布前 12: %s" % collections.Counter(pdir.values()).most_common(12))

    # ---- B 侧：有声明贴图名的已评分 mesh，以及它 mtl 的目录 ----
    mesh2mtlpath = collections.defaultdict(set)
    for fp, tp in con.execute(
        "select from_path,to_path from relations where rel='model-part' and lower(from_path) like '%.mesh' and lower(to_path) like '%.mtl'"):
        mesh2mtlpath[fp.replace(BS, "/").split("/")[-1].lower()].add(tp.replace(BS, "/").lower())
    mtl2tex = collections.defaultdict(set)
    for fp, n in con.execute("select from_path,name from refs where kind in ('.tga','.dds','.png')"):
        mb = (fp or "").replace(BS, "/").split("/")[-1].lower()
        mtl2tex[mb].add(n)

    scored = {}
    for f in os.listdir(RES):
        v = json.loads(open(os.path.join(RES, f), encoding="utf-8").read())
        if not v.get("candidates"):
            continue
        scored[v["mesh"]] = v

    cases = []
    for mesh, v in scored.items():
        bn = mesh.lower()
        t = top1_of(v)
        if not t:
            continue
        for mp in mesh2mtlpath.get(bn, ()):
            names = mtl2tex.get(mp.replace(BS, "/").split("/")[-1], set())
            if not names:
                continue
            cases.append((mesh, d_of(mp), sorted(names), t["hash"], t.get("adjustedScore"), v.get("coverage")))
    say()
    say("有「mesh + mtl 目录 + 声明贴图名 + 榜首」四件套的样本: %d 条（覆盖 mesh %d 只）" % (
        len(cases), len(set(c[0] for c in cases))))
    say("mtl 目录分布前 10: %s" % collections.Counter(c[1] for c in cases).most_common(10))

    # ---- 一致性检验 ----
    same_dir = 0
    same_region = 0
    tot = 0
    ex_ok, ex_no = [], []
    dirs_present = set(pdir.values())
    for mesh, mdir, names, h, adj, cov in cases:
        if h not in pdir:
            continue
        tot += 1
        td = pdir[h]
        if td == mdir:
            same_dir += 1
            if len(ex_ok) < 8:
                ex_ok.append((mesh, mdir, h, td, names[:2]))
        else:
            if len(ex_no) < 8:
                ex_no.append((mesh, mdir, h, td, names[:2]))
        # region = 前两段（粗粒度）
        ra = "/".join(mdir.split("/")[:2])
        rb = "/".join(td.split("/")[:2])
        if ra == rb:
            same_region += 1
    say()
    say("可检样本（榜首贴图有夹出目录）: %d 条" % tot)
    if tot:
        say("  榜首贴图的夹出目录 == 该 mesh 的 mtl 目录: %d (%.1f%%)" % (same_dir, 100.0 * same_dir / tot))
        say("  粗粒度前两段一致: %d (%.1f%%)" % (same_region, 100.0 * same_region / tot))
        # 随机基线：把榜首换成池内随机一张有目录的贴图
        import random
        rnd = random.Random(11)
        keys = list(pdir)
        base_dir = base_reg = 0
        N = 20000
        for _ in range(N):
            d = pdir[rnd.choice(keys)]
            mdir = rnd.choice([c[1] for c in cases]) if cases else ""
            base_dir += 1 if d == mdir else 0
            base_reg += 1 if "/".join(d.split("/")[:2]) == "/".join(mdir.split("/")[:2]) else 0
        say("  随机基线（同规模下撞目录）: 精确 %.2f%% / 粗粒度 %.2f%%" % (100.0 * base_dir / N, 100.0 * base_reg / N))
    for e in ex_ok:
        say("  一致例: %s mtl=%s 榜首=%s 夹出=%s 名=%s" % e)
    for e in ex_no:
        say("  不一致例: %s mtl=%s 榜首=%s 夹出=%s 名=%s" % e)

    # ---- 目录缩小效应：如果按 mtl 目录筛池，每只能剩多少候选 ----
    say()
    say("=== 若用「夹出目录」当硬过滤，池子会缩到多小 ===")
    per_dir = collections.Counter(pdir.values())
    say("有目录的池内贴图 %d 张分布在 %d 个目录，平均每目录 %.1f 张，最大目录 %d 张" % (
        len(pdir), len(per_dir), len(pdir) / max(1, len(per_dir)), max(per_dir.values())))
    say("目录大小分布: %s" % collections.Counter(
        ("1" if v == 1 else "2-5" if v <= 5 else "6-20" if v <= 20 else ">20") for v in per_dir.values()).most_common())

    with open(SIDE, "w", encoding="utf-8") as fh:
        json.dump({h: d for h, d in sorted(pdir.items())}, fh, ensure_ascii=False, indent=1)
    say("池内贴图→夹出目录 sidecar → %s" % SIDE)

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
