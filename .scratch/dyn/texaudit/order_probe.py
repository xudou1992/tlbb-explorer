# -*- coding: utf-8 -*-
"""没被记录在案的旁证：pak 索引里的**存放顺序**是否按路径字典序。

如果按路径排，那么一条匿名条目在顺序上夹在两条有名条目之间时，它的目录就被
两侧的目录夹出来（同目录兄弟）——不需要任何人工标注就能给匿名贴图定目录，
再和 dangling 的贴图名做交集，搜索空间从 24,261 张掉到「某个目录里的若干张」。
本脚本只做判证：用 57,274 条**有路径**的行，看按 (pak, gen, offset) 排出来的序列
里路径是不是有序的（目录游程数 / 相邻路径的公共前缀长度 / 目录变化次数）。

纪律：resources.db 只读；只写本目录。
"""
import collections
import os
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/order_probe.txt")
L = []


def say(s=""):
    L.append(str(s))


def main():
    db = os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        con.execute("update resources set width=width")
        say("!! 只读闸门失效")
        return
    except Exception as e:
        say("只读闸门：%s" % e)

    say("=== A. 有路径行按 (pak, offset) 排序后的目录游程 ===")
    rows = con.execute(
        "select pak, gen, offset, path, hash from resources where path is not null order by pak, gen, offset"
    ).fetchall()
    say("有路径行数（按 pak,offset 排好）: %d" % len(rows))
    per_pak = collections.defaultdict(list)
    for pak, gen, off, path, h in rows:
        per_pak[pak].append((int(off), path.replace(BS, "/").lower()))

    total_runs = 0
    total_items = 0
    for pak, lst in sorted(per_pak.items()):
        lst.sort()
        dirs = [p.rsplit("/", 1)[0] if "/" in p else "" for _o, p in lst]
        runs = 1 + sum(1 for i in range(1, len(dirs)) if dirs[i] != dirs[i - 1])
        distinct = len(set(dirs))
        total_runs += runs
        total_items += len(lst)
        say("  %s: 行 %6d  目录游程 %6d  目录去重 %5d  游程/去重 %.2f" % (
            pak, len(lst), runs, distinct, runs / max(1, distinct)))
    say("  合计游程 %d / 行 %d（若按路径排序，游程数应≈目录数；乱序则≈行数）" % (total_runs, total_items))

    say()
    say("=== B. 相邻有名条目的路径公共前缀（排序后）===")
    # 对每个 pak，看按 offset 相邻的两条路径的目录相同率
    same_dir = 0
    tot = 0
    pref = []
    for pak, lst in per_pak.items():
        lst.sort()
        for i in range(1, len(lst)):
            a = lst[i - 1][1]
            b = lst[i][1]
            da = a.rsplit("/", 1)[0] if "/" in a else ""
            db_ = b.rsplit("/", 1)[0] if "/" in b else ""
            tot += 1
            same_dir += 1 if da == db_ else 0
            k = 0
            while k < min(len(a), len(b)) and a[k] == b[k]:
                k += 1
            pref.append(k)
    say("相邻两条同目录的比例: %.2f%%（%d/%d）；若索引完全按路径字典序，这个值应远高于随机" % (
        100.0 * same_dir / tot, same_dir, tot))
    pref.sort()
    say("相邻公共前缀长度 p50=%d p90=%d max=%d" % (pref[len(pref) // 2], pref[int(len(pref) * 0.9)], pref[-1]))

    say()
    say("=== C. 对照组：随机打乱后的同目录率（基准线）===")
    import random
    rnd = random.Random(7)
    exp = 0.0
    for pak, lst in per_pak.items():
        paths = [p.rsplit("/", 1)[0] if "/" in p else "" for _o, p in lst]
        cnt = collections.Counter(paths)
        n = len(paths)
        if n > 1:
            exp += sum(v * (v - 1) for v in cnt.values()) / (n * (n - 1)) * (n - 1)
    say("随机相邻同目录的期望条数: %.0f / %d（%.2f%%）" % (exp, tot, 100.0 * exp / tot))
    say("实测 %.2f%% ⇒ 顺序里%s携带路径信息" % (
        100.0 * same_dir / tot, "确实" if same_dir / tot > 3 * (exp / tot) else "没有"))

    say()
    say("=== D. 若有序：匿名条图能白捡多少目录 ===")
    # 用 records 表补全（含没有 resources 行的记录），看匿名贴图在 (pak,offset) 序列里的邻居
    all_rows = con.execute(
        """select r.pak, r.gen, r.offset, (select path from resources x where x.hash=r.hash limit 1),
                  (select type from resources x where x.hash=r.hash limit 1)
           from records r order by r.pak, r.gen, r.offset"""
    ).fetchall()
    say("records 行: %d" % len(all_rows))
    seq = collections.defaultdict(list)
    for pak, gen, off, path, typ in all_rows:
        seq[(pak, gen)].append((int(off), path, typ))
    bracketed = 0
    tex_anon = 0
    agree = 0
    for key, lst in seq.items():
        lst.sort(key=lambda x: x[0])
        for i, (off, path, typ) in enumerate(lst):
            if path is not None:
                continue
            if typ != "texture":
                continue
            tex_anon += 1
            prev = next((lst[j][1] for j in range(i - 1, -1, -1) if lst[j][1]), None)
            nxt = next((lst[j][1] for j in range(i + 1, len(lst)) if lst[j][1]), None)
            if prev and nxt:
                pd = prev.replace(BS, "/").lower().rsplit("/", 1)[0]
                nd = nxt.replace(BS, "/").lower().rsplit("/", 1)[0]
                if pd == nd:
                    bracketed += 1
                    agree += 1
                elif pd.startswith(nd) or nd.startswith(pd):
                    bracketed += 1
    say("匿名贴图（records 有行、resources.path 空）: %d" % tex_anon)
    say("两侧邻居目录一致（可继承目录）: %d (%.1f%%)" % (bracketed, 100.0 * bracketed / max(1, tex_anon)))

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
