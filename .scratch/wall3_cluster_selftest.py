#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
聚族脚本的自检：证明「分段预筛」不漏对。

这是必须的，不是可选的。预筛写错的表现是**静默漏掉真孪生**——
族会变小变多，看起来"也出了结果"，但和真值不一样，而且没有任何报错。
所以这里用随机数据做穷举对照：同一批哈希，
全对全算一遍真距离，和预筛捞出来的比，两者必须完全一致。

跑法：python wall3_cluster_selftest.py
"""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wall3_cluster as WC


def brute(rows, knn):
    out = set()
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if WC.hamming(rows[i]["dhash"], rows[j]["dhash"]) <= knn:
                out.add((i, j))
    return out


def case(name, hashes, knn):
    rows = [{"dhash": h} for h in hashes]
    want = brute(rows, knn)
    got_list, skipped = WC.candidates(rows, knn)
    got = set((a, b) for a, b, _ in got_list)
    miss = want - got
    extra = got - want
    ok = (not miss) and (not extra) and skipped == 0
    print("  %-34s 真值 %5d  预筛 %5d  漏 %d  多 %3d  跳桶 %d  %s"
          % (name, len(want), len(got), len(miss), len(extra), skipped,
             "OK" if ok else "**不符**"))
    if miss:
        ex = sorted(miss)[:3]
        print("     漏例：", [(a, b, WC.hamming(rows[a]["dhash"], rows[b]["dhash"])) for a, b in ex])
    return ok


def main():
    random.seed(20260922)
    print("== 分段预筛自检（穷举对照）")
    print("  SEGMENTS=%d  SEG_BITS=%d  KIN=%d  桶上限=%d"
          % (WC.SEGMENTS, WC.SEG_BITS, WC.KIN, WC.BUCKET_CAP))
    print()

    allok = True

    # 1) 小规模随机：真值可穷举
    for n in (80, 200):
        hs = [random.getrandbits(64) for _ in range(n)]
        allok &= case("随机 %d 个哈希" % n, hs, WC.KIN)

    # 2) 故意造相近对：从同一个种子翻转少量位
    hs = []
    for k in range(60):
        base = random.getrandbits(64)
        hs.append(base)
        for _ in range(3):
            v = base
            for _ in range(random.randint(1, 6)):
                v ^= 1 << random.randrange(64)
            hs.append(v)
    allok &= case("成簇（含 1~6 位翻转）", hs, WC.KIN)

    # 3) **最恶劣情况**：差异位均匀铺满所有段
    #    这是老版本 SEGMENTS=8 会漏掉的情形，专门钉住。
    a = 0
    b = 0
    # 在 32 段里每隔一段翻 1 位 => 16 段各差 1 位，距离 = 16，恰好等于阈值
    for s in range(0, WC.SEGMENTS, 2):
        b ^= 1 << (s * WC.SEG_BITS)
    hs = [a, b]
    rows = [{"dhash": h} for h in hs]
    d = WC.hamming(a, b)
    got, _ = WC.candidates(rows, WC.KIN)
    found = len(got) == 1
    print("  %-34s 距离 %d  预筛命中 %s  %s"
          % ("最恶劣：差异铺满一半段", d, found, "OK" if found else "**漏了**"))
    allok &= found

    # 4) 距离恰好 KIN 的边界
    for target in (WC.KIN - 1, WC.KIN, WC.KIN + 1):
        # 把 target 个差异位尽量分散到不同的段
        v = 0
        placed = 0
        s = 0
        while placed < target and s < 64:
            v |= 1 << s
            placed += 1
            s += max(1, 64 // max(1, target))
        hs = [0, v]
        rows = [{"dhash": h} for h in hs]
        got, _ = WC.candidates(rows, WC.KIN)
        hit = len(got) == 1
        should = target <= WC.KIN
        ok = (hit == should)
        print("  %-34s 距离 %d  预筛命中 %-5s 应当 %-5s  %s"
              % ("边界：距离 %d" % target, target, hit, should, "OK" if ok else "**不符**"))
        allok &= ok

    print()
    if allok:
        print("⇒ 预筛与穷举完全一致，不会静默漏掉真孪生。")
        return 0
    print("⇒ 预筛有漏或有多，聚族结果不可信，必须先修。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
