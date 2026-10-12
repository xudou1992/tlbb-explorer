#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一个动作，本体与变体的轨道骨名**顺序**对不对得上。

228/229 那条判决只比了「名字在不在名单里」。真要即插即用，得看同名的动作
（比如两边的 run）驱动的是不是同一串骨、同一序。
本体那份 .ani 在清单里有路径，skel_dump 按名字就能取；变体那份只能按 hash。
"""
import json
import re
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path("D:/TLGL")
O = ROOT / ".scratch/skelcmp"
BIN = str(ROOT / "tlbb-explorer/target/debug/skel_dump.exe")
N = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 12
BS = chr(92)

con = sqlite3.connect("file:" + (ROOT / ".scratch/resources.db").as_posix() + "?mode=ro", uri=True)
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))
norm = {h: p.replace(BS, "/") for h, p in side.items()}


def tracks(ident, ani_flag=True):
    f = O / (ident + ".skel.json")
    if not f.is_file():
        subprocess.run([BIN, "--ani" if ani_flag else "--name", ident,
                        "--root", "D:/TLGL", "--out", str(O)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not f.is_file():
        return None
    j = json.loads(f.read_text(encoding="utf-8"))
    out = []
    for a in j.get("animations") or []:
        for t in a.get("tracks") or []:
            v = str(t.get("bone") or "").lower().strip()
            if v:
                out.append(v)
        break
    return out


def action_of(fn):
    """从文件名里取出动作名：去掉角色前缀与 .ani。"""
    stem = fn[:-4] if fn.lower().endswith(".ani") else fn
    return stem


by_variant = {}
for h, p in norm.items():
    if not p.lower().endswith(".ani") or "/ani/" not in p.lower():
        continue
    parts = p.split("/")
    low = [x.lower() for x in parts]
    i = low.index("ani")
    by_variant.setdefault(parts[i - 1], []).append((h, parts[-1]))

fams = sorted(by_variant)[:N * 12]  # 这里 N 限的是**本体**数，变体目录先全列出来再按本体筛
per_base = {}
same = diff = 0
report = []
for variant in fams:
    base = re.sub(r"_b\d+.*$", "_b0", variant)
    # 计数按**本体**去重：一个 _b0 底下常有 _b1…_b8 八个变体目录，
    # 上一版按变体目录计数，18 对全落在 bawanglong 与 chaimao 两个本体上，不算跨族样本。
    for h, fn in by_variant[variant]:
        if per_base.get(base, 0) >= 2:
            break
        act = action_of(fn)
        if act.lower().startswith(variant.lower()):
            act = act[len(variant):].lstrip("_")
        # 本体那份同名动作（清单里有路径）
        row = con.execute("select path from resources where path like ? limit 1",
                          ("%/" + base + "/ani/" + base + "_" + act + ".ani",)).fetchone()
        if not row:
            continue
        per_base[base] = per_base.get(base, 0) + 1
        bname = str(row[0]).replace(BS, "/").split("/")[-1]
        tb = tracks(fn[:-4] if False else h)          # 变体：按 hash
        bb = tracks(bname)                            # 本体：按文件名
        if not tb or not bb:
            continue
        if tb == bb:
            same += 1
            verdict = "顺序完全一致"
        else:
            diff += 1
            first = next((i for i, (x, y) in enumerate(zip(tb, bb)) if x != y), min(len(tb), len(bb)))
            verdict = f"不同：第 {first} 根起分岔（{tb[first] if first < len(tb) else '…'} vs " \
                      f"{bb[first] if first < len(bb) else '…'}）"
        report.append(f"{bname:<48} vs 变体轨道 {len(tb)} / 本体轨道 {len(bb)} · {verdict}")
        if len([1 for v in per_base.values() if v]) >= N:
            break

print(f"== 同动作的轨道顺序对照（比了 {same + diff} 对 · 覆盖 {len(per_base)} 个本体）")
print(f"   顺序完全一致：{same}")
print(f"   有差异：{diff}")
for line in report[:24]:
    print("   ", line)
(O / "order_pair.json").write_text(json.dumps({"same": same, "diff": diff, "lines": report},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
