# -*- coding: utf-8 -*-
"""ResourcePath.cfg 自解 + 「贴图名注册路径 → path_hash」这一枪（只读）。

为什么要重打：`.scratch/tex_归属证据缺失_20261010.md` 桥 5 的目录宇宙来自
`resources.path`（只有名条目的目录），而 cfg 里贴图登记的路径大量落在
`.../<角色>/texture/` 这种**只装贴图、贴图又全是匿名**的目录 —— 这些目录从来没出现在
resources.path 里，所以旧穷举对它们结构性失明。cfg_named 数过「72,764 条整路径代哈希」，
但它按类型只报总数，没单独回答：**8,690 个悬空贴图名各自登记的那条路径，哈希落进匿名池几张？**
本脚本把这一枪打实，并顺手产出 15 条标注要用的精确覆盖表键。

纪律：只读 .scratch/unpacked/data/ResourcePath.cfg 与 resources.db（ro uri），
只写 .scratch/dyn/texaudit/。
"""
import collections
import json
import os
import sqlite3
import time

import numpy as np

BS = chr(92)
ROOT = "D:/TLGL"
CFG = os.path.join(ROOT, ".scratch/unpacked/data/ResourcePath.cfg")
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/cfg_tex_probe.txt")
MAPS = os.path.join(ROOT, ".scratch/dyn/texaudit/cfg_tex_paths.json")
L = []


def say(s=""):
    L.append(str(s))


def path_hash_scalar(path):
    h1 = 0x4E67C6A7
    h2 = 0
    M = 0xFFFFFFFF
    for b in path.encode("utf-8", "ignore"):
        c = b
        if 65 <= c <= 90:
            c += 32
        elif c == 92:
            c = 47
        v = (c + (h1 * 32 & M) + (h1 >> 2)) & M
        h1 ^= v
        h2 = (c + 65599 * h2) & M
    return h1 | (h2 << 32)


def parse_strtab(raw):
    """串表布局（与 pathmap.rs:try_strtab 同型）：
       @off: [id=85][size][flag][count]  然后 count×(u32 len,u32 hash)  然后 chars。
       先按公式偏移试，失败就从尾部往前按 4 字节对齐扫（同 Rust 的兜底）。"""
    import struct

    def round8(x):
        return (x + 7) // 8 * 8

    def attempt(off):
        if off < 32 or off + 16 > len(raw):
            return None
        id_, size, flag, count = struct.unpack_from("<IIII", raw, off)
        if id_ != 85 or count == 0 or count > (1 << 21):
            return None
        desc = off + 16
        chars = desc + 8 * count
        if chars > len(raw):
            return None
        lens = []
        total = 0
        for i in range(count):
            ln = struct.unpack_from("<I", raw, desc + 8 * i)[0]
            if ln > 4096:
                return None
            total += ln
            lens.append(ln)
        if chars + total > len(raw) + 7:
            return None
        out = []
        p = chars
        for ln in lens:
            out.append(raw[p:p + ln].decode("utf-8", "replace"))
            p += ln
        return count, out, flag

    a = struct.unpack_from("<6I", raw, 0)
    tried = [round8(a[5]) + 24]
    tried += list(range(len(raw) - 16, max(32, len(raw) - 4_000_000), -4))
    for off in tried:
        r = attempt(off)
        if r:
            return r
    return 0, [], 0


