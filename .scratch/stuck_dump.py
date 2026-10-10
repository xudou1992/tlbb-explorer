#!/usr/bin/env python3
"""把「真卡半路」最大几族的卡点前后字节摊开看形状。

只读，不改判据。目的：找出 `tail_try_entry` 那段可变长填充
（`[u32 n] → p += 4 + 8n`）之外还有没有别的步长。
"""
import collections
import re

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m:
        rows.append(m.groups())

mid = [r for r in rows if 0 < int(r[3]) < int(r[4])]
grp = collections.Counter(f"{e}/{d}" for _, _, _, e, d in mid)
print("真卡半路", len(mid), "份；最大几族：", grp.most_common(6))


def dump(p, stop, back=48, fwd=64):
    fp = p.replace("\\", "/")
    i = fp.find("/.scratch/")
    fp = fp[i + 1:] if i >= 0 else fp
    b = open(fp, "rb").read()
    lo = max(0, stop - back)
    seg = b[lo:stop + fwd]
    print(f"  文件 {fp.split('/')[-1]} 大小 {len(b)} 卡在 {hex(stop)}")
    for off in range(0, len(seg), 16):
        chunk = seg[off:off + 16]
        u32s = " ".join(f"{int.from_bytes(chunk[i:i+4],'little'):>10}" if len(chunk) >= i + 4 else ""
                        for i in range(0, len(chunk), 4))
        asc = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        mark = "  ← 卡点" if lo + off <= stop < lo + off + 16 else ""
        print(f"    {hex(lo+off):>8} {chunk.hex(' ')}  |{asc}|  u32[{u32s}]{mark}")


for key, _ in grp.most_common(3):
    e, d = key.split("/")
    pick = [r for r in mid if r[3] == e and r[4] == d][:2]
    print(f"\n===== 族 吃了 {key}，抽 {len(pick)} 份 =====")
    for p, s, st, ee, dd in pick:
        dump(p, int(st, 16))
