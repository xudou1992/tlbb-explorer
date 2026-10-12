#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""变体到底是不是自成一整套：拿 sidecar 里**变体自己那份匿名网格**（10-12 才发现它们在包里），
与同一目录里变体自己的动画比轨道骨名。
若网格自报的骨全被动画驱动，那「必须借本体 _b0 的网格渲染」这句就错了。"""
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("D:/TLGL")
O = ROOT / ".scratch/skelcmp"
BIN = str(ROOT / "tlbb-explorer/target/debug/skel_dump.exe")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
BS = chr(92)

side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))
norm = {h: p.replace(BS, "/") for h, p in side.items()}


def skel(ident, ani):
    f = O / (ident + ".skel.json")
    if not f.is_file():
        subprocess.run([BIN, "--ani" if ani else "--name", ident, "--root", "D:/TLGL",
                        "--out", str(O)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


by_dir = defaultdict(lambda: {"mesh": [], "ani": [], "ske": [], "mdl": []})
def char_dir(path):
    """归一到**角色目录**：动画在 …/角色/ani/ 下，网格材质在 …/角色/ 下，
    上一版直接用文件的父目录，两边凑不到一起，所以 14 个全算「取不到样」。"""
    parts = path.replace(chr(92), "/").split("/")
    low = [x.lower() for x in parts]
    for sub in ("ani", "texture", "mesh"):
        if sub in low[:-1]:
            return "/".join(parts[:low.index(sub)])
    return "/".join(parts[:-1])


for h, p in norm.items():
    q = p.lower()
    for kind, ext in (("mesh", ".mesh"), ("ani", ".ani"), ("ske", ".ske"), ("mdl", ".mdl")):
        if q.endswith(ext):
            by_dir[char_dir(p)][kind].append(h)
            break

variants = sorted(d for d in by_dir if re.search(r"_b\d", d))[:N]
full = part = none = 0
lines = []
for d in variants:
    e = by_dir[d]
    if not e["mesh"] or not e["ani"]:
        none += 1
        continue
    nodes = set()
    for mh in e["mesh"]:
        j = skel(mh, False)
        if not j:
            continue
        for n in j.get("nodes") or []:
            v = str((n or {}).get("name") or "").lower().strip() if isinstance(n, dict) else ""
            if v:
                nodes.add(v)
    if not nodes:
        none += 1
        continue
    ah = e["ani"][0]
    j = skel(ah, True)
    tracks = set()
    if j:
        for a in j.get("animations") or []:
            for t in a.get("tracks") or []:
                v = str(t.get("bone") or "").lower().strip()
                if v:
                    tracks.add(v)
            break
    if not tracks:
        none += 1
        continue
    undriven = sorted(nodes - tracks)
    name = d.rsplit("/", 1)[-1]
    if not undriven:
        full += 1
        lines.append(f"{name:<34} 自己网格 {len(nodes):>3} 根 · 自己动画 {len(tracks):>3} 根 · 全被驱动")
    else:
        deform = sorted(x for x in undriven if not re.match(
            r"^(origin|top|tx_|.*footsteps)", x))
        part += 1
        lines.append(f"{name:<34} 自己网格 {len(nodes):>3} · 动画 {len(tracks):>3} · 没驱动 {len(undriven)}"
                     f"（其中形变骨 {len(deform)}：{deform[:4]}）")

print(f"== 变体是否自成一整套（比了 {full + part} 个变体目录，取不到样 {none}）")
print(f"   自己的网格**全被**自己的动画驱动：{full}")
print(f"   有未驱动的骨：{part}")
for l in lines:
    print("   ", l)
(O / "self_contained.json").write_text(json.dumps(
    {"full": full, "with_undriven": part, "no_sample": none, "lines": lines},
    ensure_ascii=False, indent=2), encoding="utf-8")
