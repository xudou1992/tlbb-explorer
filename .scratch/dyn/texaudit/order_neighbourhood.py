# -*- coding: utf-8 -*-
"""现场摊开：池内匿名贴图的包内邻居到底长什么样（只读）。"""
import collections
import os
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/order_neighbourhood.txt")
L = []


def say(s=""):
    L.append(str(s))


def d_of(p):
    p = (p or "").replace(BS, "/").lower()
    return p.rsplit("/", 1)[0] if "/" in p else ""


def main():
    db = os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)

    say("=== 路径形状普查：有没有「目录是一段 hash」的路径 ===")
    shapes = collections.Counter()
    weird = []
    for (p,) in con.execute("select path from resources where path is not null"):
        q = (p or "").replace(BS, "/")
        parts = q.split("/")
        shapes[len(parts)] += 1
        if len(parts) > 1 and len(parts[-2]) >= 12 and all(ch in "0123456789abcdef" for ch in parts[-2].lower()):
            if len(weird) < 8:
                weird.append(p)
    say("路径段数分布: %s" % sorted(shapes.items())[:12])
    say("父目录像 hash 的路径样例: %s" % weird)
    say("父目录像 hash 的路径样例数（上面已列）: %d" % len(weird))

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
    say()
    say("=== 12 张池内贴图的左右邻居现场 ===")
    shown = 0
    for k, lst in seq.items():
        for i, (off, h, path, typ) in enumerate(lst):
            if path is not None or h not in pool or shown >= 12:
                continue
            prev = [lst[j] for j in range(max(0, i - 3), i)]
            nxt = [lst[j] for j in range(i + 1, min(len(lst), i + 4))]
            say("  [%s/%s @%d] 本行 hash=%s type=%s" % (k[0], k[1], off, h, typ))
            for p in prev:
                say("      前 %s %-14s %s" % (p[0], p[3], p[2]))
            say("      >>> 匿名贴图")
            for n in nxt:
                say("      后 %s %-14s %s" % (n[0], n[3], n[2]))
            shown += 1
        if shown >= 12:
            break

    say()
    say("=== 匿名贴图的邻居类型构成（决定严格口径为什么这么小）===")
    typ_cnt = collections.Counter()
    dist = collections.Counter()
    for k, lst in seq.items():
        for i, (off, h, path, typ) in enumerate(lst):
            if path is not None or typ != "texture":
                continue
            for j, gap in ((-1, 1), (1, 1)):
                s = i + j * gap
                if 0 <= s < len(lst):
                    typ_cnt[lst[s][3] or "(无 resources 行)"] += 1
            # 紧邻（差 1 个 offset 位）是不是同类
            near_same = 0
            s = i - 1
            while s >= 0 and lst[s][2] is None and lst[s][3] == "texture":
                near_same += 1
                s -= 1
            s = i + 1
            while s < len(lst) and lst[s][2] is None and lst[s][3] == "texture":
                near_same += 1
                s += 1
            dist[min(near_same, 20)] += 1
    say("匿名贴图的直接邻居类型: %s" % typ_cnt.most_common(8))
    say("同一匿名贴图连成的「连段」长度分布(0=孤立): %s" % sorted(dist.items())[:14])

    say()
    say("=== 有路径的贴图（named，2,259 张）在索引里是连段还是散点 ===")
    tex_named_runs = collections.Counter()
    for k, lst in seq.items():
        i = 0
        while i < len(lst):
            if lst[i][3] == "texture":
                j = i
                kinds = []
                while j < len(lst) and lst[j][3] == "texture":
                    kinds.append("named" if lst[j][2] else "anon")
                    j += 1
                tex_named_runs["".join("N" if x == "named" else "A" for x in kinds)[:24]] += 1
                i = j
            else:
                i += 1
    say("贴图连段的 N/A 形状前 12: %s" % tex_named_runs.most_common(12))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
