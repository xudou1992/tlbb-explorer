#!/usr/bin/env python3
"""阈值刻度核对：grade() 的 6/3/1.2 到底是拍在 raw 刻度上还是 adjusted 刻度上。

把两套分数的分布、三个阈值在各刻度上的覆盖率、以及换刻度后的迁移量都打出来。
"""
import json

MANIFEST = ".scratch/uvfit_batch/manifest.json"
THRESHOLDS = (6.0, 3.0, 1.2)


def rows_of():
    out = []
    for ln in open(MANIFEST, encoding="utf-8"):
        ln = ln.strip()
        if ln.startswith("{"):
            r = json.loads(ln)
            if "mesh" in r:
                out.append(r)
    return out


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))]


def main():
    rows = rows_of()
    raw = [r["topScore"] for r in rows if r.get("topScore") is not None]
    adj = [r["topAdjusted"] for r in rows if r.get("topAdjusted") is not None]
    print(f"有分数的 {len(raw)} 份")
    print(f"raw  topScore   p50 {q(raw,.5):.2f}  p90 {q(raw,.9):.2f}  p99 {q(raw,.99):.2f}  max {max(raw):.1f}")
    print(f"adj  topAdjusted p50 {q(adj,.5):.3f} p90 {q(adj,.9):.3f} p99 {q(adj,.99):.3f} max {max(adj):.2f}")
    print("\n阈值落在两套刻度上的覆盖率：")
    for name, xs in (("raw", raw), ("adjusted", adj)):
        for th in THRESHOLDS:
            n = sum(1 for x in xs if x >= th)
            print(f"  {name:<9} ≥{th:<5} {n:>5} 份 = {n/len(xs)*100:5.1f}%")
    print("\ngradedV2 各档的 adjusted 区间：")
    for g in ("high", "mid", "low", "unknown"):
        xs = [r["topAdjusted"] for r in rows if r.get("gradedV2") == g and r.get("topAdjusted") is not None]
        if xs:
            print(f"  {g:<8} n={len(xs):<5} min {min(xs):.3f}  p50 {q(xs,.5):.3f}  max {max(xs):.3f}")
    print("\n同一批 v1 graded 各档的 raw 区间（对照）：")
    for g in ("high", "mid", "low", "unknown"):
        xs = [r["topScore"] for r in rows if r.get("graded") == g and r.get("topScore") is not None]
        if xs:
            print(f"  {g:<8} n={len(xs):<5} min {min(xs):.2f}  p50 {q(xs,.5):.2f}  max {max(xs):.1f}")
    print("\n换刻度迁移：v1 high → v2 unknown 的",
          sum(1 for r in rows if r.get("graded") == "high" and r.get("gradedV2") == "unknown"), "份；",
          "v1 unknown → v2 high 的",
          sum(1 for r in rows if r.get("graded") == "unknown" and r.get("gradedV2") == "high"), "份")


if __name__ == "__main__":
    main()
