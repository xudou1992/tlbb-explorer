"""差分验证:对多份不同骨数的 .mesh 跑同一套尾部语法,
验证:(1) 语法能整文件走通(到 EOF 分毫不差);(2) 节点数 = 头部声明数;
(3) 树单根、无环、每根非根骨恰被列一次;(4) 骨长区间抽验;
(5) X 字段(u32,根=-1)取值分布。结果写 txt。"""
import json
import math
import os
import re
import struct
import sys

NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")


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
    lens = [math.sqrt(sum(v * v for v in r)) for r in rows]
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
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in m):
        return False
    if abs(m[15] - 1.0) > 1e-3 or abs(m[3]) > 1e-3 or abs(m[7]) > 1e-3 or abs(m[11]) > 1e-3:
        return False
    return ortho3([m[0:3], m[4:7], m[8:11]])


def looks_u92(b, pos):
    """88B:对角值 d×3 组(每组后跟 4 个 0)+ (1.0,0×3) + (100,100,100)。
    d 逐文件可为 0.9998 / 1.0 等,要求三组相等且落在 0.9..1.1。"""
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
    verts = [u32(b, pos + 4 + 4 * k) for k in range(n)]
    if any(verts[k] >= verts[k + 1] for k in range(n - 1)):
        return False
    if verts[-1] >= max(vc, 1):
        return False
    ws = struct.unpack_from("<%df" % n, b, pos + 4 + 4 * n)
    if any(not math.isfinite(w) or w < -1e-3 or w > 1.01 for w in ws):
        return False
    return True


def looks_record96(b, pos):
    if pos + 96 > len(b):
        return None
    nm = name_at(b, pos)
    if nm is None:
        return None
    m = struct.unpack_from("<16f", b, pos + 32)
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in m):
        return None
    if abs(m[15] - 1.0) > 1e-3:
        return None
    if not ortho3([m[0:3], m[4:7], m[8:11]]):
        return None
    return nm, m


def try_entry(b, pos, vc):
    """试探一个节点条目:[RECORD96(名=条目名)]? [块]* [u32 X][名字×2][c][孩子...]。
    成功返回 (entry, newpos);失败返回 None。"""
    p = pos
    rec = looks_record96(b, p)
    if rec is not None:
        p += 96
    mat = None
    while True:
        if looks_u92(b, p):
            p += 88
            continue
        if mat is None and looks_mat64(b, p):
            mat = struct.unpack_from("<16f", b, p)
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
        return None  # 前导记录的名字必须等于条目名,否则它是 scene 前奏(origin/top)
    p += 64
    c = u32(b, p)
    if c > 4096:
        return None
    p += 4
    children = []
    for _ in range(c):
        r = looks_record96(b, p)
        if r is not None:
            children.append({"name": r[0], "bind": list(r[1])})
            p += 96
        else:
            cn = name_at(b, p)
            if cn is None:
                return None
            children.append({"name": cn, "bind": None})
            p += 32
    return {"name": nm1, "x": x, "local": list(mat) if mat else None,
            "inf": None, "children": children,
            "rec_bind": list(rec[1]) if rec else None}, p


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
    xt = u32(b, p)
    p += 4
    cnt = u32(b, p)
    p += 4
    if cnt == 0 or cnt > 4096 or p + 128 * cnt > len(b):
        return None
    entries = []
    for _ in range(cnt):
        if pos + 128 > len(b):
            return None
        tn = name_at(b, p)
        bn = name_at(b, p + 32)
        if tn is None or bn is None:
            return None
        bm = struct.unpack_from("<16f", b, p + 64)
        entries.append({"tx": tn, "bone": bn, "bind": list(bm)})
        p += 128
    return {"x": xt, "count": cnt, "entries": entries}, p


def walk_tail(b, start, vc):
    """从 start 走到 EOF:节点条目 + 可选 scene 前奏记录 + 可选 tx 段。
    成功 = 恰好到 EOF。返回 (prelude, nodes, tx, err)。"""
    pos = start
    prelude = []
    nodes = []
    tx = None
    while pos < len(b):
        got = try_entry(b, pos, vc)
        if got is not None:
            nd, pos = got
            nodes.append(nd)
            continue
        r = looks_record96(b, pos)
        if r is not None:
            prelude.append({"name": r[0], "bind": list(r[1])})
            pos += 96
            continue
        got = try_tx(b, pos, vc)
        if got is not None:
            tx, pos = got
            break
        return None
    if pos != len(b):
        return None
    return prelude, nodes, tx, None


