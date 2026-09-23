#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
图片考古墙 · 第二步：把 24,261 张图的内容特征聚成「族」。

这一步的输出是**人要在墙上看到的分组**，所以算法的取舍必须能讲清楚：

1. 用 64 位 dHash 的 Hamming 距离作唯一相似度。标定基线（见 P3-B-0 结论）：
   同源图 0~1 位，纯随机噪声之间 32 位 ⇒ 定阈 ≤8 孪生 / ≤16 同族 / >24 无关。

2. **不做全对全比对**。2.9 亿对在 Python 里跑不动，也没必要：
   用「分段预筛」（LSH）先把候选砍到很小——
   把 64 位切成 `SEGMENTS` 段，**只要有任意一段完全相同**，这对就进候选。

   正确性（这是关键，写错了会静默漏掉真孪生）：
   若两个哈希的距离 ≤ `KIN`，那么被这些差异位"沾到"的段最多 `KIN` 个
   （每个被沾到的段至少含 1 位差异）。所以**至少 `SEGMENTS - KIN` 段完全相同**。
   要让"至少一段相同"成为必然，必须 `SEGMENTS > KIN`。
   早先取 `SEGMENTS = 8`（每段 8 位）时 `KIN = 16 > 8`，
   这个推理**不成立**——差异可以均匀铺满全部 8 段，一段相同都没有，
   真孪生会被静默丢掉。所以现在取 `SEGMENTS = 32`（每段 2 位）：
   `SEGMENTS - KIN = 16`，即任何距离 ≤16 的对至少有 16 段完全相同。
   代价是倒排表变大，但换来的是**不漏**，值得。

3. 候选对建并查集。连通分量 = 族。

4. **超大族要切**。相似度是传递闭包，容易"链式吃掉全库"：
   A≈B、B≈C 但 A≉C。做法是族超过 MAX_FAMILY 时按更严的阈值递归再切。
   宁可多几个小族（人能看），不要一个吃下几万张的大族（人看不了）。

