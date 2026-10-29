# -*- coding: utf-8 -*-
"""hamigua 取证 · 第 3 步：广义 walker（2026-10-05）

假设 H1：hamigua 族与已走通的 47 份共用同一套条目语法，差别只有两条——
  (a) 尾部没有 origin/top 前奏记录，根条目（flag=-1）直接开始；
  (b) 挂点段挂点数可以为 0（老样本恒 >=1）。
其余判据一条不松：条目数=0x110 声明数、单根、无环、除根外恰列一次、
名字×2 一致、前导记录名=条目名、EOF 分毫不差、标志位分布={-1:1, 1:其余}。

对全部 parse_hierarchy 失败且 declared>0 的文件跑这套 walker，输出：
  走通/走不通 + 走不通时卡在哪（偏移、当时的 u32/f32）。
结果写 .scratch/hamigua_walk.txt
"""
import os
import re
import struct
import collections

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")
ROOT = r"D:\TLGL\.scratch\out\tree"
OUT = r"D:\TLGL\.scratch\hamigua_walk.txt"


def name_at(b, off):
    if off < 1 or off + 32 > len(b):
        return None
    if re.match(rb"[0-9A-Za-z_\-.]", b[off - 1:off]):
        return None
    m = NAME_OK.match(b, off)
    if not m:
        return None
    s = m.group()
    if len(s) > 31 or b[off + len(s)] != 0:
        return None
    if any(x != 0 for x in b[off + len(s):off + 32]):
        return None
    return s.decode()


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def f32(b, o):
    return struct.unpack_from("<f", b, o)[0]


def ortho3(rows):
    lens = [sum(v * v for v in r) ** 0.5 for r in rows]
    if min(lens) < 1e-4 or max(lens) / min(lens) > 1.05:
        return False
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) > 1e-2:
                return False
    return True


def looks_mat64(b, pos):
    if pos + 64 > len(b):
        return False
    m = struct.unpack_from("<16f", b, pos)
    if not all(abs(v) < 1e7 for v in m):
        return False
    if abs(m[15] - 1.0) > 1e-3 or abs(m[3]) > 1e-3 or abs(m[7]) > 1e-3 or abs(m[11]) > 1e-3:
        return False
    return ortho3([m[0:3], m[4:7], m[8:11]])


def looks_u92(b, pos):
    if pos + 88 > len(b):
        return False
    d = f32(b, pos)
    if not (0.9 <= d <= 1.1):
        return False
    if abs(f32(b, pos + 20) - d) > 1e-6 or abs(f32(b, pos + 40) - d) > 1e-6:
        return False
    if abs(f32(b, pos + 60) - 1.0) > 1e-3:
        return False
    for o in (76, 80, 84):
        if abs(f32(b, pos + o) - 100.0) > 1e-2:
            return False
    return True


def looks_inf(b, pos, vc):
    if pos + 4 > len(b):
        return False
    n = u32(b, pos)
    if n == 0:
        return True
    if n > 200000 or pos + 4 + 8 * n > len(b):
        return False
    last = 0
    for k in range(n):
        v = u32(b, pos + 4 + 4 * k)
        if k > 0 and v <= last:
            return False
        if v >= vc:
            return False
        last = v
    for k in range(n):
        w = f32(b, pos + 4 + 4 * n + 4 * k)
        if not (-1e-3 <= w <= 1.001):
            return False
    return True


def looks_record96(b, pos):
    if pos + 96 > len(b):
        return None
    nm = name_at(b, pos)
    if nm is None:
        return None
    m = struct.unpack_from("<16f", b, pos + 32)
    if not all(abs(v) < 1e7 for v in m):
        return None
    if abs(m[15] - 1.0) > 1e-3:
        return None
    if not ortho3([m[0:3], m[4:7], m[8:11]]):
        return None
    return nm, m