def analyze(path):
    b = open(path, "rb").read()
    if len(b) < 0x114:
        return None
    declared = u32(b, 0x110)
    vc = u32(b, 0x8C)
    if declared == 0 or declared > 4096:
        return None
    # 候选起点:文件后 2/3 里所有 96B 记录位置,升序试,第一个整文件走通者胜
    cands = []
    i = len(b) // 3
    while i + 96 <= len(b):
        if looks_record96(b, i) is not None:
            cands.append(i)
        i += 4
    for start in cands:
        got = walk_tail(b, start, vc)
        if got is None:
            continue
        prelude, nodes, tx, err = got
        if len(nodes) != declared:
            return {"file": path, "declared": declared, "vc": vc,
                    "err": "node count %d != declared %d" % (len(nodes), declared)}
        # 树
        parent = {}
        bad = []
        for nd in nodes:
            for ch in nd["children"]:
                if ch["name"] in parent:
                    bad.append(ch["name"])
                parent[ch["name"]] = nd["name"]
        roots = [nd["name"] for nd in nodes if nd["name"] not in parent]
        # 无环 + 深度
        def depth(nm):
            d, seen = 0, set()
            while nm in parent:
                if nm in seen:
                    return -1
                seen.add(nm)
                nm = parent[nm]
                d += 1
            return d
        cyc = [nd["name"] for nd in nodes if depth(nd["name"]) == -1]
        # 骨长:子(有bind)与父(有bind)
        byname = {nd["name"]: nd for nd in nodes}
        binds = {}
        for nd in nodes:
            if nd.get("rec_bind"):
                binds[nd["name"]] = nd["rec_bind"]
            for ch in nd["children"]:
                if ch["bind"]:
                    binds[ch["name"]] = ch["bind"]
        for pd in prelude:
            binds[pd["name"]] = pd["bind"]
        dists = []
        for nd in nodes:
            p = parent.get(nd["name"])
            if p is None or nd["name"] not in binds or p not in binds:
                continue
            t1 = binds[nd["name"]][12:15]
            t0 = binds[p][12:15]
            d = math.sqrt(sum((a - c) ** 2 for a, c in zip(t0, t1)))
            dists.append(d)
        inband = sum(1 for d in dists if 0.01 <= d <= 2.0)
        xs = {}
        for nd in nodes:
            xs[nd["x"]] = xs.get(nd["x"], 0) + 1
        nbind = len(binds)
        return {
            "file": path, "declared": declared, "vc": vc, "nodes": len(nodes),
            "roots": roots, "dup": bad, "cycles": cyc, "x_hist": xs,
            "pairs_with_both_bind": len(dists), "in_band": inband,
            "dist_max": max(dists) if dists else None,
            "dist_min": min(dists) if dists else None,
            "dists_over2": sorted([round(d, 3) for d in dists if d > 2.0], reverse=True)[:8],
            "with_bind": nbind, "tx_entries": [e["tx"] for e in tx["entries"]] if tx else [],
            "prelude": [p["name"] for p in prelude],
            "hier_sample": {nd["name"]: [c["name"] for c in nd["children"]]
                            for nd in nodes if len(nd["children"]) > 0},
        }
    return {"file": path, "declared": declared, "vc": vc, "err": "no origin-record walk"}


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ".scratch/out/tree/data/source"
    out_txt = sys.argv[2] if len(sys.argv) > 2 else ".scratch/parent_diff.txt"
    out_json = sys.argv[3] if len(sys.argv) > 3 else ".scratch/parent_diff.json"
    files = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.endswith(".mesh"):
                files.append(os.path.join(dirpath, n))
    files.sort()
    results = []
    # 先按声明骨数分桶,挑每种骨数前几份,凑足够多的不同骨数
    by_count = {}
    for f in files:
        try:
            b = open(f, "rb").read()
        except OSError:
            continue
        if len(b) < 0x114:
            continue
        declared = u32(b, 0x110)
        if declared == 0 or declared > 4096:
            continue
        by_count.setdefault(declared, []).append(f)
    picked = []
    for cnt in sorted(by_count):
        picked += by_count[cnt][:6]
    lines = []
    w = lines.append
    w("总 .mesh=%d,有声明骨数的=%d 种骨数:%s" %
      (len(files), len(by_count), sorted(by_count)))
    w("抽样 %d 份跑全语法" % len(picked))
    w("")
    ok = 0
    for f in picked:
        r = analyze(f)
        if r is None:
            continue
        results.append(r)
        if "err" in r:
            w("❌ %s declared=%d err=%s" % (os.path.basename(f), r["declared"], r["err"]))
            continue
        ok += 1
        w("✅ %-52s 声明=%-4d 节点=%-4d 根=%-1s 环=%-2d 双bind对=%-3d 带内=%-3d X分布=%s" %
          (os.path.basename(f), r["declared"], r["nodes"], r["roots"], len(r["cycles"]),
           r["pairs_with_both_bind"], r["in_band"], r["x_hist"]))
    w("")
    w("走通 %d / %d" % (ok, len(results)))
    json.dump(results, open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(out_txt, "w", encoding="utf-8").write("\n".join(lines))
    print("written", out_txt)


main()
