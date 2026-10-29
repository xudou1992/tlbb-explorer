"""完整解析 .mesh 尾部:按「块 + [u32 X][名字×2][孩子数][孩子...]」的语法走一遍,
重建父骨链,并做几何交叉验证:
  1) 树必须单根(000)、无环、46 节点全覆盖;
  2) 有绑定矩阵的父子对,检验 bind 与 MAT64(局部变换)的复合关系
     (四种口径:bind 是否逆阵 × 行/列向量复合),找残差最小的一组;
  3) |child.bind位移 − parent.bind位移| 落在骨长区间。
结果写 txt + json。"""
import json
import math
import re
import struct
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ".scratch/ani/w1351_monster_xiyuqiezei_yifu_001.mesh"
out_txt = sys.argv[2] if len(sys.argv) > 2 else ".scratch/parent_walk.txt"
out_json = sys.argv[3] if len(sys.argv) > 3 else ".scratch/parent_walk.json"
b = open(path, "rb").read()
NAME_OK = re.compile(rb"[0-9A-Za-z_\-.]{3,40}")
TAIL = 0x7690


def name_at(off):
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


def u32(off):
    return struct.unpack_from("<I", b, off)[0]


def f32(off):
    return struct.unpack_from("<f", b, off)[0]


def f32s(off, n):
    return list(struct.unpack_from("<%df" % n, b, off))


def ortho3(rows):
    lens = [math.sqrt(sum(v * v for v in r)) for r in rows]
    if min(lens) < 1e-4 or max(lens) / min(lens) > 1.05:
        return False
    for i in range(3):
        for k in range(i + 1, 3):
            if abs(sum(rows[i][t] * rows[k][t] for t in range(3))) > 1e-2:
                return False
    return True


def looks_mat64(pos):
    """64B 局部矩阵:16 f32,行主序,末列 (0,0,0,1),前三行正交。"""
    if pos + 64 > len(b):
        return False
    m = f32s(pos, 16)
    if not all(math.isfinite(v) and abs(v) < 1e7 for v in m):
        return False
    if abs(m[15] - 1.0) > 1e-3 or abs(m[3]) > 1e-3 or abs(m[7]) > 1e-3 or abs(m[11]) > 1e-3:
        return False
    return ortho3([m[0:3], m[4:7], m[8:11]])


def looks_u92(pos):
    if pos + 88 > len(b):
        return False
    if abs(f32(pos) - 0.9998902082) > 1e-3:
        return False
    if abs(f32(pos + 20) - 0.9998902082) > 1e-3:
        return False
    if abs(f32(pos + 40) - 0.9998902082) > 1e-3:
        return False
    if abs(f32(pos + 60) - 1.0) > 1e-3:
        return False
    for o in (76, 80, 84):
        if abs(f32(pos + o) - 100.0) > 1e-2:
            return False
    return True


def looks_inf(pos):
    """[u32 n][n×u32 顶点(严格递增)][n×f32 权重(0..1.01)]"""
    if pos + 4 > len(b):
        return False
    n = u32(pos)
    if n == 0:
        return True  # 空影响表
    if pos + 4 + 8 * n > len(b) or n > 200000:
        return False
    verts = [u32(pos + 4 + 4 * k) for k in range(n)]
    if any(verts[k] >= verts[k + 1] for k in range(n - 1)):
        return False
    if verts[-1] > 1000000:
        return False
    ws = f32s(pos + 4 + 4 * n, n)
    if any(not math.isfinite(w) or w < -1e-3 or w > 1.01 for w in ws):
        return False
    return True


lines = []
w = lines.append
w("file=%s size=%d declared=%d" % (path, len(b), u32(0x110)))
pos = TAIL
# 前导:origin / top 两条裸记录
prelude = []
for _ in range(2):
    nm = name_at(pos)
    mat = f32s(pos + 32, 16)
    prelude.append({"name": nm, "bind": mat})
    pos += 96
w("prelude: %s" % ", ".join(p["name"] for p in prelude))

