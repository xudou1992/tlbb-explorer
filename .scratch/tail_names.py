#!/usr/bin/env python3
"""尾巴那张矩阵**后面**的 40 字节是什么：像不像 [名字 32B][u32 计数]。"""
import os
import re
import struct

rows = []
for ln in open(".scratch/hier_stuck.txt", encoding="utf-8"):
    m = re.match(r"(D:\S+\.mesh)\t起点 (0x[0-9a-f]+)\t卡在 (0x[0-9a-f]+)\t吃了 (\d+)/(\d+) 条", ln)
    if m and m.group(4) == m.group(5):
        rows.append((m.group(1), int(m.group(3), 16)))


def fix(p):
    p = p.replace("\\", "/")
    i = p.find("/.scratch/")
    return p[i + 1:] if i >= 0 else p


print(f"条目已齐那族 {len(rows)} 份，看卡点矩阵之后 40 字节：")
for p, stop in rows[:10]:
    b = open(fix(p), "rb").read()
    at = stop + 64
    nm = b[at:at + 32].split(b"\x00")[0]
    cnt = struct.unpack("<I", b[at + 32:at + 36])[0] if at + 36 <= len(b) else None
    rest = b[at + 36:at + 44].hex(" ")
    printable = all(32 <= c < 127 for c in nm) if nm else False
    print(f"  {os.path.basename(p)[:36]:<36} 名字={nm!r:<30} 可读={printable} u32={cnt} 再 8B={rest}")
