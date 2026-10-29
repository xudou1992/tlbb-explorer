"""刀1/刀2/刀3 决定性取证（2026-10-07）：解析 .mesh 尾部条目流里的 64B 局部矩阵块。

背景：geometry.rs::parse_hierarchy 把每骨条目里的 mat64 块（64B 行主序 4×4，
前三行正交、末行平移）**跳过未用**（"用途未证，只识别"）。本脚本按同一字节文法
（tail_record_at / tail_is_u92 / tail_is_mat64 / tail_is_inf / tail_try_entry 逐条复刻，
判据一点不放宽）把每骨的数据块清单挖出来，然后检验语义：
  [K] 每骨块清单：96B 记录有无 / u92 数 / mat64 数 / 影响表大小
  [L] mat64（行主序 -> 列口径 R=t(rm).T, t=rm[12:16]）与 bind 局部 blocal 对照（记录骨）
  [M] mat64 与 .ani 第0帧局部的三种复合（mat∘A / A∘mat / 纯 mat）在 frame0 的世界
      vs bind 世界 B：逐骨 |Δt| / 角差 + 静态重心判据 —— 判「mat64 是不是引擎静置局部」
  [N] 无记录骨：mat64 平移 vs .ani 常量偏移（刀3 闭合）
输出 k2_mat64.txt
"""
import sys, struct, json, math
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, locals_frames, compose_worlds, ang

MESHES = {
    "yifu": r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_xiyuqiezei\w1351_monster_xiyuqiezei_yifu_001.mesh",
    "shoutao": r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_xiyuqiezei\w1351_monster_xiyuqiezei_shoutao_001.mesh",
}
NAME_FIELD = 32
NODE_RECORD = 96

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def f32(raw, at):
    if at + 4 > len(raw):
        return None
    return struct.unpack_from("<f", raw, at)[0]


def u32(raw, at):
    if at + 4 > len(raw):
        return None
    return struct.unpack_from("<I", raw, at)[0]


def name_at(raw, at):
    if at < 1 or at + 32 > len(raw):
        return None
    prev = raw[at - 1]
    if prev < 128 and (chr(prev).isalnum() or prev in b"_-."):  # Rust: is_ascii_alphanumeric
        return None
    nb = raw[at:at + 32]
    end = nb.find(0)
    if end < 3 or end > 31:
        return None
    ok = all(chr(c).isalnum() or c in b"_-." for c in nb[:end])
    if not ok:
        return None
    if any(c != 0 for c in nb[end:]):
        return None
    try:
        return nb[:end].decode("ascii")
    except UnicodeDecodeError:
        return None


def record_at(raw, at):
    nm = name_at(raw, at)
    if nm is None:
        return None
    m = []
    for k in range(16):
        v = f32(raw, at + 32 + k * 4)
        if v is None or not math.isfinite(v) or abs(v) >= 1e7:
            return None
        m.append(v)
    if abs(m[15] - 1.0) > 1e-3:
        return None
    rows = [m[0:3], m[4:7], m[8:11]]
    lens = [np.linalg.norm(r) for r in rows]
    if min(lens) <= 1e-6 or max(lens) / min(lens) > 1.05:
        return None
    for i in range(3):
        for k in range(i + 1, 3):
            d = sum(rows[i][t] * rows[k][t] for t in range(3))
            if abs(d) / (lens[i] * lens[k]) > 0.03:
                return None
    return nm, np.array(m, float).reshape(4, 4)  # 行主序原样


def is_u92(raw, at):
    d = f32(raw, at)
    if d is None or not (0.9 <= d <= 1.1):
        return False
    v = f32(raw, at + 20)
    if v is None or abs(v - d) > 1e-6:
        return False
    v = f32(raw, at + 40)
    if v is None or abs(v - d) > 1e-6:
        return False
    v = f32(raw, at + 60)
    if v is None or abs(v - 1.0) > 1e-3:
        return False
    return all(abs((f32(raw, at + o) or 0) - 100.0) < 1e-2 for o in (76, 80, 84))


