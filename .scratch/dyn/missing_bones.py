#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合「变体动画轨道里、但本体骨架没有」的那根骨到底是谁。
（先前那条一次性命令里正则 `_b\d+.*$` 的 `$` 被 shell 吃成 `\$`，结果不可信，故写成文件。）"""
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("D:/TLGL")
O = ROOT / ".scratch/skelcmp"
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))


def walk(o, s):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("bone", "name", "child", "parent") and isinstance(v, str):
                s.add(v.lower())
            else:
                walk(v, s)
    elif isinstance(o, list):
        for x in o:
            walk(x, s)
    return s


def keys_of(j):
    return walk({k: v for k, v in j.items() if k != "animations"}, set())


base_cache = {}


def base_of(dir_name):
    b = re.sub(r"_b\d+.*$", "_b0", dir_name)
    if b == dir_name:  # 不是 _bN 变体
        return None
    if b not in base_cache:
        f = O / f"{b}.skel.json"
        base_cache[b] = keys_of(json.loads(f.read_text(encoding="utf-8"))) if f.is_file() else None
    return base_cache[b]


miss = Counter()
rows = 0
no_base = Counter()
for h, p in side.items():
    parts = p.replace("\\", "/").split("/")
    low = [x.lower() for x in parts]
    if not p.lower().endswith(".ani") or "ani" not in low[:-1]:
        continue
    f = O / f"{h}.skel.json"
    if not f.is_file():
        continue
    char = parts[low.index("ani") - 1]
    tb = walk(json.loads(f.read_text(encoding="utf-8")).get("animations") or [], set())
    if not tb:
        continue
    bs = base_of(char)
    if bs is None:
        no_base[char] += len(tb)
        continue
    d = tb - bs
    rows += 1
    for x in d:
        miss[x] += 1

print(f"有本体可比的变体动画：{rows} 条")
print(f"缺到的骨名种类：{len(miss)}，总计 {sum(miss.values())} 次")
for name, c in miss.most_common(12):
    print(f"  {name:<28} {c:>5}")
print(f"\n没有本体可比的（同族 _b0 不存在/导不出）角色目录：{len(no_base)}，例：{list(no_base)[:6]}")
(O / "missing_bones.json").write_text(
    json.dumps({"rows": rows, "miss": miss.most_common()}, ensure_ascii=False, indent=2),
    encoding="utf-8")
