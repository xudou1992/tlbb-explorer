#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""并集版：变体 .ani 的轨道骨名 vs 本体 _b0 同目录**全部件网格**的 nodes[].name 并集。

为什么要重做一遍：前两轮拿「一份部件网格」的 23 根骨去比动画的 61~83 根轨道，
必然报「对不上」——而 10-10 已经记过：网格只声明自身那部分骨，一副骨架要靠同目录全部件网格的并集
（zhaotianshi：部件链 118 + 动作另 59 = 177，与「主网格 ∪ 四份部件」逐数对上）。

只读清单与 pak；skel_dump 导出的 JSON 落在 .scratch/skelcmp。
空名一律剔掉并报数（今天栽过两次）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import sqlite3

ROOT = Path("D:/TLGL")
O = ROOT / ".scratch/skelcmp"
BIN = ROOT / "tlbb-explorer/target/debug/skel_dump.exe"
FAMILIES = int(sys.argv[1]) if len(sys.argv) > 1 else 6

con = sqlite3.connect("file:" + (ROOT / ".scratch/resources.db").as_posix() + "?mode=ro", uri=True)
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))

dropped = 0


def names_from(json_path):
    """骨架侧骨名：只认 nodes[].name。"""
    global dropped
    j = json.loads(json_path.read_text(encoding="utf-8"))
    out = []
    for n in j.get("nodes") or []:
        v = n.get("name") if isinstance(n, dict) else None
        if isinstance(v, str) and v.strip():
            out.append(v.lower())
        elif isinstance(v, str):
            dropped += 1
    return out


def track_names(json_path):
    """动画侧：只认 animations[0].tracks[].bone，去重保序。"""
    global dropped
    j = json.loads(json_path.read_text(encoding="utf-8"))
    an = (j.get("animations") or [{}])[0]
    seen, out = set(), []
    for t in an.get("tracks") or []:
        v = t.get("bone") if isinstance(t, dict) else None
        if isinstance(v, str) and v.strip():
            k = v.lower()
            if k not in seen:
                seen.add(k)
                out.append(k)
        elif isinstance(v, str):
            dropped += 1
    return out


def dump_mesh(name):
    f = O / (name + ".skel.json")
    if not f.is_file():
        subprocess.run([str(BIN), "--root", "D:/TLGL", "--name", name, "--out", str(O)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return f if f.is_file() else None


def dump_ani(h):
    f = O / (h + ".skel.json")
    if not f.is_file():
        subprocess.run([str(BIN), "--root", "D:/TLGL", "--ani", h, "--out", str(O)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return f if f.is_file() else None


# 变体目录 → 同族本体
var = {}
for h, p in side.items():
    if not p.lower().endswith(".ani"):
        continue
    parts = p.replace("\\", "/").split("/")
    low = [x.lower() for x in parts]
    if "ani" not in low[:-1]:
        continue
    var.setdefault(parts[low.index("ani") - 1], []).append((h, parts[-1]))

bases = sorted({re.sub(r"_b\d+.*$", "_b0", d) for d in var if re.search(r"_b\d", d)})[:FAMILIES]
rows = []
for base in bases:
    meshes = [str(r[0]).replace("\\", "/").split("/")[-1][:-5]
              for (r,) in con.execute(
                  "select path from resources where path like ? and path like ?",
                  ("%/" + base + "/%", "%.mesh"))]
    union, per = set(), []
    for m in meshes:
        f = dump_mesh(m)
        if not f:
            continue
        ns = names_from(f)
        per.append((m, len(ns)))
        union |= set(ns)
    kids = [d for d in var if re.sub(r"_b\d+.*$", "_b0", d) == base]
    for d in kids[:1]:
        for h, fn in var[d][:2]:
            f = dump_ani(h)
            if not f:
                continue
            tb = track_names(f)
            miss = sorted(set(tb) - union)
            rows.append({"base": base, "n_mesh": len(meshes), "union": len(union),
                         "ani": fn, "tracks": len(tb), "miss": len(miss),
                         "miss_sample": miss[:5]})
            print(f"  {base:<34} 网格 {len(meshes):>2} 份 · 并集 {len(union):>4} 根"
                  f" | {fn:<40} 轨道 {len(tb):>3} · 不在并集 {len(miss):>3}")
            if per:
                print("      各份网格自报骨名：", ", ".join(f"{m}:{n}" for m, n in per[:5]))

ok = sum(1 for r in rows if r["miss"] == 0)
part = sum(1 for r in rows if 0 < r["miss"] <= 3)
print(f"\n== {len(rows)} 条变体动画：并集后**全在**的 {ok} 条 · 只差 1~3 根的 {part} 条")
print("   剔掉的空名：", dropped)
allmiss = {}
for r in rows:
    for m in r["miss_sample"]:
        allmiss[m] = allmiss.get(m, 0) + 1
print("   最常见「并集里也没有」的骨名：", sorted(allmiss.items(), key=lambda kv: -kv[1])[:8])
(O / "union_compare.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