def main():
    db = os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    raw = open(CFG, "rb").read()
    say("cfg 文件 %s 字节=%d" % (CFG, len(raw)))
    say("头 16 字节 magic=%r" % raw[:4])
    t0 = time.time()
    count, strs, flag = parse_strtab(raw)
    say("串表条数=%d（应为 2×72,764=145,528）flag=%d 用时 %.1fs" % (count, flag, time.time() - t0))
    if count != 145528:
        say("!! 条数对不上，解析口径要复核，后面结论只当参考")

    pairs = [(strs[i], strs[i + 1]) for i in range(0, len(strs) - 1, 2)]
    say("映射对=%d  首 3 对=%s" % (len(pairs), pairs[:3]))
    # 校验：每条 path 的 basename 是否等于 bare name
    good = sum(1 for b, p in pairs if p.replace(BS, "/").split("/")[-1].lower() == b.lower())
    say("对内自洽（path 末段==裸名，忽略大小写）: %d / %d (%.1f%%)" % (
        good, len(pairs), 100.0 * good / max(1, len(pairs))))
    n2p = {}
    for b, p in pairs:
        n2p.setdefault(b.lower(), p)
    say("去重后的裸名: %d" % len(n2p))

    # ---- 1. 悬空贴图名有多少在 cfg 里登过、登记路径长什么样 ----
    dang = [r[0] for r in con.execute(
        "select distinct name from refs where to_hash is null and kind in ('.tga','.dds','.png')")]
    have = [n for n in dang if n.lower() in n2p]
    say()
    say("=== 悬空贴图名 × cfg ===")
    say("悬空贴图名 %d 个，其中 cfg 登记过路径的: %d (%.1f%%)" % (len(dang), len(have), 100.0 * len(have) / max(1, len(dang))))
    dcnt = collections.Counter(n2p[n.lower()].replace(BS, "/").rsplit("/", 1)[0].lower() for n in have)
    say("登记目录种类: %d；前 10: %s" % (len(dcnt), dcnt.most_common(10)))
    say("登记目录里含 /texture/ 段的: %d 个名" % sum(v for d, v in dcnt.items() if "/texture" in d or d.endswith("texture")))

    # ---- 2. 这一枪：登记路径代哈希，落进匿名池几张？ ----
    anon = {int(r[0], 16): r[1] for r in con.execute("select hash,type from resources where path is null")}
    pool = set(r[0] for r in con.execute(
        "select hash from resources where type='texture' and path is null and width>=512 and height>=512 and codec in ('RGBA32','BC3') and mips>=4"))
    pool_i = set(int(h, 16) for h in pool)
    say()
    say("=== 决定性一枪：path_hash(cfg 登记全路径) 落在包里吗 ===")
    hit_any = hit_tex = hit_pool = 0
    ex = []
    for n in have:
        h = path_hash_scalar(n2p[n.lower()])
        if h in anon:
            hit_any += 1
            if anon[h] == "texture":
                hit_tex += 1
                if h in pool_i:
                    hit_pool += 1
                if len(ex) < 8:
                    ex.append((n, n2p[n.lower()], "%016x" % h))
    say("登记路径共 %d 条 → 哈希命中任意匿名行 %d 条，其中匿名**贴图** %d 条，落进候选池 %d 条" % (
        len(have), hit_any, hit_tex, hit_pool))
    for e in ex:
        say("  例 %s -> %s -> %s" % e)
    # 已解析的对照：有路径的行本身
    chk = con.execute("select hash,path from resources where type='texture' and path is not null limit 200").fetchall()
    okc = sum(1 for h, p in chk if path_hash_scalar(p) == int(h, 16))
    say("对照（有路径的贴图行 200 条自校验）: %d/200 哈希相符" % okc)

    # ---- 3. 穷举：cfg 目录宇宙（含祖先）× 悬空贴图名 ----
    dirs = set()
    for b, p in pairs:
        parts = p.replace(BS, "/").split("/")[:-1]
        for i in range(len(parts) + 1):
            dirs.add("/".join(parts[:i]).lower())
    dirs.discard("")
    dl = sorted(dirs)
    say()
    say("=== 穷举 B：cfg 目录宇宙 × 悬空贴图名 ===")
    say("cfg 目录宇宙（含祖先，不含根）: %d；旧的 resources.path 宇宙: 3,757" % len(dl))
    target = np.array(sorted(anon), dtype=np.uint64)

    def norm(s):
        b = bytearray()
        for ch in s.encode("utf-8", "ignore"):
            if 65 <= ch <= 90:
                ch += 32
            elif ch == 92:
                ch = 47
            b.append(ch)
        return bytes(b)

    def state(bs):
        h1 = np.uint32(0x4E67C6A7)
        h2 = np.uint32(0)
        for b in bs:
            v = (np.uint32(int(b)) + h1 * np.uint32(32) + (h1 >> np.uint32(2))).astype(np.uint32)
            h1 = (h1 ^ v).astype(np.uint32)
            h2 = (np.uint32(int(b)) + np.uint32(65599) * h2).astype(np.uint32)
        return int(h1), int(h2)

    dirs_ext = [""] + dl
    pre = [state(norm(d + "/") if d else b"") for d in dirs_ext]
    pre_lo = np.array([x[0] for x in pre], dtype=np.uint32)
    pre_hi = np.array([x[1] for x in pre], dtype=np.uint32)
    names = sorted(set(dang))
    nb = [norm(x) for x in names]
    bylen = collections.defaultdict(list)
    for i, x in enumerate(nb):
        bylen[len(x)].append(i)
    hits = []
    t1 = time.time()
    for L_ in sorted(bylen):
        idxs = bylen[L_]
        mat = np.zeros((len(idxs), L_), dtype=np.uint8)
        for j, i in enumerate(idxs):
            mat[j] = np.frombuffer(nb[i], dtype=np.uint8)
        for s in range(0, len(dirs_ext), 1200):
            H1 = np.repeat(pre_lo[s:s + 1200][:, None], len(idxs), axis=1)
            H2 = np.repeat(pre_hi[s:s + 1200][:, None], len(idxs), axis=1)
            for k in range(L_):
                col = mat[:, k][None, :].astype(np.uint32)
                H1 = H1 ^ (col + H1 * np.uint32(32) + (H1 >> np.uint32(2)))
                H2 = col + np.uint32(65599) * H2
            vals = H1.astype(np.uint64) | (H2.astype(np.uint64) << np.uint64(32))
            pos = np.isin(vals, target)
            if pos.any():
                rr, cc = np.nonzero(pos)
                for a, b in zip(rr, cc):
                    hits.append((names[idxs[b]], dirs_ext[s + int(a)], "%016x" % int(vals[a, b]),
                                 anon[int(vals[a, b])]))
    say("比对 %.0fM 次（目录含根 %d × 名 %d），耗时 %.1fs，命中 %d" % (
        len(dirs_ext) * len(names) / 1e6, len(dirs_ext), len(names), time.time() - t1, len(hits)))
    for h in hits[:12]:
        say("  命中 %s @ %s -> %s type=%s" % h)
    say("命中里 type=texture 的: %d" % sum(1 for h in hits if h[3] == "texture"))

    # ---- 4. 给标注用的精确键 ----
    keys = {}
    for n in dang:
        p = n2p.get(n.lower())
        keys[n] = ("cfg:%s" % p) if p else ("bare:%s" % n)
    with open(MAPS, "w", encoding="utf-8") as fh:
        json.dump({"dangling_tex_keys": keys,
                   "cfg_registered_path_for_dangling": {n: n2p[n.lower()] for n in have}},
                  fh, ensure_ascii=False, indent=1)
    say()
    say("覆盖表键清单（cfg:/bare:）→ %s" % MAPS)

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
