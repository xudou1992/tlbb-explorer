# -*- coding: utf-8 -*-
"""path_hash 全交叉反查（只读）：未解析贴图名 × 包里所有已知目录（含祖先）。

为什么值得再跑一次：`.scratch/tex_归属证据缺失_20261010.md` 桥 5 只拼了 1,500 种写法
（裸名 / resource/ / data/ / source/ / 引用者同目录），**没做过全目录叉乘**。
库里有路径的行给出几千个真实目录；贴图与它的 .mdl/.mtl/.mesh 通常同叶子目录，
而那些兄弟文件都有路径 —— 所以「匿名 hash = path_hash(某个已知目录/某个悬空名)」
是可判证的假设。

算法：path_hash 是逐字两泳道循环（jpak/crypto.rs:78）。先把每个目录串的**前缀末态**
算出来（3 千次标量推进），再对「同一长度的名字组」做向量化推进，最后一列查匿名哈希表。
零填充会污染哈希，所以必须按名字长度分组。

纪律：resources.db 以 mode=ro 打开；只写本目录；不写覆盖表。
"""
import json
import os
import sqlite3
import time
from collections import defaultdict

import numpy as np

BS = chr(92)
ROOT = "D:/TLGL"
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/pathhash_sweep.txt")
HITS = os.path.join(ROOT, ".scratch/dyn/texaudit/pathhash_hits.json")
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


def norm(s):
    b = bytearray()
    for ch in s.encode("utf-8", "ignore"):
        if 65 <= ch <= 90:
            ch += 32
        elif ch == 92:
            ch = 47
        b.append(ch)
    return bytes(b)


def prefix_state(dbytes):
    """一个目录前缀（含结尾 '/'，根目录为空 bytes）推进后的 (h1,h2)。"""
    h1 = np.uint32(0x4E67C6A7)
    h2 = np.uint32(0)
    for b in dbytes:
        v = (np.uint32(int(b)) + h1 * np.uint32(32) + (h1 >> np.uint32(2))).astype(np.uint32)
        h1 = (h1 ^ v).astype(np.uint32)
        h2 = (np.uint32(int(b)) + np.uint32(65599) * h2).astype(np.uint32)
    return h1, h2


