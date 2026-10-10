#!/usr/bin/env python3
"""试贴 unknown 分桶：把 gradedV2=unknown 的份按「前提为什么不成立」拆开。

数据源是 uvfit_batch 的 manifest（JSONL，一行一份网格）。
注意字段是 camelCase（hasUv / topScore / topAdjusted / coverage）——
按 snake_case 取会全部取到 None，第一遍就这么错过一次。
"""
import collections
import json

MANIFEST = ".scratch/uvfit_batch/manifest.json"


def rows_of(path=MANIFEST):
    out = []
    for ln in open(path, encoding="utf-8"):
        ln = ln.strip()
        if ln.startswith("{"):
            r = json.loads(ln)
            if "mesh" in r:
                out.append(r)
    return out


def main():
    rows = rows_of()
    st = [r for r in (json.loads(l) for l in open(MANIFEST, encoding="utf-8") if l.strip().startswith("{")) if "gradedV2" in r][-1]
    print("stats:", json.dumps(st, ensure_ascii=False))
    unk = [r for r in rows if r.get("gradedV2") == "unknown"]
    print(f"\ngradedV2 == unknown 共 {len(unk)} 份")
    b = collections.Counter()
    ex = collections.defaultdict(list)
    for r in unk:
        if not r.get("hasUv"):
            k = "① 网格没有 UV 流（试贴前提不成立）"
        elif r.get("topAdjusted") is not None and r["topAdjusted"] < 1.3:
            k = "② 度量退化：岛内外没有对比（adjusted 挤在 1.0 附近）"
        elif r.get("topAdjusted") is None:
            k = "③ 没有 adjusted（有 UV 但没算出候选分）"
        else:
            k = "④ 有信号但分数不达标"
        b[k] += 1
        if len(ex[k]) < 3:
            ex[k].append(r)
    for k in sorted(b):
        print(f"\n{k}: {b[k]} 份")
        for r in ex[k]:
            print(f"   例 {r['mesh'][:52]:<52} hasUv {r.get('hasUv')} raw {r.get('topScore')} adj {r.get('topAdjusted')} cover {r.get('coverage')}")
    band = [r for r in rows if r.get("topAdjusted") is not None and r["topAdjusted"] < 1.3]
    rest = [r for r in rows if r.get("topAdjusted") is not None and r["topAdjusted"] >= 1.3]

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(len(xs) * p))]

    print("\n退化带 vs 其余的 coverage（证明②是「铺满整张图」而不是「分不够」）：")
    for name, g in (("退化带", band), ("其余", rest)):
        cov = [r["coverage"] for r in g if r.get("coverage") is not None]
        hi = sum(1 for c in cov if c >= 0.9)
        print(f"  {name} n={len(g)}: p10 {q(cov,.1):.3f} p50 {q(cov,.5):.3f} p90 {q(cov,.9):.3f} · ≥0.9 占 {hi/len(cov)*100:.0f}%")


if __name__ == "__main__":
    main()