def is_mat64(raw, at):
    m = []
    for k in range(16):
        v = f32(raw, at + k * 4)
        if v is None or not math.isfinite(v) or abs(v) >= 1e7:
            return None
        m.append(v)
    if abs(m[3]) > 1e-3 or abs(m[7]) > 1e-3 or abs(m[11]) > 1e-3 or abs(m[15] - 1.0) > 1e-3:
        return None
    rows = [m[0:3], m[4:7], m[8:11]]
    lens = [np.linalg.norm(r) for r in rows]
    if min(lens) <= 1e-4 or max(lens) / min(lens) > 1.05:
        return None
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) > 1e-2:
                return None
    return np.array(m, float).reshape(4, 4)


def is_inf(raw, at, vc):
    n = u32(raw, at)
    if n is None:
        return False
    if n == 0:
        return True
    if n > vc or at + 4 + 8 * n > len(raw):
        return False
    seen = set()
    for k in range(n):
        v = u32(raw, at + 4 + 4 * k)
        if v is None or v >= vc or v in seen:
            return False
        seen.add(v)
    for k in range(n):
        w = f32(raw, at + 4 + 4 * n + 4 * k)
        if w is None or not math.isfinite(w) or w < -1e-3 or w > 1.001:
            return False
    return True


def try_entry(raw, at, vc):
    """复刻 tail_try_entry，但把块记下来。返回 (entry, next) 或 None。"""
    p = at
    own = record_at(raw, p)
    if own is not None:
        p += NODE_RECORD
    blocks = []  # ("u92", 88) / ("mat64", 64, M) / ("inf", size, n)
    while True:
        if is_u92(raw, p):
            blocks.append(("u92", 88)); p += 88
            continue
        m = is_mat64(raw, p)
        if m is not None:
            blocks.append(("mat64", 64, m)); p += 64
            continue
        n = u32(raw, p)
        if n is not None and is_inf(raw, p, vc):
            blocks.append(("inf", 4 + 8 * n, n)); p += 4 + 8 * n
            continue
        break
    flag = u32(raw, p)
    if flag is None:
        return None
    p += 4
    nm1 = name_at(raw, p)
    nm2 = name_at(raw, p + 32) if nm1 is not None else None
    if nm1 is None or nm1 != nm2:
        return None
    if own is not None and own[0] != nm1:
        return None
    p += 64
    c = u32(raw, p)
    if c is None or c > 4096:
        return None
    p += 4
    children = []
    for _ in range(c):
        r = record_at(raw, p)
        if r is not None:
            children.append((r[0], r[1])); p += NODE_RECORD
        else:
            cn = name_at(raw, p)
            if cn is None:
                return None
            children.append((cn, None)); p += 32
    return dict(name=nm1, own=own[1] if own else None, blocks=blocks, children=children, flag=flag), p


def try_sockets(raw, at, vc):
    """复刻 tail_try_sockets：块链跳行 + [u32 1][u32 count][count×128B] 恰好到 EOF。"""
    p = at
    while p < len(raw):
        # 试收挂点段
        if u32(raw, p) == 1:
            cnt = u32(raw, p + 4)
            if cnt is not None:
                end = p + 8 + cnt * 128
                if cnt <= 4096 and end == len(raw):
                    socks = []
                    q = p + 8
                    good = True
                    for _ in range(cnt):
                        nm = name_at(raw, q)
                        bn = name_at(raw, q + 32)
                        m = []
                        for k in range(16):
                            v = f32(raw, q + 64 + k * 4)
                            if v is None or not math.isfinite(v) or abs(v) >= 1e7:
                                good = False; break
                            m.append(v)
                        if not good or nm is None or bn is None or abs(m[15] - 1.0) > 1e-3:
                            good = False; break
                        socks.append((nm, bn)); q += 128
                    if good and q == len(raw):
                        return socks
        if is_u92(raw, p):
            p += 88; continue
        if is_mat64(raw, p) is not None:
            p += 64; continue
        n = u32(raw, p)
        if n is not None and is_inf(raw, p, vc):
            p += 4 + 8 * n; continue
        return None
    return None


