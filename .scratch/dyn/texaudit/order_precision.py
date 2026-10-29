# -*- coding: utf-8 -*-
"""包内顺序旁证的**零标注精度实测**（只读）：
   拿有路径的行当考题——它的左右邻居（同 pak/gen、按 offset）如果目录一致，
   那「继承这个目录」这条规则在它有路径的样本上准不准？准多少？
   再用同一规则去夹匿名贴图，看池内 1,650 张能拿到目录的有多少、
   每个目录里候选名有几个（候选名来自 dangling/refs 的注册名）。

副产品：如果精度够高，这就是「人工标注最省」的新杠杆——
15 条标在 15 个不同目录上，验的是规则本身，规则一旦立住可以机械带动一大批。
"""
import collections
import json
import os
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/order_precision.txt")
SIDE = os.path.join(ROOT, ".scratch/dyn/texaudit/anon_dir_candidates.json")
L = []


def say(s=""):
    L.append(str(s))


def d_of(p):
    p = (p or "").replace(BS, "/").lower()
    return p.rsplit("/", 1)[0] if "/" in p else ""


def main():
    db = os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)

    # 全量记录（records 是包索引，含没有 resources 行的）
    rows = con.execute(
        """select r.pak, r.gen, r.offset, r.hash, x.path, x.type
           from records r left join resources x on x.hash=r.hash"""
    ).fetchall()
    say("records×resources 行: %d" % len(rows))
    seq = collections.defaultdict(list)
    for pak, gen, off, h, path, typ in rows:
        seq[(pak, gen)].append((int(off), h, path, typ))
    for k in seq:
        seq[k].sort(key=lambda t: t[0])

    # ---- 1. 精度：有路径的行，两侧最近有名邻居目录一致时，自己是否同目录 ----
    hit = tot = 0
    by_pak = collections.Counter()
    by_pak_tot = collections.Counter()
    tex_hit = tex_tot = 0
    run_hit = run_tot = 0      # 邻居与自己同类型（贴图夹贴图）时
    for k, lst in seq.items():
        for i, (off, h, path, typ) in enumerate(lst):
            if path is None:
                continue
            prev = next((lst[j] for j in range(i - 1, -1, -1) if lst[j][2]), None)
            nxt = next((lst[j] for j in range(i + 1, len(lst)) if lst[j][2]), None)
            if not prev or not nxt:
                continue
            pd, nd = d_of(prev[2]), d_of(nxt[2])
            if pd != nd:
                continue
            tot += 1
            by_pak_tot[k[0]] += 1
            ok = d_of(path) == pd
            hit += 1 if ok else 0
            if typ == "texture":
                tex_tot += 1
                tex_hit += 1 if ok else 0
                if prev[3] == "texture" and nxt[3] == "texture":
                    run_tot += 1
                    run_hit += 1 if ok else 0
    say("【全类型】邻居目录一致时规则可判: %d 行，继承正确 %d 行 (%.2f%%)" % (tot, hit, 100.0 * hit / max(1, tot)))
    say("【只算贴图行】: %d 行，正确 %d (%.2f%%)" % (tex_tot, tex_hit, 100.0 * tex_hit / max(1, tex_tot)))
    say("【贴图行且两侧邻居也是贴图】: %d 行，正确 %d (%.2f%%)" % (run_tot, run_hit, 100.0 * run_hit / max(1, run_tot)))
    say("分 pak 正确率: %s" % {p: "%d/%d" % (by_pak[p], by_pak_tot[p]) for p in by_pak})

    # ---- 2. 拿规则去夹匿名贴图（含两侧都是同类的严格版）----
    strict = collections.defaultdict(list)   # dir -> [hash,...]
    loose = collections.defaultdict(list)
    pool = set(r[0] for r in con.execute(
        "select hash from resources where type='texture' and path is null and width>=512 and height>=512 and codec in ('RGBA32','BC3') and mips>=4"))
    in_pool_strict = in_pool_loose = 0
    anon_tex_total = 0
    for k, lst in seq.items():
        for i, (off, h, path, typ) in enumerate(lst):
            if path is not None or typ != "texture":
                continue
            anon_tex_total += 1
            prev = next((lst[j] for j in range(i - 1, -1, -1) if lst[j][2]), None)
            nxt = next((lst[j] for j in range(i + 1, len(lst)) if lst[j][2]), None)
            if not prev or not nxt:
                continue
            pd, nd = d_of(prev[2]), d_of(nxt[2])
            if pd != nd:
                continue
            loose[h].append(pd)
            if prev[3] == "texture" and nxt[3] == "texture":
                strict[h].append(pd)
            if h in pool:
                if prev[3] == "texture" and nxt[3] == "texture":
                    in_pool_strict += 1
                in_pool_loose += 1
    say()
    say("=== 用规则夹匿名贴图 ===")
    say("匿名贴图行: %d" % anon_tex_total)
    say("宽松（两侧有名且同目录）拿到目录的贴图: %d 张（其中池内 %d 张）" % (len(loose), in_pool_loose))
    say("严格（两侧也都是贴图）拿到目录的贴图: %d 张（其中池内 %d 张）" % (len(strict), in_pool_strict))
    say("严格口径下目录数: %d" % len(strict))
    top = sorted(((len(v), d) for d, v in strict.items()), reverse=True)[:15]
    say("按张数排前 15 个目录: %s" % top)

    # ---- 3. 目录里有哪些「注册过但没本体」的贴图名（dangling/refs）----
    names = con.execute("select distinct name from refs where to_hash is null and kind in ('.tga','.dds','.png')").fetchall()
    bn = [n[0].replace(BS, "/").lower() for n in names]
    say()
    say("=== 悬空贴图名的目录归属可查性 ===")
    say("悬空贴图名去重: %d；其中名字自带目录分隔符的: %d" % (len(bn), sum(1 for x in bn if "/" in x)))
    say("裸名（无目录信息）占比: %.1f%%" % (100.0 * sum(1 for x in bn if "/" not in x) / len(bn)))
    # dangling 表里有没有目录列？
    cols = [r[1] for r in con.execute("pragma table_info(dangling)")]
    say("dangling 列: %s（没有目录列 → 名字本身不带目录就不能按目录分桶）" % cols)

    with open(SIDE, "w", encoding="utf-8") as fh:
        json.dump({"strict_dir_of_anon_texture": {d: sorted(v) for d, v in sorted(strict.items())}},
                  fh, ensure_ascii=False, indent=1)
    say("sidecar（目录→该目录里被夹出的匿名贴图 hash）→ %s" % SIDE)

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
