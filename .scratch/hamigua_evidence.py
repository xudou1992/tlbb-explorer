# -*- coding: utf-8 -*-
"""hamigua 取证 · 第 4 步：四道证据 + 剩余族谱（2026-10-05）

A. 无回归：旧口径（origin 起点且挂点段收口 EOF）走通的每份文件，新口径必须仍走通。
B. .ani 对账：root-flag 走通样本旁若有同干名 .ani，轨道数(0xba u16) == 0x110 声明数。
C. 解剖学：对声明骨数 >= 14 的 root-flag 样本解链，抽验
   spine→spine1→neck→head / thigh→calf→foot→toe0 / clavicle→upperarm→forearm。
D. 剩余失败族聚类（no-candidate / stuck / tx-not-eof / 多根）按前缀。
输出 .scratch/hamigua_evidence.txt
"""
import os
import re
import struct
import collections
import sys

sys.path.insert(0, r"D:\TLGL\.scratch")
import hamigua_walk as W

ROOT = W.ROOT
OUT = r"D:\TLGL\.scratch\hamigua_evidence.txt"


def old_ok(path):
    """旧口径：只试 origin 起点（= 现 Rust parse_hierarchy 的行为，
    含挂点数>0 的隐含约束——Rust tail_try_sockets 拒绝 count=0）。"""
    b = open(path, "rb").read()
    if len(b) < 0x114:
        return False
    d = W.u32(b, 0x110)
    if not (0 < d <= 4096):
        return False
    vc = W.u32(b, 0x8C)
    starts = []
    i = 0
    while i + 96 <= len(b):
        r = W.looks_record96(b, i)
        if r is not None:
            if r[0] == "origin":
                starts.append(i)
            i += 96
        else:
            i += 4
    for s in starts:
        nodes, tx, pos, err = W.walk_tail(b, s, vc)
        if err:
            continue
        if len(nodes) != d:
            continue
        if W.tree_check(nodes, d) is None:
            return True
    return False


def ani_track(path):
    """同干名 .ani 的轨道数（0xba u16，与 anim.rs 口径一致）。"""
    stem = path[:-5]
    for suf in (".ani",):
        c = stem + suf
        if os.path.exists(c):
            raw = open(c, "rb").read()
            if len(raw) >= 0xbc:
                return struct.unpack_from("<H", raw, 0xba)[0], os.path.basename(c)
    d = os.path.dirname(stem)
    a = os.path.join(d, "ani")
    if os.path.isdir(a):
        base = os.path.basename(stem)
        for n in os.listdir(a):
            if n.startswith(base + "_") and n.endswith(".ani"):
                raw = open(os.path.join(a, n), "rb").read()
                if len(raw) >= 0xbc:
                    return struct.unpack_from("<H", raw, 0xba)[0], n
    return None, None


def chain_summary(nodes, root):
    parent = {}
    for nd in nodes:
        for ch in nd["children"]:
            parent[ch] = nd["name"]
    chains = []
    KEY = ("spine", "thigh", "calf", "foot", "toe0", "clavicle", "upperarm",
           "forearm", "hand", "neck", "head", "finger")
    byname = {nd["name"]: nd for nd in nodes}
    for nd in nodes:
        nm = nd["name"].lower()
        if any(k in nm for k in KEY) and nm in parent:
            p = parent[nm]
            chains.append("%s<-%s" % (nd["name"], p))
    return chains


