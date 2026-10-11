#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全量判决：每个「只剩动画」的变体角色，抽一条自己的 .ani，比它的同族本体 _b0.ske 骨名名单。
把 6/2,995 那条样本结论推成 235 个族的判决。跑法：
  python .scratch/dyn/ske_sweep.py          # 每族 1 条动画（约 235 次动画导出）
  python .scratch/dyn/ske_sweep.py 3        # 每族 3 条
"""
import json
import re
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("D:/TLGL")
TREE = ROOT / ".scratch/out/tree"
O = ROOT / ".scratch/skelcmp"
BIN = str(ROOT / "tlbb-explorer/target/debug/skel_dump.exe")
PER = int(sys.argv[1]) if len(sys.argv) > 1 else 1

con = sqlite3.connect("file:" + (ROOT / ".scratch/resources.db").as_posix() + "?mode=ro", uri=True)
side = json.loads((ROOT / ".scratch/cfg_named_sidecar.json").read_text(encoding="utf-8"))


def strings_of_jbcf(raw):
    """JBCF 字符串表：[id][size][flag][count][count*(len,hash)][chars]。与 pathmap.rs 同语法。"""
    import struct
    if len(raw) < 32 or raw[:4] != b"JBCF":
        return None
    # 只认字符串表（id=85）。上一版允许 86，而 86 就是根 chunk 自己——
    # 从 off=16 起扫必然先撞上它，把根头当表读，名单全是乱码（229 那个判决就是这么来的）。
    root_size = struct.unpack_from("<I", raw, 20)[0]
    first = 16 + 8 + ((root_size + 7) // 8) * 8
    offs = [first] + list(range(16, min(len(raw) - 16, 2_000_000), 4))
    for off in offs:
        try:
            sid, size, flag, count = struct.unpack_from("<4I", raw, off)
        except struct.error:
            continue
        if count == 0 or count > 400000 or sid != 85:
            continue
        desc, chars = off + 16, off + 16 + 8 * count
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


def ani_tracks(h):
    f = O / (h + ".skel.json")
    if not f.is_file():
        subprocess.run([BIN, "--ani", h, "--root", "D:/TLGL", "--out", str(O)],
                       capture_output=True, text=True)
    if not f.is_file():
        return None
    j = json.loads(f.read_text(encoding="utf-8"))
    an = (j.get("animations") or [{}])[0]
    out = []
    for t in an.get("tracks") or []:
        v = str(t.get("bone") or "").lower().strip()
        if v and v not in out:
            out.append(v)
    return out


by_variant = defaultdict(list)
for h, p in side.items():
    q = p.replace(chr(92), "/")
    if not q.lower().endswith(".ani") or "/ani/" not in q.lower():
        continue
    parts = q.split("/")
    low = [x.lower() for x in parts]
    i = low.index("ani")
    by_variant[parts[i - 1]].append((h, parts[-1]))

print("待判的变体角色目录：", len(by_variant))

hit = full = partial = noske = noani = 0
worst = []
for k, (variant, items) in enumerate(sorted(by_variant.items()), 1):
    base = re.sub(r"_b\d+.*$", "_b0", variant)
    ske = TREE / "data/source/npc/quest" / base / (base + ".ske")
    if not ske.is_file():
        cand = list((TREE).rglob(base + ".ske"))
        ske = cand[0] if cand else None
    if ske is None:
        noske += 1
        continue
    names = strings_of_jbcf(ske.read_bytes())
    if not names:
        noske += 1
        continue
    boneish = {s.lower() for s in names if s.strip() and ("bip" in s.lower() or "bone" in s.lower())}
    if not boneish:
        boneish = {s.lower() for s in names if s.strip()}
    done = 0
    for h, fn in items[:PER]:
        tb = ani_tracks(h)
        if not tb:
            continue
        done += 1
        miss = set(tb) - boneish
        if not miss:
            full += 1
        elif len(miss) <= 2:
            partial += 1
            worst.append((len(miss), variant, fn, sorted(miss)[:3]))
        else:
            hit += 1
            if len(worst) < 25:
                worst.append((len(miss), variant, fn, sorted(miss)[:3]))
    if done == 0:
        noani += 1
    if k % 40 == 0:
        print(f"  已判 {k}/{len(by_variant)} 个角色目录 …")

print(f"\n== 判决（每族取 {PER} 条动画）")
print(f"   轨道骨名**全在** _b0.ske 名单里：{full}")
print(f"   只差 1~2 根：{partial}")
print(f"   差 3 根以上：{hit}")
print(f"   找不到本体 .ske 或字符串表读不出：{noske} · 动画解不出：{noani}")
if worst:
    print("   差得最多的几个：")
    for w in sorted(worst, reverse=True)[:10]:
        print("     ", w)
(O / "ske_sweep.json").write_text(json.dumps(
    {"per": PER, "full": full, "off_by_1_2": partial, "off_by_3plus": hit,
     "no_ske": noske, "no_ani": noani, "worst": worst[:60]}, ensure_ascii=False, indent=2),
    encoding="utf-8")
