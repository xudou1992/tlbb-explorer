#!/usr/bin/env python3
"""量一件事：尾部错开 2 字节那一族，96B 绑定记录与影响顶点表在 2 mod 4 上读不读得出来。

parse_nodes 现在按 4 步长扫（geometry.rs:576），所以这 157 份「有骨架树、没骨位、没权重」。
先量再改：若在 2 mod 4 上能认出成规模的记录、且权重表逐顶点加起来 ≈1，
那才值得把 ALIGN_PROBE 也用到 parse_nodes；量不出来就别动（权重是会被界面直接消费的）。
"""
import struct
import sys

FILES = [
    r"D:/TLGL/.scratch/out/tree/data/source/npc/quest/w1351_boss_caoshuang/w1351_boss_caoshuang01_yifu_001.mesh",
    r"D:/TLGL/.scratch/out/tree/data/source/npc/quest/w1351_boss_caoshuang/w1351_boss_caoshuang01_shoutao_001.mesh",
    r"D:/TLGL/.scratch/out/tree/data/source/npc/quest/w1351_boss_renpingsheng/w1351_boss_renpingsheng_yifu_001.mesh",
]


def printable_name(raw, i):
    b = raw[i:i + 32]
    if len(b) < 32:
        return None
    z = b.find(0)
    if z < 3 or any(c < 0x20 or c > 0x7e for c in b[:z]):
        return None
    prev = raw[i - 1]
    if 0x20 <= prev <= 0x7e or prev == 0:  # 名字前一个字节不能还是名字字符（撞假阳性的老坑）
        return None
    return b[:z].decode("ascii")


def good_matrix(m):
    """D3DX 行向量：前三行两两垂直、等比，m[15]==1。"""
    rows = [m[0:4], m[4:8], m[8:12]]
    if abs(m[15] - 1.0) > 1e-5:
        return False
    lens = []
    for r in rows:
        L = sum(x * x for x in r) ** 0.5
        if L < 1e-4:
            return False
        lens.append(L)
    spread = max(lens) - min(lens)
    if spread / max(lens) > 1e-3:
        return False
    for a in range(3):
        for b in range(a + 1, 3):
            d = sum(rows[a][k] * rows[b][k] for k in range(3))
            if abs(d) > 1e-3 * lens[a] * lens[b]:
                return False
    return True


def skin_table(raw, off):
    """[u32 N][N 个严格递增 u32][N 个 f32]，回来 (顶点号, 权重, 下一偏移) 或 None。"""
    n = struct.unpack_from("<I", raw, off)[0]
    if not 0 < n <= 20000:
        return None
    ids = struct.unpack_from("<%dI" % n, raw, off + 4)
    if any(ids[k] >= ids[k + 1] for k in range(n - 1)):
        return None
    woff = off + 4 + 4 * n
    if woff + 4 * n > len(raw):
        return None
    ws = struct.unpack_from("<%df" % n, raw, woff)
    if any(not 0.0 <= w <= 1.0001 for w in ws):
        return None
    return ids, ws, woff + 4 * n


for p in FILES:
    raw = open(p, "rb").read()
    declared = struct.unpack_from("<I", raw, 0x110)[0]
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    print("\n###", p.split("/")[-1], "声明骨", declared, "顶点", vc, "大小", len(raw))
    for mod in (0, 2):
        found = []
        i = 0x118 + mod
        while i + 96 <= len(raw):
            nm = printable_name(raw, i)
            if nm:
                m = struct.unpack_from("<16f", raw, i + 32)
                if all(x == 0.0 for x in m[:12]):
                    i += 4
                    continue
                if good_matrix(m):
                    st = skin_table(raw, i + 96)
                    found.append((i, nm, st is not None))
                    i += 96
                    continue
            i += 4
        recs = len(found)
        with_skin = sum(1 for f in found if f[2])
        print(f"  起点 {0x118+mod:#x} 步长 4（即 {mod} mod 4）：认得 {recs} 条 96B 记录，带影响表 {with_skin}")
        if recs:
            print("    样本:", ", ".join(f"{n}{'*' if s else ''}" for _, n, s in found[:10]))
