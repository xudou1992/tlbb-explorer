#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变体动画 vs 本体骨架：把骨名对照从「一条样本」推到「一批族」。

做法（全部走现有工具，不改任何判据）：
  sidecar 里按角色目录归堆 → 每个 `_bN` 变体找同族 `_b0` 本体（清单里有路径的）
  → `skel_dump --ani <hash>`（匿名件靠 hash 定位，10-11 才打通）导一条动画
  → `skel_dump --name <本体名>` 导本体骨架 → 比动画轨道骨名是不是本体骨架骨名的子集。

只读清单与 pak，只往 .scratch/skelcmp 写。
"""
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("D:/TLGL")
OUT = ROOT / ".scratch/skelcmp"
BIN = ROOT / "tlbb-explorer/target/debug/skel_dump.exe"
FAMILIES = int(sys.argv[1]) if len(sys.argv) > 1 else 18
PER_FAMILY = 3


def run(args):
    r = subprocess.run([str(BIN)] + args, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def track_bones(j):
    s = set()
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("bone", "name", "child", "parent") and isinstance(v, str):
                    s.add(v.lower())
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    walk(j.get("animations") or [])
    return s


def skel_bones(j):
    s = set()
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("bone", "name", "child", "parent") and isinstance(v, str):
                    s.add(v.lower())
                else:
                    walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)
    for k, v in j.items():
        if k == "animations":
            continue
        walk(v)
    return s


side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))
by_dir = defaultdict(list)
for h, p in side.items():
    if not p.lower().endswith(".ani"):
        continue
    parts = p.replace("\\", "/").split("/")
    low = [x.lower() for x in parts]
    if "ani" not in low[:-1]:
        continue
    by_dir["/".join(parts[: low.index("ani")])].append((h, parts[-1]))

# 变体目录 -> 同族本体名（_b0）
fams = {}
for d in by_dir:
    last = d.rstrip("/").split("/")[-1]
    if "_b" not in last:
        continue
    base = re.sub(r"_b\d+.*$", "_b0", last)
    fams.setdefault(base, []).append(d)
bases = sorted(fams)[:FAMILIES]
print(f"候选族：{len(fams)} 个，本轮取前 {len(bases)} 个；每族最多 {PER_FAMILY} 条动画\n")

rows = []
skipped_base = 0
for base in bases:
    code, txt = run(["--root", "D:/TLGL", "--name", base, "--out", str(OUT)])
    f = OUT / f"{base}.skel.json"
    if not f.is_file():
        skipped_base += 1
        print(f"  本体 {base} 没导出来：{txt.strip().splitlines()[-1] if txt.strip() else '（无输出）'}")
        continue
    bs = skel_bones(json.loads(f.read_text(encoding="utf-8")))
    for d in fams[base]:
        for h, fn in by_dir[d][:PER_FAMILY]:
            g = OUT / f"{h}.skel.json"
            if not g.is_file():
                code, txt = run(["--root", "D:/TLGL", "--ani", h, "--out", str(OUT)])
                if not g.is_file():
                    rows.append((fn, None, len(bs), None, "解不出"))
                    continue
            tb = track_bones(json.loads(g.read_text(encoding="utf-8")))
            if not tb:
                rows.append((fn, 0, len(bs), 0, "没有轨道骨名"))
                continue
            miss = tb - bs
            rows.append((fn, len(tb), len(bs), len(miss), "全在" if not miss else "有缺"))

tot = len(rows)
clean = sum(1 for r in rows if r[4] == "全在")
bad = sum(1 for r in rows if r[4] == "有缺")
none = sum(1 for r in rows if r[4] not in ("全在", "有缺"))
print(f"\n== 比了 {tot} 条变体动画（本体导出失败跳过 {skipped_base} 个族）")
print(f"   轨道骨名**全在**本体骨架里：{clean}")
print(f"   有缺：{bad}")
print(f"   其他（解不出/没骨名）：{none}")
if bad:
    print("\n有缺的明细（前 12）：")
    for r in [x for x in rows if x[4] == "有缺"][:12]:
        print(f"  {r[0]:<44} 轨道 {r[1]:>3} · 本体 {r[2]:>3} · 缺 {r[3]}")
print("\n全部逐条：")
for r in rows:
    print(f"  {r[0]:<44} 轨道 {str(r[1]):>4} · 本体 {str(r[2]):>4} · 缺 {str(r[3]):>4} · {r[4]}")
(OUT / "bone_compare_summary.json").write_text(
    json.dumps({"rows": rows, "clean": clean, "bad": bad, "other": none,
                "families": len(bases), "skipped_base": skipped_base},
               ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n明细：{OUT / 'bone_compare_summary.json'}")
