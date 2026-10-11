#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整骨架 vs 一条动画：沿 .mdl 的 model-part 清单把所有**部件网格**的骨名取并集，
再比变体动画的轨道骨名。前几轮栽在「只取目录里那份有路径的网格」，那是整副骨架的一片。"""
import json
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path("D:/TLGL")
O = ROOT / ".scratch/skelcmp"
BIN = str(ROOT / "tlbb-explorer/target/debug/skel_dump.exe")
SEP = chr(92)  # 反斜杠：绝不用字面量，今天已经两次被 shell/heredoc 吃掉

con = sqlite3.connect("file:" + (ROOT / ".scratch/resources.db").as_posix() + "?mode=ro", uri=True)
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))
norm = {h: p.replace(SEP, "/") for h, p in side.items()}


def run(args):
    return subprocess.run([BIN] + args + ["--root", "D:/TLGL", "--out", str(O)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def node_names(ident, ani=False):
    f = O / (ident + ".skel.json")
    if not f.is_file():
        run(["--ani" if ani else "--name", ident])
    if not f.is_file():
        return None
    j = json.loads(f.read_text(encoding="utf-8"))
    return [str(n.get("name")).lower() for n in (j.get("nodes") or [])
            if isinstance(n, dict) and str(n.get("name") or "").strip()], j


pairs = (("w1351_pets_daishu_b0", "w1351_pets_daishu_b1_2_3"),
         ("w1351_pets_daidainiu_b0", "w1351_pets_daidainiu_b3"),
         ("w1351_pets_bawanglong_b0", "w1351_pets_bawanglong_b2"))

for base, variant in pairs:
    mh = [str(r) for (r,) in con.execute("select hash from resources where path like ?",
                                         ("%/" + base + ".mdl",))]
    if not mh:
        print("× 清单里没有", base + ".mdl")
        continue
    parts = [str(r) for (r,) in con.execute(
        "select to_hash from relations where from_hash=? and rel='model-part'", (mh[0],))]
    kinds = {}
    for ph in parts:
        row = con.execute("select type from resources where hash=?", (ph,)).fetchone()
        kinds[ph] = str(row[0]) if row else "不在库里"
    tally = {}
    for t in kinds.values():
        tally[t] = tally.get(t, 0) + 1
    meshes = [p for p, t in kinds.items() if t == "mesh"]
    union, per = set(), []
    for m in meshes:
        got = node_names(m)
        if not got:
            continue
        ns = got[0]
        per.append((m[:8], len(ns)))
        union |= set(ns)
    print("==", base, "· model-part", len(kinds), "个 · 类型", tally, "· mesh", len(meshes))
    print("   各部件自报骨名：", per, "· 并集", len(union), "根")
    if not union:
        print("   × 并集为空 = 取样失败，不比")
        continue
    cands = [(h, p) for h, p in norm.items() if variant in p and p.lower().endswith(".ani")]
    for h, p in cands[:2]:
        got = node_names(h, ani=True)
        if not got:
            continue
        an = (got[1].get("animations") or [{}])[0]
        tb = []
        for t in an.get("tracks") or []:
            v = str(t.get("bone") or "").lower().strip()
            if v and v not in tb:
                tb.append(v)
        if not tb:
            print("   × 这条动画没有轨道骨名，不比")
            continue
        miss = sorted(set(tb) - union)
        print(f"   {p.split('/')[-1]:<44} 轨道 {len(tb):>3} · 不在并集 {len(miss):>3} · {miss[:6]}")