def main():
    files = []
    for dirpath, _, names in os.walk(ROOT):
        for n in names:
            if n.lower().endswith(".mesh"):
                p = os.path.join(dirpath, n)
                b = open(p, "rb").read()
                if len(b) >= 0x114 and 0 < W.u32(b, 0x110) <= 4096:
                    files.append(p)
    files.sort()
    L = []
    w = L.append

    # ---- A. 无回归 + 全量重跑
    new_ok = {}
    old_oks = 0
    regress = []
    for p in files:
        b = open(p, "rb").read()
        d = W.u32(b, 0x110)
        vc = W.u32(b, 0x8C)
        starts, roots = W.candidates(b)
        best = None
        for start in starts + roots:
            nodes, tx, pos, err = W.walk_tail(b, start, vc)
            if err:
                continue
            bad = W.tree_check(nodes, d)
            if bad:
                continue
            best = (start, "origin" if start in starts else "root-flag", tx, nodes)
            break
        if best:
            new_ok[p] = best
        if old_ok(p):
            old_oks += 1
            if p not in new_ok:
                regress.append(p)
    w("A. 无回归：declared>0 共 %d；旧口径走通 %d；新口径走通 %d；回退 %d" %
      (len(files), old_oks, len(new_ok), len(regress)))
    for p in regress[:10]:
        w("   回退！%s" % p)

    # ---- B. root-flag 族名单 + .ani 对账
    rf = [(p, v) for p, v in new_ok.items() if v[1] == "root-flag"]
    origin_only = [(p, v) for p, v in new_ok.items() if v[1] == "origin"]
    w("")
    w("B. root-flag（无 origin/top 前奏，根条目 flag=-1 直接开始）族：%d 份" % len(rf))
    w("   其中旧口径已走通（不可能，仅防错）：%d" % sum(1 for p, _ in rf if old_ok(p)))
    ani_ok = ani_bad = ani_na = 0
    bad_cases = []
    for p, v in sorted(rf):
        d = W.u32(open(p, "rb").read(), 0x110)
        t, name = ani_track(p)
        if t is None:
            ani_na += 1
        elif t == d:
            ani_ok += 1
        else:
            ani_bad += 1
            bad_cases.append((p, d, t, name))
    w("   .ani 轨道数对账：相等 %d / 不等 %d / 无同干名 .ani %d" % (ani_ok, ani_bad, ani_na))
    for p, d, t, name in bad_cases[:12]:
        w("     不等：%s declared=%d ani=%s(%d)" % (os.path.basename(p), d, name, t))

    # ---- C. 解剖学抽验
    w("")
    w("C. 解剖学抽验（root-flag 且 declared>=14 的样本，全部解链检查 Biped 关系）：")
    PAT = [
        ("spine1<-spine", lambda par: par.get("bip01_spine1") == "bip01_spine"),
        ("neck<-spine1", lambda par: par.get("bip01_neck") == "bip01_spine1"),
        ("head<-neck", lambda par: par.get("bip01_head") == "bip01_neck"),
        ("l_thigh<-spine", lambda par: par.get("bip01_l_thigh") == "bip01_spine"),
        ("l_calf<-l_thigh", lambda par: par.get("bip01_l_calf") == "bip01_l_thigh"),
        ("l_foot<-l_calf", lambda par: par.get("bip01_l_foot") == "bip01_l_calf"),
        ("l_toe0<-l_foot", lambda par: par.get("bip01_l_toe0") == "bip01_l_foot"),
        ("r_calf<-r_thigh", lambda par: par.get("bip01_r_calf") == "bip01_r_thigh"),
        ("r_foot<-r_calf", lambda par: par.get("bip01_r_foot") == "bip01_r_calf"),
        ("l_forearm<-l_upperarm", lambda par: par.get("bip01_l_forearm") == "bip01_l_upperarm"),
        ("l_hand<-l_forearm", lambda par: par.get("bip01_l_hand") == "bip01_l_forearm"),
    ]
    big = [(p, v) for p, v in sorted(rf) if W.u32(open(p, "rb").read(), 0x110) >= 14]
    w("   候选 %d 份（root-flag 且 declared>=14）" % len(big))
    stat = collections.Counter()
    samples = []
    for p, v in big:
        nodes = v[3]
        par = {}
        for nd in nodes:
            for ch in nd["children"]:
                par[ch] = nd["name"]
        has_bip = any("bip01" in nd["name"].lower() for nd in nodes)
        hit = [name for name, fn in PAT if fn(par)]
        stat["bip01" if has_bip else "non-bip01"] += 1
        if has_bip:
            stat["hits%d" % len(hit)] += 1
            if len(hit) >= 8:
                samples.append((p, v, hit, par))
    w("   其中含 bip01 名的 %d 份；命中解剖关系数分布：%s" %
      (stat["bip01"], sorted((k, v) for k, v in stat.items() if k.startswith("hits"))))
    w("   命中 >=8 条关系的样本 %d 份；列前 6 份的关系现场：" % len(samples))
    for p, v, hit, par in samples[:6]:
        w("     %s (declared=%d, start=0x%x, tx=(%d,%d))" %
          (os.path.basename(p), W.u32(open(p, "rb").read(), 0x110), v[0], v[2][0], v[2][1]))
        w("       %s" % ", ".join(hit))
    # 非 bip01 的 root-flag 样本，链长什么样（抽 3 份 declared>=14）
    w("   非 bip01 命名的 root-flag 大样本（链首 8 对）：")
    shown = 0
    for p, v in big:
        nodes = v[3]
        if any("bip01" in nd["name"].lower() for nd in nodes):
            continue
        par = {}
        for nd in nodes:
            for ch in nd["children"]:
                par[ch] = nd["name"]
        w("     %s (declared=%d): %s" % (os.path.basename(p),
                                          W.u32(open(p, "rb").read(), 0x110),
                                          ", ".join("%s<-%s" % (c, pa) for c, pa in list(par.items())[:8])))
        shown += 1
        if shown >= 3:
            break

    # ---- D. 剩余失败族
    w("")
    w("D. 剩余失败 %d 份的族谱：" % (len(files) - len(new_ok)))
    fams = collections.defaultdict(collections.Counter)
    for p in files:
        if p in new_ok:
            continue
        b = open(p, "rb").read()
        d = W.u32(b, 0x110)
        vc = W.u32(b, 0x8C)
        starts, roots = W.candidates(b)
        err = None
        for start in starts + roots:
            nodes, tx, pos, e = W.walk_tail(b, start, vc)
            if e:
                err = e.split(" ")[0] if e.startswith("stuck") else e
                err = "%s@tail%%" % err.split("@")[0] if e.startswith("tx-not-eof") else e
                break
            bad = W.tree_check(nodes, d)
            if bad:
                err = bad.split(":")[0].split("=")[0]
                break
        if err is None:
            err = "unknown"
        base = os.path.basename(p).rsplit(".", 1)[0].lower()
        pref = "_".join(base.split("_")[:2])
        fams[err][pref] += 1
    for e, c in sorted(fams.items(), key=lambda kv: -sum(kv[1].values())):
        w("  %-18s %5d  top前缀：%s" % (e, sum(c.values()), c.most_common(6)))

    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("written", OUT)


if __name__ == "__main__":
    main()