nodes = []
tx = None
err = None
while pos < len(b):
    start = pos
    mat = None
    inf_n = None
    has_u92 = False
    while True:
        if looks_u92(pos):
            has_u92 = True
            pos += 88
            continue
        if looks_mat64(pos):
            mat = f32s(pos, 16)
            pos += 64
            continue
        if looks_inf(pos):
            inf_n = u32(pos)
            pos += 4 + 8 * inf_n
            continue
        break
    x = u32(pos)
    pos += 4
    nm1 = name_at(pos)
    nm2 = name_at(pos + 32)
    if nm1 is None or nm1 != nm2:
        # 不是节点尾 → 试 tx 段:[MAT64][INF][U92][X][count][count×(tx名+RECORD96)]
        pos = start
        mat = None
        inf_n = None
        has_u92 = False
        while True:
            if looks_u92(pos):
                has_u92 = True
                pos += 88
                continue
            if looks_mat64(pos):
                mat = f32s(pos, 16)
                pos += 64
                continue
            if looks_inf(pos):
                inf_n = u32(pos)
                pos += 4 + 8 * inf_n
                continue
            break
        xt = u32(pos)
        pos += 4
        cnt = u32(pos)
        pos += 4
        entries = []
        for _ in range(cnt):
            tn = name_at(pos)
            bn = name_at(pos + 32)
            bm = f32s(pos + 64, 16)
            entries.append({"tx": tn, "bone": bn, "bind": bm})
            pos += 128
        tx = {"x": xt, "mat": mat, "inf": inf_n, "count": cnt, "entries": entries}
        w("TX section: x=%d inf=%d count=%d entries=%s" %
          (xt, inf_n, cnt, [(e["tx"], e["bone"]) for e in entries]))
        break
    pos += 64
    c = u32(pos)
    pos += 4
    children = []
    for _ in range(c):
        cn = name_at(pos)
        if cn is None:
            err = "child name fail @0x%x" % pos
            break
        if pos + 64 <= len(b):
            mtest = f32s(pos + 32, 16)
            ok = (all(math.isfinite(v) and abs(v) < 1e7 for v in mtest)
                  and abs(mtest[15] - 1.0) < 1e-3
                  and ortho3([mtest[0:3], mtest[4:7], mtest[8:11]]))
        else:
            ok = False
        if ok:
            children.append({"name": cn, "bind": mtest})
            pos += 96
        else:
            children.append({"name": cn, "bind": None})
            pos += 32
    if err:
        break
    nodes.append({
        "name": nm1, "x": x, "local": mat, "inf": inf_n, "u92": has_u92,
        "children": children, "at": "0x%06x" % start,
    })

w("")
w("parsed nodes=%d  err=%s" % (len(nodes), err))
for nd in nodes:
    w("  %-30s x=%-3d mat=%-3s inf=%-4s u92=%-5s kids=%s" %
      (nd["name"], nd["x"], "Y" if nd["local"] else "-",
       "-" if nd["inf"] is None else nd["inf"], nd["u92"],
       ",".join(ch["name"] + ("*" if ch["bind"] else "") for ch in nd["children"])))
if pos < len(b) and tx is None:
    w("LEFTOVER %d bytes @0x%06x" % (len(b) - pos, pos))

# ---- 建父链 ----
byname = {nd["name"]: nd for nd in nodes}
parent = {}
dup = []
for nd in nodes:
    for ch in nd["children"]:
        if ch["name"] in parent:
            dup.append(ch["name"])
        parent[ch["name"]] = nd["name"]
roots = [nd["name"] for nd in nodes if nd["name"] not in parent]
w("")
w("roots=%s dup_children=%s declared=%d nodes=%d" % (roots, dup, u32(0x110), len(nodes)))

# 环检测
def depth(nm, seen=None):
    seen = seen or set()
    d = 0
    while nm in parent:
        if nm in seen:
            return -1
        seen.add(nm)
        nm = parent[nm]
        d += 1
    return d

cyc = [nd["name"] for nd in nodes if depth(nd["name"]) == -1]
w("cycles=%s" % cyc)

# ---- 几何验证 ----
def mul_row(A, B):
    """行向量约定: world = local · parent (4x4, 16 f32 平铺)"""
    R = [[sum(A[i * 4 + k] * B[k * 4 + j] for k in range(4)) for j in range(4)] for i in range(4)]
    return [R[i][j] for i in range(4) for j in range(4)]


