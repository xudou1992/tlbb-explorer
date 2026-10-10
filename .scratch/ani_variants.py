#!/usr/bin/env python3
"""全库 .ani 版式普查：魔数族 + 0x98 版式选择子 + 两套尺寸公式对账。

IDA 侧证据（sub_14072F6F0，.ani 装载器）：
  0x8C u32 魔数：判据 (v-0x324E494D) & 0xFCFFFFFF == 0 且 v != 0x354E494D
                 → 放行 "MIN2"/"MIN3"/"MIN6"/"MIN7"（第 4 字节低两 bit 随意），
                   而 "MIN5" 被单独排除
  0x98 u32 版式选择子：==1 走一套尺寸，==13 走另一套
  版式 13 的尺寸：名字块 30*(骨数+7)、每骨 44B(8 对齐)、每帧 76B(8 对齐)、
                 另有 4*骨数 与 4*帧数 两块
  版式 1 的尺寸：从 0xCA 起 [u32 n][4n][12*帧数*n][?]

用法：python ani_variants.py [树根]
"""
import json
import os
import struct
import sys
from collections import Counter

ROOT = sys.argv[1] if len(sys.argv) > 1 else r"D:\TLGL\.scratch\out\tree"
files = []
for dirpath, _, names in os.walk(ROOT):
    for n in names:
        if n.lower().endswith(".ani"):
            files.append(os.path.join(dirpath, n))

magic = Counter()
kind = Counter()
pair = Counter()
fit = Counter()
rows = []
skipped = 0
for p in files:
    try:
        with open(p, "rb") as f:
            head = f.read(0x200)
            size = os.path.getsize(p)
    except OSError:
        skipped += 1
        continue
    if len(head) < 0xD0:
        skipped += 1
        continue
    m = head[0x8C:0x90].decode("latin1")
    k = struct.unpack_from("<I", head, 0x98)[0]
    bones = struct.unpack_from("<H", head, 0xBA)[0]
    frames = struct.unpack_from("<H", head, 0xC2)[0]
    tick = struct.unpack_from("<f", head, 0xC6)[0]
    magic[m] += 1
    kind[k] += 1
    pair[(m, k)] += 1
    # 我们现有口径：轨道区 = 骨数 × 帧数 × 32B，从文件尾往回数收口
    tail = size - bones * frames * 32
    fit["尾区收口合理" if 0xF0 <= tail <= 0x2000 else "尾区不收口"] += 1
    rows.append({"path": os.path.relpath(p, ROOT).replace("\\", "/"), "magic": m,
                 "kind": k, "bones": bones, "frames": frames, "tick": round(tick, 4),
                 "size": size, "tail": tail})

print(f"份数 {len(rows)}（跳过 {skipped}）")
print("魔数:", dict(magic.most_common(12)))
print("0x98 版式选择子:", dict(kind.most_common(12)))
print("(魔数, 版式) 前 12:", dict(pair.most_common(12)))
print("我们的 32B 轨道口径:", dict(fit.most_common()))
by = {}
for r in rows:
    by.setdefault((r["magic"], r["kind"]), []).append(r)
print()
for key, rs in sorted(by.items(), key=lambda kv: -len(kv[1]))[:8]:
    r = rs[0]
    sizes = sorted({x["size"] for x in rs})[:3]
    print(f"{key} 共 {len(rs)} 份 · 例 {r['path']} 骨{r['bones']} 帧{r['frames']} tick{r['tick']} size{r['size']} tail{r['tail']}")
with open(r"D:\TLGL\.scratch\ani_variants.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, ensure_ascii=False)
print("\n明细 → .scratch/ani_variants.json")