def main():
    db = os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/")
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    try:
        con.execute("update resources set width=width")
        say("!! 只读闸门失效 —— 立即中止")
        return
    except Exception as e:
        say("只读闸门：%s" % e)

    say("=== 0. 复刻自校验：path_hash(路径)==hash ===")
    rows = con.execute("select hash,path from resources where path is not null").fetchall()
    ok = sum(1 for h, p in rows if path_hash_scalar(p) == int(h, 16))
    say("命中 %d / %d (%.3f%%)" % (ok, len(rows), 100.0 * ok / len(rows)))
    if ok != len(rows):
        say("!! 复刻不准，穷举作废")
        return

    say()
    say("=== 1. 目标集（匿名行）===")
    anon = con.execute("select hash,type,codec,width,height,mips,path is null from resources where path is null").fetchall()
    anon_info = {int(a[0], 16): a for a in anon}
    target = np.array(sorted(anon_info), dtype=np.uint64)
    pool = set(int(r[0], 16) for r in con.execute(
        "select hash from resources where type='texture' and path is null and width>=512 and height>=512 and codec in ('RGBA32','BC3') and mips>=4"))
    say("匿名行 %d，其中候选池 %d" % (len(anon_info), len(pool)))

    say()
    say("=== 2. 目录宇宙 ===")
    dirs = set()
    for (p,) in con.execute("select path from resources where path is not null"):
        parts = (p or "").replace(BS, "/").split("/")[:-1]
        for i in range(len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    dirs.add("")
    dirs.discard("")  # 裸名单独作为一组试（省一次前缀）
    dl = sorted(dirs)
    say("含祖先与根的目录数: %d" % (len(dl) + 1))

    say()
    say("=== 3. 名字宇宙 ===")
    raw = [r[0] for r in con.execute(
        "select distinct name from refs where to_hash is null and kind in ('.tga','.dds','.png')")]
    say("未解析贴图名（原样，去重）: %d" % len(raw))

    def try_set(names, tag):
        nb = [norm(n) for n in names]
        bylen = defaultdict(list)
        for i, b in enumerate(nb):
            bylen[len(b)].append(i)
        dirs_ext = [""] + dl            # 0 号 = 根（裸名）
        pre = [prefix_state(norm(d + "/") if d else b"") for d in dirs_ext]
        pre_lo = np.array([int(h1) for h1, h2 in pre], dtype=np.uint32)
        pre_hi = np.array([int(h2) for h1, h2 in pre], dtype=np.uint32)
        hits = []
        t0 = time.time()
        for L_ in sorted(bylen):
            idxs = bylen[L_]
            mat = np.zeros((len(idxs), L_), dtype=np.uint8)
            for j, i in enumerate(idxs):
                mat[j] = np.frombuffer(nb[i], dtype=np.uint8)
            for s in range(0, len(dirs_ext), 1500):        # 目录分块，控内存峰值
                lo = pre_lo[s:s + 1500]
                hi = pre_hi[s:s + 1500]
                H1 = np.repeat(lo[:, None], len(idxs), axis=1)
                H2 = np.repeat(hi[:, None], len(idxs), axis=1)
                for k in range(L_):
                    col = mat[:, k][None, :].astype(np.uint32)
                    v = col + H1 * np.uint32(32) + (H1 >> np.uint32(2))
                    H1 = H1 ^ v
                    H2 = col + np.uint32(65599) * H2
                vals = H1.astype(np.uint64) | (H2.astype(np.uint64) << np.uint64(32))
                pos = np.isin(vals, target)
                if pos.any():
                    rr, cc = np.nonzero(pos)
                    for a, b in zip(rr, cc):
                        hv = int(vals[a, b])
                        info = anon_info[hv]
                        hits.append((names[idxs[b]], dirs_ext[s + int(a)], hv, info[1],
                                     info[2], info[3], info[4], hv in pool))
        say("[%s] 比对 %.1fM 次（目录含根 %d × 名 %d），耗时 %.1fs，命中 %d" % (
            tag, len(dirs_ext) * len(names) / 1e6, len(dirs_ext), len(names),
            time.time() - t0, len(hits)))
        return hits

    all_hits = try_set(raw, "原样名")
    # 变体集（只给规模可控的：换扩展名 / 去扩展名），用同名集的 4 倍上限
    var = set()
    for n in raw:
        s = n.replace(BS, "/")
        stem, dot, ext = s.rpartition(".")
        if dot and "/" not in ext:
            var |= {stem + ".tga", stem + ".dds", stem + ".png", stem}
    var = sorted(x for x in var if x not in set(raw))
    say("扩展名变体（新增）: %d" % len(var))
    if len(var) <= 60000:
        all_hits += try_set(var, "变体名")

    say()
    say("=== 4. 结论 ===")
    say("总命中: %d" % len(all_hits))
    if all_hits:
        for h in all_hits[:40]:
            say("  命中 名=%s 目录=%r -> hash=%016x type=%s codec=%s %sx%s mips=%s 在池内=%s" % h)
        with open(HITS, "w", encoding="utf-8") as fh:
            json.dump([{"name": a, "dir": b, "hash": "%016x" % c, "type": d, "codec": e,
                        "w": f, "h": g, "mips": hh, "in_pool": i} for a, b, c, d, e, f, g, hh, i in all_hits],
                      fh, ensure_ascii=False, indent=1)
        say("命中清单 -> %s" % HITS)
    else:
        say("0 命中：匿名 hash 不是「任何已知目录（含祖先/根）/ 任何未解析贴图名（含扩展名变体）」的 path_hash。")

    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
