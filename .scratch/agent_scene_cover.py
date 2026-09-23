"""Quantify how much of every map's instance table decodes under the confirmed grammar.

header [u32 N][u32 753][u32 0] + N x 761B records
record = f32[16] row-major affine (4th col 0,0,0,1 ; 4th row x,y,z,1) + char name[697]
"""
import re
import sqlite3
import struct
from pathlib import Path

TREE = Path(r"D:\TLGL\.scratch\out\tree")
NAME = re.compile(rb"^[ -~]{3,80}?\.(mesh|tani)$")
con = sqlite3.connect("file:resources.db?mode=ro", uri=True)
paths = [r[0] for r in con.execute(
    "SELECT path FROM resources WHERE lower(path) LIKE '%.scene' AND path IS NOT NULL")]
maps = {}
for p in paths:
    s = p.split("/")
    if len(s) > 2 and s[0] == "mobile_maps":
        maps.setdefault(s[1], []).append(p)

files = inst = inst_ok = blank = badmat = 0
per_map = []
cov = {}
for mp, rels in maps.items():
    m_files = m_inst = m_ok = 0
    for rel in rels:
        f = TREE / rel
        if not f.exists():
            continue
        raw = f.read_bytes()
        if len(raw) < 64:
            continue
        N = struct.unpack_from("<I", raw, 0)[0]
        if not N or 12 + 761 * N > len(raw) + 761:
            continue
        good = 0
        for i in range(N):
            off = 12 + 761 * i
            if off + 761 > len(raw):
                break
            m = struct.unpack_from("<16f", raw, off)
            col = (m[3], m[7], m[11], m[15])
            if not (all(abs(c) < 1e-5 for c in col[:3]) and abs(col[3] - 1) < 1e-4):
                badmat += 1
                continue
            nb = raw[off + 64 : off + 761].split(b"\x00")[0]
            if not nb:
                blank += 1
            elif NAME.match(nb):
                good += 1
        m_files += 1
        m_inst += N
        m_ok += good
    files += m_files
    inst += m_inst
    inst_ok += m_ok
    per_map.append((mp, m_files, m_inst, m_ok, round(100 * m_ok / max(m_inst, 1), 1)))
    for _n, size in ((None, 0),):
        pass

per_map.sort(key=lambda r: -r[4])
print(f"地图数 {len(per_map)}  非空格子文件 {files}  实例记录 {inst:,}  解出可用网格名 {inst_ok:,}"
      f" = {100*inst_ok/max(inst,1):.2f}%")
print(f"矩阵不成立 {badmat:,}  名字为空 {blank:,}")
print("\n覆盖率最好的 8 张图 / 最差的 8 张图：")
for r in per_map[:8] + [None] + per_map[-8:]:
    if r is None:
        print("  ...")
        continue
    print("  %-30s 格子 %4d  实例 %6d  可用 %6d  %5.1f%%" % r)
hi = sum(1 for r in per_map if r[4] >= 95)
lo = sum(1 for r in per_map if r[4] < 50)
print(f"\n≥95% 可用的地图 {hi} 张；<50% 的 {lo} 张；共 {len(per_map)} 张")
