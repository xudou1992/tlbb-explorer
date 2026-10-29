# -*- coding: utf-8 -*-
"""hamigua 变体取证 · 第 1 步：全库 .mesh 普查（2026-10-05）

对 D:/TLGL/.scratch/out/tree 下全部 .mesh 复现 crates/core/src/preview/
geometry.rs::parse_hierarchy 的接受条件（origin 记录起步、走到 EOF、
条目数=0x110 声明数、单根无环、孩子恰列一次），把失败按名字前缀聚类。

输出 .scratch/hamigua_census.txt：
  * 全库/有声明骨数/走通/失败 四个总数
  * 失败按「文件名前 2 个下划线 token」聚类的 top30 + 失败型分布
  * 失败文件的尾部特征统计（有无 origin、有无 tx_、声明数直方）
"""
import os
import re
import struct
import sys
import collections

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")
ROOT = r"D:\TLGL\.scratch\out\tree"
OUT = r"D:\TLGL\.scratch\hamigua_census.txt"


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


def u32(b, off):
    return struct.unpack_from("<I", b, off)[0]


def f32(b, off):
    return struct.unpack_from("<f", b, off)[0]


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
    return {"name": nm1, "x": x, "children": children}, p


def try_tx(b, pos, vc):
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
    cnt = u32(b, p + 4)
    p += 8
    if cnt == 0 or cnt > 4096 or p + 128 * cnt > len(b):
        return None
    for _ in range(cnt):
        if name_at(b, p) is None or name_at(b, p + 32) is None:
            return None
        m = struct.unpack_from("<16f", b, p + 64)
        if abs(m[15] - 1.0) > 1e-3:
            return None
        p += 128
    return p


def walk_tail(b, start, vc):
    """完全按 geometry.rs::tail_walk：条目 → 裸记录（前奏）→ 挂点段收口。"""
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
            pos = tx
            break
        return nodes, pos, "stuck@0x%x" % pos
    if pos != len(b):
        return nodes, pos, "not-eof@0x%x" % pos
    return nodes, pos, None


def analyze(path):
    b = open(path, "rb").read()
    if len(b) < 0x114:
        return {"err": "too-short"}
    declared = u32(b, 0x110)
    vc = u32(b, 0x8C)
    if declared == 0 or declared > 4096:
        return {"err": "bad-declared", "declared": declared}
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
    if not starts:
        return {"err": "no-origin", "declared": declared, "vc": vc, "size": len(b)}
    for start in starts:
        nodes, pos, err = walk_tail(b, start, vc)
        if err:
            continue
        if len(nodes) != declared:
            return {"err": "count!=declared", "walked": len(nodes), "declared": declared,
                    "size": len(b), "vc": vc}
        parent = {}
        dup = []
        for nd in nodes:
            for ch in nd["children"]:
                if ch in parent:
                    dup.append(ch)
                parent[ch] = nd["name"]
        roots = [nd["name"] for nd in nodes if nd["name"] not in parent]
        if len(roots) != 1:
            return {"err": "multi-root", "roots": roots[:6], "declared": declared}
        seen_names = set(nd["name"] for nd in nodes)
        if len(seen_names) != len(nodes):
            return {"err": "dup-entry-name", "declared": declared}
        missing = [c for c in parent if c not in seen_names]
        if missing:
            return {"err": "child-not-entry", "missing": missing[:6], "declared": declared}
        # 无环
        for nm in seen_names:
            cur, seen = nm, set()
            while cur in parent:
                if cur in seen:
                    return {"err": "cycle", "declared": declared}
                seen.add(cur)
                cur = parent[cur]
        return {"ok": True, "declared": declared, "vc": vc, "size": len(b)}
    return {"err": "no-origin-walk", "declared": declared, "vc": vc, "size": len(b),
            "n_starts": len(starts)}


def prefix_of(fn):
    base = os.path.basename(fn).rsplit(".", 1)[0].lower()
    toks = base.split("_")
    return "_".join(toks[:2]) if len(toks) >= 2 else base


def main():
    files = []
    for dirpath, _, names in os.walk(ROOT):
        for n in names:
            if n.lower().endswith(".mesh"):
                files.append(os.path.join(dirpath, n))
    files.sort()
    lines = []
    ok = 0
    fails = []
    skipped = 0
    by_err = collections.Counter()
    declared_hist = collections.Counter()
    no_origin_declared = collections.Counter()
    for f in files:
        try:
            r = analyze(f)
        except Exception as e:  # noqa
            r = {"err": "exception:%s" % e}
        if r.get("ok"):
            ok += 1
            continue
        skipped += 1
        e = r.get("err", "?")
        by_err[e] += 1
        if e in ("no-origin", "no-origin-walk", "count!=declared"):
            no_origin_declared[r.get("declared", -1)] += 1
        fails.append((f, r))
        d = r.get("declared")
        if d is not None:
            declared_hist[d] += 1
    lines.append("全库 .mesh=%d  走通=%d  失败=%d" % (len(files), ok, skipped))
    lines.append("")
    lines.append("失败型分布：")
    for e, c in by_err.most_common():
        lines.append("  %-22s %d" % (e, c))
    lines.append("")
    lines.append("失败文件按名字前缀（前 2 token）聚类 top30：")
    clusters = collections.defaultdict(list)
    for f, r in fails:
        clusters[prefix_of(f)].append((f, r))
    for pref, lst in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:30]:
        errs = collections.Counter(r.get("err") for _, r in lst)
        lines.append("  %-24s %4d  例：%s  %s" %
                     (pref, len(lst), os.path.basename(lst[0][0]), dict(errs)))
    lines.append("")
    lines.append("失败文件的 0x110 声明数直方（top20）：")
    for d, c in declared_hist.most_common(20):
        lines.append("  declared=%-5d %d" % (d, c))
    lines.append("")
    lines.append(" hamigua 全名单：")
    for f, r in fails:
        if "hamigua" in f.lower():
            lines.append("  %s  %s" % (f, r))
    open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    print("written", OUT)


if __name__ == "__main__":
    main()