def try_entry(b, pos, vc):
    p = pos
    rec = looks_record96(b, p)
    if rec is not None:
        p += 96
    ninf = n92 = n64 = 0
    while True:
        if looks_u92(b, p):
            p += 88
            n92 += 1
            continue
        if looks_mat64(b, p):
            p += 64
            n64 += 1
            continue
        if looks_inf(b, p, vc):
            p += 4 + 8 * u32(b, p)
            ninf += 1
            continue
        break
    if p + 4 > len(b):
        return None
    x = u32(b, p)
    p += 4
    nm1 = name_at(b, p)
    nm2 = name_at(b, p + 32) if p + 32 < len(b) else None
    if nm1 is None or nm1 != nm2:
        return None
    if rec is not None and rec[0] != nm1:
        return None
    p += 64
    c = u32(b, p)
    if c > 4096:
        return None
    p += 4
    children = []
    for _ in range(c):
        r = looks_record96(b, p)
        if r is not None:
            children.append(r[0])
            p += 96
        else:
            cn = name_at(b, p)
            if cn is None:
                return None
            children.append(cn)
            p += 32
    return {"name": nm1, "x": x, "children": children,
            "blocks": (ninf, n92, n64)}, p


def try_tx(b, pos, vc):
    """挂点段：允许挂点数 = 0（hamigua 变体假设 H1b）。"""
    p = pos
    while True:
        if looks_u92(b, p):
            p += 88
            continue
        if looks_mat64(b, p):
            p += 64
            continue
        if looks_inf(b, p, vc):
            p += 4 + 8 * u32(b, p)
            continue
        break
    if p + 8 > len(b):
        return None
    xt = u32(b, p)
    cnt = u32(b, p + 4)
    p += 8
    if cnt > 4096 or p + 128 * cnt > len(b):
        return None
    for _ in range(cnt):
        if name_at(b, p) is None or name_at(b, p + 32) is None:
            return None
        m = struct.unpack_from("<16f", b, p + 64)
        if abs(m[15] - 1.0) > 1e-3:
            return None
        p += 128
    return xt, cnt, p


def walk_tail(b, start, vc):
    pos = start
    nodes = []
    while pos < len(b):
        got = try_entry(b, pos, vc)
        if got is not None:
            nd, pos = got
            nodes.append(nd)
            continue
        if looks_record96(b, pos) is not None:
            pos += 96
            continue
        tx = try_tx(b, pos, vc)
        if tx is not None:
            if tx[2] != len(b):
                return nodes, tx, tx[2], "tx-not-eof@0x%x-of-0x%x" % (tx[2], len(b))
            return nodes, tx, tx[2], None
        return nodes, None, pos, "stuck@0x%x u32=%d(0x%x)" % (pos, u32(b, pos), u32(b, pos))
    return nodes, None, pos, "not-eof"


def candidates(b):
    """起点候选：origin 命名的 96B 记录（老语法），以及
    [u32 -1][名字×2 相同]（hamigua 变体的根条目，无前奏）。"""
    starts = []
    i = 0
    while i + 96 <= len(b):
        r = looks_record96(b, i)
        if r is not None:
            if r[0] == "origin":
                starts.append(i)
            i += 96
        else:
            i += 4
    roots = []
    at = 0
    needle = b"\xff\xff\xff\xff"
    while True:
        at = b.find(needle, at)
        if at < 0 or at + 68 > len(b):
            break
        if at % 4 == 0:
            n1 = name_at(b, at + 4)
            n2 = name_at(b, at + 36)
            if n1 is not None and n1 == n2:
                roots.append(at)
        at += 1
    return starts, roots


def tree_check(nodes, declared):
    if len(nodes) != declared:
        return "count %d != declared %d" % (len(nodes), declared)
    parent = {}
    for nd in nodes:
        for ch in nd["children"]:
            if ch in parent:
                return "child-listed-twice: %s" % ch
            parent[ch] = nd["name"]
    names = set(nd["name"] for nd in nodes)
    if len(names) != len(nodes):
        return "dup-entry-name"
    roots = [nd["name"] for nd in nodes if nd["name"] not in parent]
    if len(roots) != 1:
        return "roots=%s" % roots[:4]
    if any(c not in names for c in parent):
        return "child-not-entry"
    for nm in names:
        cur, seen = nm, set()
        while cur in parent:
            if cur in seen:
                return "cycle"
            seen.add(cur)
            cur = parent[cur]
    xs = collections.Counter(nd["x"] for nd in nodes)
    if set(xs) - {0xFFFFFFFF, 1}:
        return "flag-values=%s" % dict(xs)
    if xs.get(0xFFFFFFFF, 0) != 1:
        return "flag-1-count=%d" % xs.get(0xFFFFFFFF, 0)
    # DFS 检查：孩子名单展开顺序 == 条目顺序
    order = []
    seen = set()

    def dfs(nm):
        if nm in seen:
            return
        seen.add(nm)
        order.append(nm)
        for nd in nodes:
            if nd["name"] == nm:
                for ch in nd["children"]:
                    dfs(ch)
    dfs(roots[0])
    if order != [nd["name"] for nd in nodes]:
        return "not-dfs"
    return None


