#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数清楚：sidecar 那 4,780 件能拼出多少个**完整的角色资产集**。
判据只用清单自己数得出的东西：同一角色目录下 mesh + mtl + mdl + ske + ani 齐全，
就算「这个角色的资产在包里、但清单没名字」。输出一份可核对的清单，供决定要不要补进目录。"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path("D:/TLGL")
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))
BS = chr(92)

by = defaultdict(lambda: defaultdict(int))
files = defaultdict(list)
for h, p in side.items():
    q = p.replace(BS, "/")
    parts = q.split("/")
    low = [x.lower() for x in parts]
    for sub in ("ani", "texture", "mesh"):
        if sub in low[:-1]:
            char = "/".join(parts[:low.index(sub)])
            break
    else:
        char = "/".join(parts[:-1])
    ext = q.rsplit(".", 1)[-1].lower()
    by[char][ext] += 1
    files[char].append(q)

complete, partial = [], []
for char, c in sorted(by.items()):
    has = all(c.get(k, 0) > 0 for k in ("mesh", "mtl", "mdl", "ske", "ani"))
    (complete if has else partial).append((char, dict(c), sum(c.values())))

print("== sidecar 覆盖的角色目录：", len(by))
print("   mesh+mtl+mdl+ske+ani **五样齐全**（可直接拼成一个资产组）：", len(complete))
print("   缺至少一样：", len(partial))

kinds = defaultdict(int)
for _, c, _n in partial:
    miss = [k for k in ("mesh", "mtl", "mdl", "ske", "ani") if not c.get(k)]
    kinds["+".join(miss)] += 1
print("   缺的是哪几样（前 8）：", sorted(kinds.items(), key=lambda kv: -kv[1])[:8])

out = ["# 可以补进目录的角色集（清单里没有名字，包里有完整一套）", "",
       f"数据源：`.scratch/cfg_named_sidecar.json`（4,780 件 path_hash 对上 cfg 登记路径的匿名件）。",
       f"**五样齐全、可直接拼成资产组的角色目录：{len(complete)} 个。**", "",
       "| 角色目录 | mesh | mtl | mdl | ske | ani | 合计 |", "| --- | --- | --- | --- | --- | --- | --- |"]
for char, c, n in complete:
    out.append(f"| `{char}` | {c.get('mesh', 0)} | {c.get('mtl', 0)} | {c.get('mdl', 0)} | "
               f"{c.get('ske', 0)} | {c.get('ani', 0)} | {n} |")
out += ["", f"## 还差样的（{len(partial)} 个）", ""]
for char, c, n in partial[:40]:
    out.append(f"- `{char}` → {json.dumps(c, ensure_ascii=False)}")
(ROOT / ".scratch/可补目录的角色集_20261012.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print("\n清单：", ROOT / ".scratch/可补目录的角色集_20261012.md")
