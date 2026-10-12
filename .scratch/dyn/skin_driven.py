#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最后一环：本体**部件网格自报的那些骨**（也就是蒙皮权重真正挂着的那批），
是不是都被变体动画的轨道驱动。
名字在 .ske 名单里只说明「骨架有这根」，而权重挂在网格自报的那几根上——
网格自报 ⊆ 动画轨道，挂上去才不会有蒙着的骨不动。"""
import json
import re
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path("D:/TLGL")
O = ROOT / ".scratch/skelcmp"
BIN = str(ROOT / "tlbb-explorer/target/debug/skel_dump.exe")
N = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 25
BS = chr(92)

con = sqlite3.connect("file:" + (ROOT / ".scratch/resources.db").as_posix() + "?mode=ro", uri=True)
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))
norm = {h: p.replace(BS, "/") for h, p in side.items()}


def skel(ident, ani):
    f = O / (ident + ".skel.json")
    if not f.is_file():
        subprocess.run([BIN, "--ani" if ani else "--name", ident, "--root", "D:/TLGL", "--out", str(O)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


by_variant = {}
for h, p in norm.items():
    if not p.lower().endswith(".ani") or "/ani/" not in p.lower():
        continue
    parts = p.split("/")
    low = [x.lower() for x in parts]
    i = low.index("ani")
    by_variant.setdefault(parts[i - 1], []).append((h, parts[-1]))

bases = []
for v in sorted(by_variant):
    b = re.sub(r"_b\d+.*$", "_b0", v)
    if b != v:
        bases.append((b, v))
seen, done = set(), 0
ok = short = nomesh = 0
lines = []
for base, variant in bases:
    if base in seen or done >= N:
        continue
    seen.add(base)
    mh = [str(r) for (r,) in con.execute("select hash from resources where path like ?",
                                         ("%/" + base + ".mdl",))]
    mesh_hash = None
    if mh:
        for (ph,) in con.execute("select to_hash from relations where from_hash=? and rel='model-part'", (mh[0],)):
            t = con.execute("select type from resources where hash=?", (str(ph),)).fetchone()
            if t and str(t[0]) == "mesh":
                mesh_hash = str(ph)
                break
    if not mesh_hash:
        nomesh += 1
        continue
    mj = skel(mesh_hash, False)
    if not mj:
        nomesh += 1
        continue
    mnodes = {str(n.get("name")).lower().strip() for n in (mj.get("nodes") or [])
              if isinstance(n, dict) and str(n.get("name") or "").strip()}
    if not mnodes:
        nomesh += 1
        continue
    h, fn = by_variant[variant][0]
    aj = skel(h, True)
    if not aj:
        continue
    tracks = []
    for a in aj.get("animations") or []:
        for t in a.get("tracks") or []:
            v = str(t.get("bone") or "").lower().strip()
            if v and v not in tracks:
                tracks.append(v)
        break
    if not tracks:
        continue
    done += 1
    undriven = sorted(mnodes - set(tracks))
    if undriven:
        short += 1
        if len(lines) < 30:
            lines.append(f"{base} 网格自报 {len(mnodes)} · 变体轨道 {len(tracks)} · "
                         f"**没被驱动的蒙皮骨 {len(undriven)}** {undriven[:5]}")
    else:
        ok += 1
        if len(lines) < 30:
            lines.append(f"{base} 网格自报 {len(mnodes)} · 变体轨道 {len(tracks)} · 全被驱动")

print(f"== 蒙皮骨有没有被驱动（比了 {done} 个本体）")
print(f"   网格自报的骨**全部**被变体动画驱动：{ok}")
print(f"   有漏：{short} · 取不到网格/动画：{nomesh}")
for l in lines[:20]:
    print("   ", l)
(O / "skin_driven.json").write_text(json.dumps({"compared": done, "ok": ok, "short": short,
                                                "no_mesh": nomesh, "lines": lines},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
