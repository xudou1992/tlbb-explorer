#!/usr/bin/env python3
"""试贴召回率：拿客户端自己点名的贴图当标准答案，量 UV 度量把它排到第几。

链路（resources.db，只读）：
  .mesh --relations(use-mtl)--> .mtl --refs--> 贴图名 --resources.name--> 贴图 hash
为什么不能走 refs.to_hash：.tga 的 30,585 条 ref 里只有 25 条解出 hash，
名字几乎全悬空，所以答案只能按「名字在资源库里有没有这一份」来认。

候选榜只有前 10（pool 上千），所以「不在榜」只能说「没进前十」，不能说「排第 800」。
分档看（high/mid/low/unknown）就能分清「度量把对的排上去了」和「度量根本没见过对的」。
"""
import collections
import json
import os
import sqlite3
import statistics

DB = ".scratch/resources.db"
RESULTS = ".scratch/uvfit_batch/results"
MANIFEST = ".scratch/uvfit_batch/manifest.json"
TEX_EXT = (".tga", ".dds", ".png", ".jpg")


def load_manifest():
    rows = []
    for ln in open(MANIFEST, encoding="utf-8"):
        ln = ln.strip()
        if ln.startswith("{"):
            r = json.loads(ln)
            if "mesh" in r:
                rows.append(r)
    return rows


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    c = con.cursor()

    # 贴图名 -> 该名下所有 hash（同名多份都算对）
    by_name = collections.defaultdict(set)
    for name, h in c.execute(
        "select name, hash from resources where ext in ('.tga','.dds','.png','.jpg')"
    ):
        if name and h:
            by_name[name.lower()].add(h)

    # mesh 路径(小写 basename) -> mtl hash 集合
    m2mtl = collections.defaultdict(set)
    for fp, th, tp in c.execute(
        "select from_path, to_hash, to_path from relations where rel='use-mtl'"
    ):
        if fp and tp and th and fp.lower().endswith(".mesh") and tp.lower().endswith(".mtl"):
            m2mtl[os.path.basename(fp.lower())].add(th)

    # mtl hash -> 声明的贴图名集合
    mtl2names = collections.defaultdict(set)
    for fh, name, kind in c.execute("select from_hash, name, kind from refs"):
        if kind in TEX_EXT and name:
            mtl2names[fh].add(name.lower())

    stat = collections.defaultdict(collections.Counter)
    ranks = collections.defaultdict(list)
    misses = []
    files = {f.lower(): f for f in os.listdir(RESULTS)}

    for r in load_manifest():
        grade = r.get("gradedV2") or "?"
        stem = r["mesh"].lower()
        fname = files.get(stem.replace(".mesh", ".json"))
        if not fname:
            stat[grade]["没有结果文件"] += 1
            continue
        try:
            doc = json.loads(
                open(os.path.join(RESULTS, fname), encoding="utf-8").read().splitlines()[0]
            )
        except (json.JSONDecodeError, IndexError, OSError):
            stat[grade]["结果文件读不出"] += 1
            continue
        cands = [x.get("hash") for x in doc.get("candidates", [])]
        pos = {h: i for i, h in enumerate(cands)}

        names = set()
        for m in m2mtl.get(stem, ()):
            names |= mtl2names.get(m, set())
        if not names:
            stat[grade]["无 mtl/无贴图声明"] += 1
            continue
        want = set()
        for n in names:
            want |= by_name.get(n, set())
        if not want:
            stat[grade]["点名的贴图库里没有"] += 1
            continue

        hit = [pos[h] for h in want if h in pos]
        if hit:
            best = min(hit)
            ranks[grade].append(best)
            stat[grade]["进前十"] += 1
            if best == 0:
                stat[grade]["  其中第 1"] += 1
            if best < 3:
                stat[grade]["  其中前 3"] += 1
        else:
            ranks[grade].append(None)
            stat[grade]["没进前十"] += 1
            if len(misses) < 40 and grade == "unknown":
                misses.append((r["mesh"], sorted(names)[:3], len(cands)))

    print("UV 试贴召回率（答案=客户端 mtl 自己点名的贴图；候选榜只有前 10）")
    print(f"{'分级':<9}{'总数':>6}{'有答案':>7}{'进前十':>7}{'第1':>5}{'没进':>6}"
          f"{'无声明':>7}{'点名不在库':>11}{'中位名次':>9}")
    for g in ("high", "mid", "low", "unknown", "?"):
        s = stat.get(g)
        if not s:
            continue
        ok = [x for x in ranks[g] if x is not None]
        tot = sum(s.values()) - s["没有结果文件"] - s["结果文件读不出"]
        ans = len(ranks[g])
        med = f"{statistics.median(ok):.1f}" if ok else "-"
        print(f"{g:<9}{tot:>6}{ans:>7}{s['进前十']:>7}{s['  其中第 1']:>5}"
              f"{s['没进前十']:>6}{s['无 mtl/无贴图声明']:>7}"
              f"{s['点名的贴图库里没有']:>11}{med:>9}")
        print(f"         名次分布 {sorted(collections.Counter(ok).items())[:10]}")
    allv = [x for v in ranks.values() for x in v if x is not None]
    nn = sum(len(v) for v in ranks.values())
    print(f"\n合计：有答案可查 {nn} 份，度量把客户端点名的贴图排进前十 "
          f"{len(allv)} 份（{100.0 * len(allv) / max(nn, 1):.1f}%），"
          f"其中第 1 名 {sum(1 for x in allv if x == 0)} 份")
    if misses:
        print("\nunknown 里没进前十的样本（前 15）：")
        for m, n, k in misses[:15]:
            print(f"  {m}  点名 {n}  榜长 {k}")


if __name__ == "__main__":
    main()
