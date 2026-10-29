# -*- coding: utf-8 -*-
"""tx-not-eof 取证 walker：拷自 hamigua_walk.py，looks_inf 改成 V2（互异+有界）。

只读 .mesh；不改 tlbb-explorer。挂点段口径与 V2 一致：
  [块 u92/mat64/inf]* [u32 标志][u32 挂点数][挂点数 × 128B]
挂点 128B = 名 char[32] + 骨名 char[32] + 矩阵 f32[16]（m15≈1）。
不要求挂点段收到 EOF——那正是本族的失败定义。
"""
import collections
import os
import re
import struct

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")
ROOT = r"D:\TLGL\.scratch\out\tree"


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


def i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


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
    """V2：N=0 合法；否则互异 + <顶点数 + 权重∈[0,1]。"""
    if pos + 4 > len(b):
        return False
    n = u32(b, pos)
    if n == 0:
        return True
    if n > vc or n > 200000 or pos + 4 + 8 * n > len(b):
        return False
    seen = set()
    for k in range(n):
        v = u32(b, pos + 4 + 4 * k)
        if v >= vc or v in seen:
            return False
        seen.add(v)
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


def skip_blocks(b, p, vc):
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
    return p


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
    """挂点段：允许 count=0。不要求 EOF。返回 (flag, count, end, sockets_start)."""
    p = skip_blocks(b, pos, vc)
    if p + 8 > len(b):
        return None
    xt = u32(b, p)
    cnt = u32(b, p + 4)
    p0 = p
    p += 8
    if cnt > 4096 or p + 128 * cnt > len(b):
        return None
    socks = []
    for _ in range(cnt):
        n1 = name_at(b, p)
        n2 = name_at(b, p + 32)
        if n1 is None or n2 is None:
            return None
        m = struct.unpack_from("<16f", b, p + 64)
        if abs(m[15] - 1.0) > 1e-3:
            return None
        if not all(abs(v) < 1e7 for v in m):
            return None
        socks.append((n1, n2))
        p += 128
    return xt, cnt, p, p0, socks


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
            xt, cnt, end, p0, socks = tx
            if end != len(b):
                return nodes, tx, end, "tx-not-eof@0x%x-of-0x%x" % (end, len(b))
            return nodes, tx, end, None
        return nodes, None, pos, "stuck@0x%x u32=%d(0x%x)" % (
            pos, u32(b, pos) if pos + 4 <= len(b) else 0,
            u32(b, pos) if pos + 4 <= len(b) else 0)
    return nodes, None, pos, "not-eof"


def candidates(b):
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
        return {"file": path, "err": "bad-declared", "declared": declared, "size": len(b)}
    starts, roots = candidates(b)
    attempts = []
    for start in starts + roots:
        nodes, tx, pos, err = walk_tail(b, start, vc)
        if err:
            attempts.append((start, err, len(nodes), tx, pos))
            continue
        bad = tree_check(nodes, declared)
        if bad:
            attempts.append((start, bad, len(nodes), tx, pos))
            continue
        return {
            "file": path, "ok": True, "declared": declared, "vc": vc,
            "start": start, "kind": "origin" if start in starts else "root-flag",
            "nodes": len(nodes), "tx_flag": tx[0], "tx_count": tx[1],
            "tx_end": tx[2], "tx_at": tx[3],
            "socks": tx[4], "size": len(b),
            "names": [nd["name"] for nd in nodes][:8],
        }
    # 优先保留 tx-not-eof 尝试（本任务目标族）
    txatt = [a for a in attempts if a[1].startswith("tx-not-eof")]
    pick = txatt[0] if txatt else (attempts[0] if attempts else None)
    if pick is None:
        return {"file": path, "err": "no-candidate", "declared": declared,
                "vc": vc, "size": len(b)}
    start, err, nnodes, tx, pos = pick
    rec = {
        "file": path, "err": err, "declared": declared, "vc": vc,
        "size": len(b), "start": start, "nnodes": nnodes, "pos": pos,
    }
    if tx is not None:
        rec["tx_flag"] = tx[0]
        rec["tx_count"] = tx[1]
        rec["tx_end"] = tx[2]
        rec["tx_at"] = tx[3]
        rec["socks"] = tx[4]
        rec["left"] = len(b) - tx[2]
    return rec


def iter_declared_mesh():
    for dirpath, _, names in os.walk(ROOT):
        for n in names:
            if n.lower().endswith(".mesh"):
                p = os.path.join(dirpath, n)
                try:
                    bb = open(p, "rb").read(0x114)
                except OSError:
                    continue
                if len(bb) < 0x114:
                    continue
                d = u32(bb, 0x110)
                if 0 < d <= 4096:
                    yield p