def parse_tail(path):
    raw = open(path, "rb").read()
    vc = struct.unpack_from("<I", raw, 0x8C)[0]
    # 起点：origin 记录 或 变体 [u32 -1][名字×2]
    starts = []
    for i in range(0, len(raw) - NODE_RECORD):
        r = record_at(raw, i)
        if r is not None and r[0] == "origin":
            starts.append(i)
    for i in range(0, len(raw) - 4 - 64):
        if u32(raw, i) == 0xFFFFFFFF:
            if name_at(raw, i + 4) is not None and name_at(raw, i + 4) == name_at(raw, i + 4 + 32):
                starts.append(i)
    for start in starts:
        p = start
        entries = []
        prelude = []
        sockets = None
        ok = True
        while p < len(raw):
            got = try_entry(raw, p, vc)
            if got is not None:
                entries.append(got[0]); p = got[1]
                continue
            r = record_at(raw, p)
            if r is not None:
                prelude.append(r[0]); p += NODE_RECORD
                continue
            sockets = try_sockets(raw, p, vc)
            if sockets is not None:
                p = len(raw)
                break
            ok = False
            break
        if ok and p == len(raw) and entries:
            return entries, prelude, vc, sockets
    return None, None, vc, None


for tag, meshpath in MESHES.items():
    say("#" * 72)
    say("=== [%s] .mesh 尾部条目流 ===" % tag)
    entries, prelude, vc, sockets = parse_tail(meshpath)
    if entries is None:
        say("  解析失败（没有可走到 EOF 的起点）")
        continue
    say("  前奏记录: %s" % prelude)
    say("  条目数 %d ; 挂点 %d 个: %s" % (len(entries), len(sockets or []), sockets))
    say("  条目数 %d" % len(entries))
    D = build(GLBS[tag])
    names_glb = D["names"]
    say("  与 GLB 骨名序列一致: %s" % ([e["name"] for e in entries] == names_glb))
    n_own = sum(1 for e in entries if e["own"] is not None)
    say("  自带 96B 记录的条目 %d（+孩子槽里的记录另计）" % n_own)
    say("  %-26s %6s %6s %8s %10s %s" % ("bone", "own96", "u92", "mat64", "infN", "mat64|t|"))
    for e in entries:
        mats = [b[2] for b in e["blocks"] if b[0] == "mat64"]
        infs = [b[2] for b in e["blocks"] if b[0] == "inf"]
        say("  %-26s %6s %6d %8d %10s %s" %
            (e["name"], "Y" if e["own"] is not None else "-",
             sum(1 for b in e["blocks"] if b[0] == "u92"), len(mats),
             ",".join(str(n) for n in infs),
             ("%.4f" % np.linalg.norm(mats[0][12:15])) if mats else "-"))

    # 每骨主 mat64（第一块）
    mat = {}
    for e in entries:
        mats = [b[2] for b in e["blocks"] if b[0] == "mat64"]
        if mats:
            mat[e["name"]] = mats[0]
    say("  带 mat64 的骨 %d/%d" % (len(mat), len(entries)))

    # ---- [L] mat64 vs blocal（列口径换算：R=t(rm).T, t=rm[12:15]）----
    say("\n  [L] mat64(列口径) vs bind 局部 blocal（记录骨）")
    nR = nT = nBoth = 0
    for j, nm in enumerate(names_glb):
        if nm not in mat:
            continue
        rm = mat[nm]
        Rc = rm[:3, :3].T
        tc = rm[3, :3]
        bl = D["blocal"][j]
        is_ph = np.linalg.norm(bl[:3, 3]) < 1e-6 and np.abs(bl[:3, :3] - np.eye(3)).max() < 1e-5
        if is_ph:
            continue
        dR = ang(Rc @ bl[:3, :3].T)
        dT = np.linalg.norm(tc - bl[:3, 3])
        eqR = dR < 0.01; eqT = dT < 1e-4
        nR += eqR; nT += eqT; nBoth += (eqR and eqT)
    say("    记录骨中: 旋转相等 %d / 平移相等 %d / 全等 %d" % (nR, nT, nBoth))

    json.dump({ "entries": [{ "name": e["name"], "own": e["own"] is not None,
                              "blocks": [(b[0], b[1]) for b in e["blocks"]],
                              "mats": [m.tolist() for m in (b[2] for b in e["blocks"] if b[0] == "mat64")] }
                            for e in entries]},
              open(r"D:\TLGL\.scratch\ani_axis\k2_mat64_%s.json" % tag, "w"))

open(r"D:\TLGL\.scratch\ani_axis\k2_mat64.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k2_mat64.txt")
