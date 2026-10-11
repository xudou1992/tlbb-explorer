#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读 .ske 的 JBCF 字符串表拿骨名（10-10 已定性：.ske 是**扁平骨名清单**，不是父骨链），
与部件网格自报的骨名并起来，再比变体动画的轨道骨名。
这一步才是「一副骨架 vs 一条动画」的正确口径。"""
import json
import struct
import subprocess
from pathlib import Path

ROOT = Path("D:/TLGL")
TREE = ROOT / ".scratch/out/tree"
O = ROOT / ".scratch/skelcmp"
BIN = str(ROOT / "tlbb-explorer/target/debug/skel_dump.exe")


def strings_of_jbcf(raw):
    """照 pathmap.rs 的语法：根 chunk 之后是字符串表 [size][flag][count][count*(len,hash)][chars]。"""
    if len(raw) < 32 or raw[:4] != b"JBCF":
        return None
    body = struct.unpack_from("<I", raw, 12)[0]
    if body + 16 != len(raw) and body == 0:
        return None
    root_size = struct.unpack_from("<I", raw, 20)[0]
    cands = [16 + 8 + ((root_size + 7) // 8) * 8, 16 + 8]
    for off in cands + list(range(16, min(len(raw) - 16, 200000), 4)):
        try:
            sid = struct.unpack_from("<I", raw, off)[0]
            size = struct.unpack_from("<I", raw, off + 4)[0]
            flag = struct.unpack_from("<I", raw, off + 8)[0]
            count = struct.unpack_from("<I", raw, off + 12)[0]
        except struct.error:
            continue
        if count == 0 or count > 400000 or sid not in (85, 84, 86):
            continue
        desc = off + 16
        chars = desc + 8 * count
        if chars > len(raw):
            continue
        lens = [struct.unpack_from("<I", raw, desc + 8 * i)[0] for i in range(count)]
        if any(l > 4096 for l in lens) or chars + sum(lens) > len(raw) + 8:
            continue
        out, p = [], chars
        for l in lens:
            out.append(raw[p:p + l].decode("utf-8", "replace"))
            p += l
        if out:
            return out
    return None


def mesh_names(h):
    f = O / (h + ".skel.json")
    if not f.is_file():
        subprocess.run([BIN, "--name", h, "--root", "D:/TLGL", "--out", str(O)],
                       capture_output=True, text=True)
    j = json.loads(f.read_text(encoding="utf-8"))
    return {str(n.get("name")).lower() for n in (j.get("nodes") or [])
            if isinstance(n, dict) and str(n.get("name") or "").strip()}


def ani_tracks(h):
    f = O / (h + ".skel.json")
    if not f.is_file():
        subprocess.run([BIN, "--ani", h, "--root", "D:/TLGL", "--out", str(O)],
                       capture_output=True, text=True)
    j = json.loads(f.read_text(encoding="utf-8"))
    an = (j.get("animations") or [{}])[0]
    seen = []
    for t in an.get("tracks") or []:
        v = str(t.get("bone") or "").lower().strip()
        if v and v not in seen:
            seen.append(v)
    return seen


side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))
norm = {h: p.replace(chr(92), "/") for h, p in side.items()}

cases = [("w1351_pets_daishu_b0", "w1351_pets_daishu_b1_2_3", "d160aeb6"),
         ("w1351_pets_daidainiu_b0", "w1351_pets_daidainiu_b3", "d91f2bec"),
         ("w1351_pets_bawanglong_b0", "w1351_pets_bawanglong_b2", "52cf4690")]

for base, variant, mesh_prefix in cases:
    ske = TREE / "data/source/npc/quest" / base / (base + ".ske")
    if not ske.is_file():
        print("× 没有解包好的", base + ".ske（先跑解包或换 out/tree 路径）")
        continue
    names = strings_of_jbcf(ske.read_bytes())
    if names is None:
        print("×", base, ".ske 字符串表读不出来")
        continue
    boneish = [s for s in names if s.strip() and ("bip" in s.lower() or "bone" in s.lower())]
    mesh_hash = [h for h in side if h.startswith(mesh_prefix)]
    mset = mesh_names(mesh_hash[0]) if mesh_hash else set()
    union = mset | {s.lower() for s in boneish}
    print(f"== {base}.ske 字符串 {len(names)} 条 · 像骨名的 {len(boneish)} 条 · "
          f"部件网格自报 {len(mset)} 根 · 合起来 {len(union)} 根")
    hs = [(h, p) for h, p in norm.items() if variant in p and p.lower().endswith(".ani")]
    for h, p in hs[:2]:
        tb = ani_tracks(h)
        if not tb:
            continue
        miss = sorted(set(tb) - union)
        print(f"   {p.split('/')[-1]:<44} 轨道 {len(tb):>3} · 仍不在骨架里 {len(miss):>3} {miss[:6]}")