def analyze(path):
    b = open(path, "rb").read()
    if len(b) < 0x114:
        return {"file": path, "err": "too-short"}
    declared = u32(b, 0x110)
    vc = u32(b, 0x8C)
    if declared == 0 or declared > 4096:
        return {"file": path, "err": "bad-declared", "declared": declared}
    starts, roots = candidates(b)
    attempts = []
    for start in starts + roots:
        nodes, tx, pos, err = walk_tail(b, start, vc)
        if err:
            attempts.append(("walk-fail@0x%x" % start, err, len(nodes)))
            continue
        bad = tree_check(nodes, declared)
        if bad:
            attempts.append(("tree-fail@0x%x" % start, bad, len(nodes)))
            continue
        return {"file": path, "ok": True, "declared": declared, "vc": vc,
                "start": start, "kind": "origin" if start in starts else "root-flag",
                "nodes": len(nodes), "tx_flag": tx[0], "tx_count": tx[1],
                "flags": dict(collections.Counter(nd["x"] for nd in nodes)),
                "blocks": (sum(nd["blocks"][0] for nd in nodes),
                           sum(nd["blocks"][1] for nd in nodes),
                           sum(nd["blocks"][2] for nd in nodes)),
                "names": [nd["name"] for nd in nodes][:8],
                "size": len(b)}
    return {"file": path, "err": attempts[0][1] if attempts else "no-candidate",
            "declared": declared, "vc": vc, "attempts": attempts[:3], "size": len(b)}


def main():
    # 上次普查的失败清单（declared>0）
    import json
    fails = []
    for dirpath, _, names in os.walk(ROOT):
        for n in names:
            if n.lower().endswith(".mesh"):
                p = os.path.join(dirpath, n)
                try:
                    bb = open(p, "rb").read()
                except OSError:
                    continue
                if len(bb) < 0x114:
                    continue
                d = u32(bb, 0x110)
                if 0 < d <= 4096:
                    fails.append(p)
    fails.sort()
    lines = []
    ok = 0
    errs = collections.Counter()
    kinds = collections.Counter()
    txs = collections.Counter()
    oklist = []
    for p in fails:
        r = analyze(p)
        if r.get("ok"):
            ok += 1
            kinds[r["kind"]] += 1
            txs[(r["tx_flag"], r["tx_count"])] += 1
            oklist.append(r)
        else:
            errs[r.get("err", "?")[:80]] += 1
    lines.append("declared>0 的 .mesh 共 %d，广义 walker 走通 %d" % (len(fails), ok))
    lines.append("起点类别：%s" % dict(kinds))
    lines.append("挂点段 (flag,count) 直方 top10：%s" % txs.most_common(10))
    lines.append("")
    lines.append("仍走不通的按错误聚类：")
    for e, c in errs.most_common(25):
        lines.append("  %5d  %s" % (c, e))
    lines.append("")
    lines.append("走通样本（前 40，按 declared 排）：")
    for r in sorted(oklist, key=lambda r: r["declared"])[:40]:
        lines.append("  %-46s declared=%-4d vc=%-6d start=0x%x %s tx=(%d,%d) 块=%s 名=%s" % (
            os.path.basename(r["file"]), r["declared"], r["vc"], r["start"],
            r["kind"], r["tx_flag"], r["tx_count"], r["blocks"], r["names"][:6]))
    open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    with open(r"D:\TLGL\.scratch\hamigua_walk.json", "w", encoding="utf-8") as f:
        json.dump(oklist, f, ensure_ascii=False)
    print("written", OUT, "and json")


if __name__ == "__main__":
    main()