def inv(m):
    """4x4 仿射逆(行主序平铺,末列 0,0,0,1)"""
    r = [[m[i * 4 + j] for j in range(3)] for i in range(3)]
    t = (m[12], m[13], m[14])
    det = (r[0][0] * (r[1][1] * r[2][2] - r[1][2] * r[2][1])
           - r[0][1] * (r[1][0] * r[2][2] - r[1][2] * r[2][0])
           + r[0][2] * (r[1][0] * r[2][1] - r[1][1] * r[2][0]))
    if abs(det) < 1e-12:
        return None
    ir = [[0.0] * 3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            ir[i][j] = ((r[(j + 1) % 3][(k + 1) % 3] * r[(j + 2) % 3][(k + 2) % 3]
                         - r[(j + 1) % 3][(k + 2) % 3] * r[(j + 2) % 3][(k + 1) % 3]) / det)
    it = [-(ir[i][0] * t[0] + ir[i][1] * t[1] + ir[i][2] * t[2]) for i in range(3)]
    out = []
    for i in range(3):
        out += ir[i] + [0.0]
    out += it + [1.0]
    return out


def fro(m1, m2):
    return math.sqrt(sum((a - c) ** 2 for a, c in zip(m1, m2)))


pairs = []
for nd in nodes:
    if nd["name"] not in parent:
        continue
    p = byname[parent[nd["name"]]]
    if nd["local"] and p["local"]:
        pairs.append((nd["name"], p["name"], nd["local"], p["local"]))

w("parent-child pairs with local matrices: %d" % len(pairs))
# 口径:bind_stored = world 或 inv(world);world_child = local∘world_parent 或 world_parent∘local
results = {}
for inv_case in (False, True):
    for order in ("LR", "RL"):
        res = []
        for cn, pn, lc, pc in pairs:
            A = inv(lc) if inv_case else lc
            B = inv(pc) if inv_case else pc
            pred = mul_row(A, B) if order == "LR" else mul_row(B, A)
            res.append((cn, pn, pred))
        results[(inv_case, order)] = res

# 用「有 bind 的节点」对账:bind_stored 与 pred 的关系
# 对每个口径,统计 pred(child) 与 pred(parent) 的关系能否再现 bind
# 实际检验:bind_child =? f(local_child, bind_parent)
binds = {}
for nd in nodes:
    for ch in nd["children"]:
        if ch["bind"]:
            binds[ch["name"]] = ch["bind"]
w("")
w("bind matrices available for %d child-entries" % len(binds))
best = None
for inv_case in (False, True):
    for order in ("LR", "RL"):
        res = results[(inv_case, order)]
        rows = []
        for cn, pn, pred in res:
            if cn in binds and pn in binds:
                if inv_case:
                    # bind=inv(world):bind_child = inv(local∘world_p) = inv(world_p)∘inv(local)
                    lpred = mul_row(binds[pn], inv(lc_of(cn))) if False else None
                rows.append((cn, pn))
        # 直接口径:bind_stored 是否 = world 或 inv(world)?
        # 用根链:world(bip01) = local(bip01)∘world(000)?000 无矩阵 → 从有矩阵的最深根起
        pass

# 更直接的检验:bind_child 与 bind_parent 的相对变换 = local?
w("")
w("check: rel = bind_child ∘ inv(bind_parent)  vs local  (行向量)")
w("        or rel = inv(bind_parent) ∘ bind_child (列向量口径)")
rel_rows = []
for cn, pn, lc, pc in pairs:
    if cn in binds and pn in binds:
        bc, bp = binds[cn], binds[pn]
        rel1 = mul_row(bc, inv(bp))
        rel2 = mul_row(inv(bp), bc)
        d1 = fro(rel1, lc)
        d2 = fro(rel2, lc)
        # bind 是否逆阵:inv(bind) 的旋转让 rel 更贴近?
        rel3 = mul_row(inv(bc), bp)
        rel4 = mul_row(bp, inv(bc))
        d3 = fro(rel3, inv(lc))
        d4 = fro(rel4, inv(lc))
        rel_rows.append((cn, pn, d1, d2, d3, d4))
for cn, pn, d1, d2, d3, d4 in rel_rows:
    w("  %-26s <- %-22s  d(R,L)=%.4f d(L,R)=%.4f  d(inv)R=%.4f d(L,inv)=%.4f" %
      (cn, pn, d1, d2, d3, d4))

# 骨长区间
w("")
w("bind-translation distances child vs parent:")
dists = []
for nd in nodes:
    if nd["name"] not in parent:
        continue
    ch_bind = None
    for ch in nd["children"]:
        if ch["name"] == nd["name"]:
            continue
    for ch in nd["children"]:
        if ch["bind"]:
            t1 = ch["bind"][12:15]
            p = nd
            # 父的 bind:父在自己的父的孩子表里
            if p["name"] in parent:
                gp = byname[parent[p["name"]]]
                pb = next((c["bind"] for c in gp["children"] if c["name"] == p["name"]), None)
                if pb:
                    t0 = pb[12:15]
                    d = math.sqrt(sum((a - c) ** 2 for a, c in zip(t0, t1)))
                    dists.append((ch["name"], p["name"], d))
for cn, pn, d in sorted(dists, key=lambda x: -x[2]):
    flag = "OK" if 0.01 <= d <= 2.0 else ("BIG" if d > 2.0 else "TINY")
    w("  %-26s <- %-22s dist=%.4f  %s" % (cn, pn, d, flag))

json.dump({"nodes": nodes, "tx": tx, "parent": parent, "dists": dists},
          open(out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
open(out_txt, "w", encoding="utf-8").write("\n".join(lines))
print("written", out_txt)
