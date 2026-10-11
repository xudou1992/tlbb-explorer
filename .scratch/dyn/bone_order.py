#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""骨序对照：变体 .ani 的轨道骨名顺序 vs 同族 _b0 骨架的节点顺序。

为什么要单独问这一层：骨名 304/304 全在（10-11 已量）只说明「认得这些骨」，
播起来还要**顺序**或**按名字重挂**两条路之一成立。播放管线是按名字重挂的
（preview::pose 的重定基用骨名找位），所以顺序不等价不代表不能播——
但「顺序也一致」会让这件事更硬，值得一个数。

只读 .scratch/skelcmp 里已经导出的 JSON，不碰 pak、不改判据。
比子集前先把空名剔掉并计数（今天两次栽在空值上）。
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path("D:/TLGL")
O = ROOT / ".scratch/skelcmp"
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))

empties = Counter()


def ordered_names(node_list):
    out = []
    for n in node_list or []:
        v = n.get("bone") or n.get("name") if isinstance(n, dict) else None
        if isinstance(v, str):
            if not v.strip():
                empties["节点"] += 1
                continue
            out.append(v.lower())
    return out


def track_names(j):
    """第一条动画的轨道骨名，按出现顺序。"""
    out = []
    for a in j.get("animations") or []:
        for t in a.get("tracks") or []:
            v = t.get("bone") if isinstance(t, dict) else None
            if isinstance(v, str):
                if not v.strip():
                    empties["轨道"] += 1
                    continue
                out.append(v.lower())
        break
    return out


base_cache = {}


def base_seq(char):
    b = re.sub(r"_b\d+.*$", "_b0", char)
    if b == char:
        return None
    if b not in base_cache:
        f = O / (b + ".skel.json")
        base_cache[b] = ordered_names(json.loads(f.read_text(encoding="utf-8")).get("nodes")) if f.is_file() else None
    return base_cache[b]


stat = Counter()
examples = []
for h, p in side.items():
    if not p.lower().endswith(".ani"):
        continue
    parts = p.replace("\\", "/").split("/")
    low = [x.lower() for x in parts]
    if "ani" not in low[:-1]:
        continue
    f = O / (h + ".skel.json")
    if not f.is_file():
        continue
    j = json.loads(f.read_text(encoding="utf-8"))
    tb = track_names(j)
    bs = base_seq(parts[low.index("ani") - 1])
    if not tb or not bs:
        stat["没数据"] += 1
        continue
    if tb == bs:
        stat["顺序完全一致"] += 1
    elif set(tb) == set(bs):
        stat["同一批骨但顺序不同"] += 1
    elif set(tb) <= set(bs):
        stat["是本体的子集（顺序另算）"] += 1
    else:
        stat["仍有本体没有的骨名"] += 1
        if len(examples) < 5:
            examples.append((parts[-1], sorted(set(tb) - set(bs))[:4]))

print("== 骨序对照（变体 .ani 轨道顺序 vs 本体 _b0 节点顺序）")
for k, v in stat.most_common():
    print(f"  {k:<24} {v}")
print("  剔掉的空值：", dict(empties) or "没有")
if examples:
    print("  仍有缺名的例子：")
    for e in examples:
        print("   ", e)
print("\n注：轨道数与节点数不一定相等（本体骨架可能带动画没驱动的挂点骨），"
      "所以「子集」也单独计数；播放管线按骨名重挂，顺序不等价不等于不能播。")
(O / "bone_order_summary.json").write_text(
    json.dumps({"stat": stat, "empties": empties, "examples": examples}, ensure_ascii=False, indent=2),
    encoding="utf-8")