5. 代表图选"到族内其他成员距离和最小"的那张——最典型的那个。
"""

import os
import sys
import json
import time
import sqlite3
import argparse
from collections import defaultdict

# ---------------------------------------------------------------- 阈值（来自标定，不要随手改）

TWIN = 8        # ≤8 位 = 孪生（同源图基本落在 0~1）
KIN = 16        # ≤16 位 = 同族
MAX_FAMILY = 400  # 一个族最多多少张；超了就按更严的阈值再切
# 分段数。必须 > KIN，否则"至少一段完全相同"这个推理不成立、会静默漏掉真孪生。
# 32 段 × 2 位：距离 ≤16 的对至少有 32-16 = 16 段完全相同，必然被预筛捞到。
SEGMENTS = 32
SEG_BITS = 64 // SEGMENTS   # = 2

# 桶太大时跳过（这种位模式没有区分力，且两两配对会爆内存）。
BUCKET_CAP = 4000


def hamming(a, b):
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------- LSH 候选

def candidates(rows, knn=KIN):
    """
    分段预筛：距离 ≤ knn 的对，必然有至少 SEGMENTS - knn 段完全相同
    （每个被沾到的段至少含 1 个差异位，差异位最多 knn 个）。

    返回 (候选对列表, 被跳过的大桶数)。候选对里带真距离，后面不用再算。

    正确性依赖 SEGMENTS > knn —— 见文件头注释。这里再断言一次，
    因为这是"静默漏掉真孪生"和"结果正确"的分界线，不能靠记性。
    """
    assert SEGMENTS > knn, (
        "SEGMENTS(%d) 必须大于 knn(%d)，否则预筛不再保证不漏" % (SEGMENTS, knn))
    mask = (1 << SEG_BITS) - 1

    buckets = [defaultdict(list) for _ in range(SEGMENTS)]
    for i, r in enumerate(rows):
        h = r["dhash"]
        for s in range(SEGMENTS):
            buckets[s][(h >> (s * SEG_BITS)) & mask].append(i)

    # 同一对可能在多段里重复命中，用 set 去重
    seen = set()
    out = []
    skipped_bucket = 0
    for s in range(SEGMENTS):
        for val, idxs in buckets[s].items():
            m = len(idxs)
            if m < 2:
                continue
            if m > BUCKET_CAP:
                # 这类桶（大多数是"某 2 位组合特别常见"）没有区分力，
                # 两两配对还会是 O(m²)。跳过并如实记账——宁可少归并，
                # 也不能假装没发生。
                skipped_bucket += 1
                continue
            for p in range(m):
                i = idxs[p]
                hi = rows[i]["dhash"]
                for q in range(p + 1, m):
                    j = idxs[q]
                    key = (i, j) if i < j else (j, i)
                    if key in seen:
                        continue
                    seen.add(key)
                    d = hamming(hi, rows[j]["dhash"])
                    if d <= knn:
                        out.append((key[0], key[1], d))
    return out, skipped_bucket


# ---------------------------------------------------------------- 并查集

class DSU:
    def __init__(self, n):
        self.p = list(range(n))
        self.sz = [1] * n

    def find(self, x):
        p = self.p
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.sz[ra] < self.sz[rb]:
            ra, rb = rb, ra
        self.p[rb] = ra
        self.sz[ra] += self.sz[rb]
        return True


def split_big(members, rows, edges_of, depth=0):
    """
    把一个过大的族按更严的阈值递归切开。
    返回 [[成员下标, ...], ...]。

    用与 `candidates()` 同一套分段预筛，只是阈值更严（6 + 2*depth）。
    """
    if len(members) <= MAX_FAMILY or depth >= 4:
        return [members]
    sub = [rows[i] for i in members]
    thresh = 6 + depth * 2
    assert SEGMENTS > thresh, "分段数不足，预筛会漏"
    mask = (1 << SEG_BITS) - 1

    dsu = DSU(len(members))
    buckets = [defaultdict(list) for _ in range(SEGMENTS)]
    for k, r in enumerate(sub):
        h = r["dhash"]
        for s in range(SEGMENTS):
            buckets[s][(h >> (s * SEG_BITS)) & mask].append(k)
    seen = set()
    for s in range(SEGMENTS):
        for val, idxs in buckets[s].items():
            m = len(idxs)
            if m < 2 or m > BUCKET_CAP:
                continue
            for p in range(m):
                hi = sub[idxs[p]]["dhash"]
                for q in range(p + 1, m):
                    key = (idxs[p], idxs[q])
                    if key in seen:
                        continue
                    seen.add(key)
                    if hamming(hi, sub[idxs[q]]["dhash"]) <= thresh:
                        dsu.union(idxs[p], idxs[q])
    groups = defaultdict(list)
    for k in range(len(members)):
        groups[dsu.find(k)].append(members[k])
    if len(groups) <= 1:
        return [members]
    out = []
    for g in groups.values():
        out.extend(split_big(g, rows, edges_of, depth + 1))
    return out


# ---------------------------------------------------------------- 主流程

def load_raw(path):
    """
    读 `raw.tsv`。

    这里**做严格校验**，不做"尽量兜底"。原因：这一处曾经踩过列错位的坑——
    Rust 侧成功行多输出了一列，结果 `w` 列装的是编解码器名字、`w/h/mips/...` 整体右移。
    如果这里对非数字列悄悄 `or 0`，全库 2.4 万张图的尺寸会全部变成 0，
    而聚族只看 dHash，**不会有任何报错**，只是墙上的尺寸筛选默默失效。
    所以宁可在这里响亮地失败。
    """
    rows = []
    fails = []
    with open(path, "r", encoding="utf-8") as f:
        head = f.readline().rstrip("\n").split("\t")
        col = {k: i for i, k in enumerate(head)}

        # 必须有的列，少一列就是格式变了，直接报错而不是猜
        need = ["hash", "decoded", "pak", "gen", "offset", "original",
                "catalog_codec", "w", "h", "mips", "dhash",
                "dec_w", "dec_h", "mean_r", "mean_g", "mean_b", "mean_a",
                "lum_sd", "edge", "alpha_cov", "fail"]
        missing = [k for k in need if k not in col]
        if missing:
            raise SystemExit(f"raw.tsv 缺少列 {missing}；实际表头 {head}")

        def num(p, key, why, lineno, cast=int, default="0"):
            """取数字列，取不到就带着行号和列名报错（不要静默变 0）。"""
            v = p[col[key]] if col[key] < len(p) else ""
            if v == "":
                v = default
            try:
                return cast(v)
            except ValueError:
                raise SystemExit(
                    f"raw.tsv 第 {lineno} 行 `{key}` 列不是数字：{v!r}\n"
                    f"  整行前 12 列：{p[:12]}\n"
                    f"  —— 这通常意味着列错位（格式与表头不同步），不是数据问题。"
                )

        for lineno, line in enumerate(f, start=2):
            p = line.rstrip("\n").split("\t")
            if len(p) != len(head):
                raise SystemExit(
                    f"raw.tsv 第 {lineno} 行有 {len(p)} 列，表头是 {len(head)} 列"
                )
            if p[col["decoded"]] != "1":
                fails.append({"hash": p[col["hash"]], "reason": p[col["fail"]]})
                continue
            rows.append({
                "hash": p[col["hash"]],
                "pak": p[col["pak"]],
                "gen": num(p, "gen", "", lineno),
                "offset": num(p, "offset", "", lineno),
                "original": num(p, "original", "", lineno),
                "ccodec": p[col["catalog_codec"]],
                "dcodec": p[col["dec_codec"]] if "dec_codec" in col else "",
                "w": num(p, "w", "", lineno),
                "h": num(p, "h", "", lineno),
                "mips": num(p, "mips", "", lineno),
                "dhash": num(p, "dhash", "", lineno, cast=lambda s: int(s, 16)),
                "dw": num(p, "dec_w", "", lineno),
                "dh": num(p, "dec_h", "", lineno),
                "mr": num(p, "mean_r", "", lineno, cast=float),
                "mg": num(p, "mean_g", "", lineno, cast=float),
                "mb": num(p, "mean_b", "", lineno, cast=float),
                "ma": num(p, "mean_a", "", lineno, cast=float),
                "lum_sd": num(p, "lum_sd", "", lineno, cast=float),
                "edge": num(p, "edge", "", lineno, cast=float),
                "alpha_cov": num(p, "alpha_cov", "", lineno, cast=float),
            })
    return rows, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=r"D:\TLGL\.scratch\wall3\raw.tsv")
    ap.add_argument("--out", default=r"D:\TLGL\.scratch\wall3\wall.db")
    ap.add_argument("--report", default=r"D:\TLGL\.scratch\wall3\cluster_report.txt")
    a = ap.parse_args()

    t0 = time.time()
    rows, fails = load_raw(a.raw)
    n = len(rows)
    rep = []
    def say(s=""):
        print(s)
        rep.append(s)

    say("== 图片考古墙 · 聚族")
    say("参与聚族 %d 张；解不出（不参与）%d 张" % (n, len(fails)))
    say("阈值：≤%d 孪生 · ≤%d 同族 · 单族上限 %d" % (TWIN, KIN, MAX_FAMILY))
    say("")

    # ---- 退化统计：dHash 对纯色图无意义，必须单独说清
    flat = [r for r in rows if r["lum_sd"] < 3.0]
    say("退化检查：亮度标准差 <3 的近似纯色图 %d 张（%.2f%%）" % (len(flat), 100.0 * len(flat) / max(1, n)))
    lowedge = [r for r in rows if r["edge"] < 2.0]
    say("           边缘能量 <2 的近乎平坦图 %d 张（%.2f%%）" % (len(lowedge), 100.0 * len(lowedge) / max(1, n)))
    say("")

    # ---- 候选对
    cand, skipped = candidates(rows, KIN)
    say("分段预筛（%d 段）得到候选对 %d 对；无区分力的大桶跳过 %d 个" % (SEGMENTS, len(cand), skipped))
    say("全对全本应 %d 对 ⇒ 预筛省掉 %.4f%%" % (n * (n - 1) // 2,
        100.0 * (1 - len(cand) / max(1, n * (n - 1) // 2))))
    say("")

    # ---- 连通分量
    dsu = DSU(n)
    edges = []
    twin_pairs = 0
    for i, j, d in cand:
        if d <= TWIN:
            twin_pairs += 1
        dsu.union(i, j)
        edges.append((i, j, d))
    say("候选对里真距离 ≤%d（孪生）的 %d 对" % (TWIN, twin_pairs))
    say("")

    groups = defaultdict(list)
    for i in range(n):
        groups[dsu.find(i)].append(i)
    say("并查集得到 %d 个连通分量" % len(groups))

    # ---- 切超大族
    families = []
    for g in groups.values():
        families.extend(split_big(g, rows, edges))
    families.sort(key=len, reverse=True)
    say("切开超大族后共 %d 个族" % len(families))
    say("")

    # ---- 族统计
    hist = defaultdict(int)
    for f in families:
        hist[len(f)] += 1
    say("族大小分布：")
    for k in [1, 2, 3, 4, 5, 6, 8, 11, 16, 21, 31, 51, 101, 201]:
        # 区间统计
        pass
    buckets = [(1, 1), (2, 2), (3, 4), (5, 9), (10, 24), (25, 49), (50, 99), (100, 199),
               (200, 399), (400, 10**9)]
    for lo, hi in buckets:
        c = sum(1 for f in families if lo <= len(f) <= hi)
        m = sum(len(f) for f in families if lo <= len(f) <= hi)
        label = "%d" % lo if lo == hi else ("%d-%d" % (lo, hi) if hi < 10**9 else "%d+" % lo)
        say("  %-9s 族 %6d 个，覆盖 %7d 张（%.2f%%）" % (label, c, m, 100.0 * m / max(1, n)))
    say("")

    # ---- 单张族（孤图）单独点名
    singles = [f for f in families if len(f) == 1]
    say("孤图（族内只有自己）%d 张，占 %.2f%%" % (len(singles), 100.0 * len(singles) / max(1, n)))
    say("  —— 这些图在内容上找不到任何伙伴，是墙上最需要人工判断的一批")
    say("")

    # ---- 族内紧度
    tight = 0
    loose = 0
    for f in families:
        if len(f) < 2:
            continue
        # 只对族内抽样算（避免又变成全对全）
        sample = f[:40] if len(f) > 40 else f
        ds = []
        for x in range(len(sample)):
            for y in range(x + 1, len(sample)):
                ds.append(hamming(rows[sample[x]]["dhash"], rows[sample[y]]["dhash"]))
        if not ds:
            continue
        m = sum(ds) / len(ds)
        if m <= TWIN:
            tight += 1
        elif m > KIN:
            loose += 1
    say("族紧度（族内抽样平均距离）：均值 ≤%d 的紧族 %d 个；>%d 的松族 %d 个" % (TWIN, tight, KIN, loose))
    say("")

    # ---- 写库
    if os.path.exists(a.out):
        try:
            os.remove(a.out)
        except OSError:
            pass
    con = sqlite3.connect(a.out)
    con.executescript("""
      PRAGMA journal_mode=OFF;
      PRAGMA synchronous=OFF;
      CREATE TABLE wall_tex(
        hash TEXT PRIMARY KEY, pak TEXT, gen INT, offset INT, original INT,
        catalog_codec TEXT, declared_w INT, declared_h INT, mips INT,
        dhash TEXT, dec_w INT, dec_h INT,
        mean_r REAL, mean_g REAL, mean_b REAL, mean_a REAL,
        lum_sd REAL, edge REAL, alpha_cov REAL,
        decoded INT, fail_reason TEXT, fam INT);
      CREATE INDEX ix_wt_fam ON wall_tex(fam);
      CREATE INDEX ix_wt_dhash ON wall_tex(dhash);
      CREATE TABLE wall_family(
        fid INTEGER PRIMARY KEY, n INT, rep_hash TEXT, mean_d REAL, dia INT,
        codec TEXT, w INT, h INT, tightness TEXT);
      CREATE TABLE wall_fail(hash TEXT PRIMARY KEY, reason TEXT);
      CREATE TABLE wall_meta(k TEXT PRIMARY KEY, v TEXT);
    """)

    con.executemany(
        "INSERT INTO wall_fail(hash,reason) VALUES(?,?)",
        [(f["hash"], f["reason"]) for f in fails])

    # 族写入
    fam_rows = []
    tex_rows = []
    for fi, f in enumerate(families):
        # 代表图：到其他成员距离和最小
        # ⚠ 变量名别用 `rep`——那是上面**报告文本累加器**的名字。
        # 这里曾经复用了 `rep`，把这个 list 改绑成一张图的索引，
        # 结果整个脚本跑完、库也写好了，却在最后一行 `rep.append()` 崩掉：
        # 203 个族的成果全在，报告却丢了。报告是给人看的交付物之一，不能丢。
        repre = f[0]
        mean_d = 0.0
        dia = 0
        if len(f) > 1:
            best = None
            sample = f[:60]
            for cand_i in sample:
                s = sum(hamming(rows[cand_i]["dhash"], rows[o]["dhash"]) for o in f if o != cand_i)
                if best is None or s < best[0]:
                    best = (s, cand_i)
            repre = best[1]
            # 统计（大族抽样）
            ds = [hamming(rows[repre]["dhash"], rows[o]["dhash"]) for o in f if o != repre]
            mean_d = sum(ds) / len(ds)
            dia = max(ds)
        # 多数表决的尺寸
        cc = defaultdict(int)
        for o in f:
            cc[(rows[o]["ccodec"], rows[o]["w"], rows[o]["h"])] += 1
        (mcodec, mw, mh), _ = max(cc.items(), key=lambda kv: kv[1])
        t = "tight" if mean_d <= TWIN else ("loose" if mean_d > KIN else "mixed")
        fam_rows.append((fi, len(f), rows[repre]["hash"], round(mean_d, 2), dia, mcodec, mw, mh, t))
        for o in f:
            tex_rows.append(("T", fi, rows[o]["hash"]))

    con.executemany(
        "INSERT INTO wall_family(fid,n,rep_hash,mean_d,dia,codec,w,h,tightness) VALUES(?,?,?,?,?,?,?,?,?)",
        fam_rows)

    # 图片行
    bag = []
    fam_of = {}
    for fi, f in enumerate(families):
        for o in f:
            fam_of[rows[o]["hash"]] = fi
    for r in rows:
        bag.append((r["hash"], r["pak"], r["gen"], r["offset"], r["original"],
                    r["ccodec"], r["w"], r["h"], r["mips"],
                    "%016x" % r["dhash"], r["dw"], r["dh"],
                    r["mr"], r["mg"], r["mb"], r["ma"], r["lum_sd"], r["edge"],
                    r["alpha_cov"], 1, "", fam_of.get(r["hash"], -1)))
    for f in fails:
        bag.append((f["hash"], "", 0, 0, 0, "", 0, 0, 0, "", 0, 0,
                    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, f["reason"][:200], -1))
    con.executemany(
        "INSERT OR REPLACE INTO wall_tex VALUES(" + ",".join(["?"] * 22) + ")", bag)

    meta = {
        "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
        "参与聚族": str(n),
        "解不出": str(len(fails)),
        "族数": str(len(families)),
        "孤图": str(len(singles)),
        "孪生阈值": str(TWIN),
        "同族阈值": str(KIN),
        "单族上限": str(MAX_FAMILY),
        "候选对": str(len(cand)),
        "全对全": str(n * (n - 1) // 2),
    }
    con.executemany("INSERT INTO wall_meta(k,v) VALUES(?,?)", list(meta.items()))
    con.commit()
    con.execute("ANALYZE")
    con.commit()
    con.close()

    say("库已写出 %s（%.1f MB）" % (a.out, os.path.getsize(a.out) / 1048576.0))
    say("耗时 %.1fs" % (time.time() - t0))

    with open(a.report, "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")


if __name__ == "__main__":
    main()
