"""
axis_probe/probe.py  —  取证：骨数据空间 vs 网格空间 之间是否差一个全局刚体/相似变换 S
数据源: D:\\TLGL\\.scratch\\glb_rigged\\m_db18794d0000cd38.glb  (西域窃贼 yifu_001, 46 骨 781 顶点)
只读仓库产物，只用 numpy + 标准库；不跑 cargo，不改仓库代码。
"""
import json, struct, math, pathlib, itertools
import numpy as np

OUT = pathlib.Path(r"D:\TLGL\.scratch\axis_probe")
GLB = OUT.parent / "glb_rigged" / "m_db18794d0000cd38.glb"

# ---------------------------------------------------------------- GLB reader
def load_glb(path):
    data = path.read_bytes()
    magic, ver, total = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67
    off, j, binbuf = 12, None, b""
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off); off += 8
        chunk = data[off:off + clen]; off += clen
        if ctype == 0x4E4F534A: j = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942: binbuf = chunk
    return j, binbuf

g, BIN = load_glb(GLB)
ACC, BV = g["accessors"], g["bufferViews"]
CT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

def read_acc(ai):
    a = ACC[ai]; bv = BV[a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    fmt = "<" + CT[a["componentType"]] * NCOMP[a["type"]]
    stride = bv.get("byteStride") or struct.calcsize(fmt)
    o = np.empty((a["count"], NCOMP[a["type"]]), dtype=np.float64)
    for i in range(a["count"]):
        o[i] = struct.unpack_from(fmt, BIN, base + i * stride)
    return o

prim = g["meshes"][0]["primitives"][0]
POS = read_acc(prim["attributes"]["POSITION"])
JOI = read_acc(prim["attributes"]["JOINTS_0"])          # u16 x4, 每顶点的骨索引
WEI = read_acc(prim["attributes"]["WEIGHTS_0"])          # f32 x4
IBMm = read_acc(g["skins"][0]["inverseBindMatrices"]).reshape(len(g["skins"][0]["joints"]), 4, 4, order="F")
JOINTS = g["skins"][0]["joints"]; NJ = len(JOINTS); NODES = g["nodes"]
names = [NODES[ni]["name"] for ni in JOINTS]
print("joints=%d verts=%d sceneNodes=%s" % (NJ, len(POS), g["scenes"][0]["nodes"]))
print("mesh node0 keys:", {k: v for k, v in NODES[0].items() if k != "children"})

# ------------------------------------ 两条路求 bind 世界矩阵
def affine_inv4(m):
    R = m[:3, :3]; t = m[:3, 3]; Ri = np.linalg.inv(R)
    o = np.eye(4); o[:3, :3] = Ri; o[:3, 3] = -Ri @ t; return o

def quat_mat(q):
    x, y, z, w = q; n = math.sqrt(x*x+y*y+z*z+w*w); x, y, z, w = x/n, y/n, z/n, w/n
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def local_mat(ni):
    n = NODES[ni]; m = np.eye(4)
    m[:3, :3] = quat_mat(n.get("rotation", [0, 0, 0, 1])) * np.array(n.get("scale", [1, 1, 1]))
    m[:3, 3] = n.get("translation", [0, 0, 0]); return m

parents = {}
for ni, n in enumerate(NODES):
    for c in n.get("children", []): parents[c] = ni
jpar_joint = [(JOINTS.index(parents[ni]) if (ni in parents and parents[ni] in JOINTS) else -1) for ni in JOINTS]

def world_from_tree(ni):
    chain = []
    while True:
        chain.append(ni)
        if ni not in parents: break
        ni = parents[ni]
    m = np.eye(4)
    for a in reversed(chain): m = m @ local_mat(a)   # chain[-1] = 场景根，chain[0] = 自身
    return m

W_ibm = np.stack([affine_inv4(IBMm[j]) for j in range(NJ)])            # 路 A
W_tree = np.stack([world_from_tree(JOINTS[j]) for j in range(NJ)])     # 路 B
dAB = np.stack([np.abs(W_ibm[j] - W_tree[j]).max() for j in range(NJ)])
print("\n[核对] 路A(inv(IBM)) vs 路B(node TRS 复合): 全骨最大元素差 %.3e ; 差>1e-3 的骨 %d 根" % (dAB.max(), int((dAB > 1e-3).sum())))
rot_gap = []
for j in range(NJ):
    Rr = W_ibm[j, :3, :3].T @ W_tree[j, :3, :3]
    rot_gap.append(math.degrees(math.acos(max(-1, min(1, (np.trace(Rr)-1)/2)))))
tp = np.stack([np.linalg.norm(W_ibm[j, :3, 3] - W_tree[j, :3, 3]) for j in range(NJ)])
print("[核对] 逐骨: 旋转夹角(deg) / 原点距离")
for j in range(NJ):
    flag = "  <== 不一致" if dAB[j] > 1e-3 else ""
    print("   %2d %-26s rot=%6.1f  dOrig=%6.3f  A=(%7.3f %7.3f %7.3f) B=(%7.3f %7.3f %7.3f)%s" % (
        j, names[j], rot_gap[j], tp[j], *W_ibm[j, :3, 3], *W_tree[j, :3, 3], flag))

# ------------------------------------------------ 蒙皮重心
# 组装稠密权重矩阵 Wm[n_vert, NJ]：Wm[i, j] = 顶点 i 挂在骨 j 上的权重（4 个槽位求和）
Wm = np.zeros((len(POS), NJ))
for slot in range(4):
    idx = JOI[:, slot].astype(int)
    np.add.at(Wm, (np.arange(len(POS)), idx), WEI[:, slot])
wsum = Wm.sum(axis=1)
mx = Wm.max(axis=1); amax = Wm.argmax(axis=1)
exclusive = mx > 0.999
cnt = {j: int(((amax == j) & exclusive & (wsum > 0.999)).sum()) for j in range(NJ)}
top = sorted(cnt.items(), key=lambda kv: -kv[1])[:4]
ROOT = top[0][0]
print("\n独占某骨的顶点 top4:", [(names[j], c) for j, c in top], "=> 根骨 joint %d '%s'" % (ROOT, names[ROOT]))
mask_used = (wsum > 0.999) & ~(exclusive & (amax == ROOT))
print("顶点 总%d / 权重和>0.999 %d / 全权重挂根骨 %d / 参与重心统计 %d" % (
    len(POS), int((wsum > 0.999).sum()), int((exclusive & (amax == ROOT)).sum()), int(mask_used.sum())))
V = POS[mask_used]; Wv = Wm[mask_used]
C = np.zeros((NJ, 3)); Wt = np.zeros(NJ); covered = np.zeros(NJ, bool)
for j in range(NJ):
    w = Wv[:, j]; sel = w > 0
    if sel.any():
        C[j] = (V[sel] * w[sel, None]).sum(0) / w[sel].sum(); Wt[j] = w[sel].sum(); covered[j] = True

def fitset(P):
    f = covered.copy(); f[ROOT] = False
    keep = [j for j in np.where(f)[0] if np.isfinite(P[j]).all()]
    return np.array(keep)

# ------------------------------------------------ Umeyama
def umeyama(Ps, Ct, weight=None, allow_scale=True):
    w = np.ones(len(Ps)) if weight is None else np.asarray(weight, float); w = w / w.sum()
    pm = (Ps * w[:, None]).sum(0); cm = (Ct * w[:, None]).sum(0)
    A = Ps - pm; B = Ct - cm
    U, D, Vt = np.linalg.svd((A * w[:, None]).T @ B)
    S = np.eye(3); S[2, 2] = -1 if np.linalg.det(U) * np.linalg.det(Vt) < 0 else 1
    R = Vt.T @ S @ U.T
    s = float(np.trace(np.diag(D) @ S) / float((w[:, None] * A * A).sum())) if allow_scale else 1.0
    return s, R, cm - s * R @ pm

def apply_(Ps, s, R, t): return (s * (R @ Ps.T).T) + t

def perms():
    for pi in itertools.permutations(range(3)):
        for sg in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for r, (c, s_) in enumerate(zip(pi, sg)): M[r, c] = s_
            yield pi, sg, M

def fit_fixed_R(Rf, Ps, Ct, allow_scale=True, weight=None):
    w = np.ones(len(Ps)) if weight is None else np.asarray(weight, float); w = w / w.sum()
    pm = (Ps * w[:, None]).sum(0); cm = (Ct * w[:, None]).sum(0)
    A = Ps - pm; B = Ct - cm
    s = float(np.einsum("i,ij,ij->", w, A @ Rf.T, B) / (w[:, None] * A * A).sum()) if allow_scale else 1.0
    t = cm - s * Rf @ pm
    L = np.linalg.norm(apply_(Ps, s, Rf, t) - Ct, axis=1)
    return s, math.sqrt(float((w * L**2).sum())), float((w * L).sum()), L

def quat_of(R):
    qw = 0.5 * math.sqrt(max(0.0, 1 + R[0,0] + R[1,1] + R[2,2]))
    if qw > 1e-9:
        return [ (R[2,1]-R[1,2])/(4*qw), (R[0,2]-R[2,0])/(4*qw), (R[1,0]-R[0,1])/(4*qw), qw ]
    return [0,0,0,1]

def eulerXYZ(R):
    sy = max(-1.0, min(1.0, R[0,2])); pitch = math.asin(sy)
    if abs(sy) < 0.99999:
        return [math.degrees(math.atan2(-R[1,2], R[2,2])), math.degrees(pitch), math.degrees(math.atan2(-R[0,1], R[1,1]))]
    return [0.0, math.degrees(pitch), math.degrees(math.atan2(R[1,0], R[0,0]))]

def evaluate(P, tag, verbose=True):
    fit = fitset(P)
    Ps = P[fit]; Ct = C[fit]
    pre = np.linalg.norm(Ps - Ct, axis=1)
    r = dict(tag=tag, nbones=int(len(fit)), bone_names=[names[j] for j in fit],
             pre_mean=float(pre.mean()), pre_median=float(np.median(pre)), pre_max=float(pre.max()))
    if verbose:
        print("\n===== 骨原点来源: %s  (参与拟合骨 %d 根, 剔除根骨 '%s')" % (tag, len(fit), names[ROOT]))
        print("  拟合前 |p-c|: mean=%.4f median=%.4f max=%.4f" % (pre.mean(), np.median(pre), pre.max()))
    fits = {}
    for nm, sc, wgt in [("相似(含缩放)", True, None), ("刚体(无缩放)", False, None),
                        ("相似·Σw加权", True, Wt[fit]), ("刚体·Σw加权", False, Wt[fit])]:
        s, R, t = umeyama(Ps, Ct, weight=wgt, allow_scale=sc)
        L = np.linalg.norm(apply_(Ps, s, R, t) - Ct, axis=1)
        wn = np.ones(len(fit)) / len(fit) if wgt is None else wgt / wgt.sum()
        rms = math.sqrt(float((wn * L**2).sum()))
        fits[nm] = dict(scale=s, rms=rms, mean=float(L.mean()), max=float(L.max()),
                        R=R.tolist(), t=t.tolist(), quat=quat_of(R), euler=eulerXYZ(R),
                        axis_dev=float(np.abs(R - np.round(R)).max()),
                        ortho_dev=float(np.abs(R.T @ R - np.eye(3)).max()),
                        per_bone={names[j]: round(float(L[i]), 4) for i, j in enumerate(fit)})
        if verbose:
            print("  [%-12s] scale=%.5f RMS=%.4f (前=%.4f) mean=%.4f max=%.4f | R偏离最近整数=%.4f 正交偏差=%.4f" % (
                nm, s, rms, math.sqrt((pre**2).mean()), L.mean(), L.max(), fits[nm]["axis_dev"], fits[nm]["ortho_dev"]))
            Rm = np.array(R)
            print("      R=\n%s      quat(xyzw)=%s  eulerXYZ=%s" % (
                "\n".join("        " + np.array2string(Rm[i], precision=4, suppress_small=True) for i in range(3)),
                np.round(fits[nm]["quat"], 4).tolist(), np.round(fits[nm]["euler"], 1).tolist()))
    # 48 个带符号置换（干净轴变换）穷举
    best = None; best_ns = None
    for pi, sg, M in perms():
        s, rms, mean, L = fit_fixed_R(M, Ps, Ct, True)
        if best is None or rms < best[0]: best = (rms, mean, s, pi, sg, M, L)
        s2, rms2, mean2, L2 = fit_fixed_R(M, Ps, Ct, False)
        if best_ns is None or rms2 < best_ns[0]: best_ns = (rms2, mean2, 1.0, pi, sg, M, L2)
    if verbose:
        print("  [48轴对齐穷举] 含缩放最佳 RMS=%.4f mean=%.4f scale=%.4f R[i]=%s signs=%s det=%.0f" % (
            best[0], best[1], best[2], best[3], best[4], np.linalg.det(best[5])))
        print("      逐骨残差: %s" % {names[j]: round(float(best[6][i]), 3) for i, j in enumerate(fit)})
        print("  [48轴对齐穷举] 不含缩放最佳 RMS=%.4f mean=%.4f R[i]=%s signs=%s det=%.0f" % (
            best_ns[0], best_ns[1], best_ns[3], best_ns[4], np.linalg.det(best_ns[5])))
    r["fits"] = fits
    r["axis_aligned"] = dict(rms=best[0], mean=best[1], scale=best[2], perm=best[3], signs=best[4],
                             det=float(np.linalg.det(best[5])), per_bone=[float(x) for x in best[6]])
    r["axis_aligned_ns"] = dict(rms=best_ns[0], mean=best_ns[1], perm=best_ns[3], signs=best_ns[4],
                                det=float(np.linalg.det(best_ns[5])), per_bone=[float(x) for x in best_ns[6]])
    # 父子骨方向一致性诊断：用刚体拟合的 R
    Rr = np.array(fits["刚体(无缩放)"]["R"]); Rsim = np.array(fits["相似(含缩放)"]["R"])
    pairs = []
    for i, k in enumerate(fit):
        j = jpar_joint[k]
        if j < 0 or j not in set(fit.tolist()): continue
        db = P[k] - P[j]; dc = C[k] - C[j]
        nb = float(np.linalg.norm(db)); nc = float(np.linalg.norm(dc))
        if nb < 1e-6 or nc < 1e-6: continue
        def ang(vec):
            return math.degrees(math.acos(max(-1.0, min(1.0, float(vec @ dc) / (np.linalg.norm(vec) * nc)))))
        pairs.append(dict(parent=names[j], child=names[k], nb=nb, nc=nc,
                          raw=ang(db), after_rigid=ang(Rr @ db), after_sim=ang(Rsim @ db)))
    if verbose and pairs:
        for key, lbl in [("raw", "未变换"), ("after_rigid", "施加刚体R后"), ("after_sim", "施加相似R后")]:
            a = np.array([p[key] for p in pairs])
            print("  [父子骨方向 vs 重心方向夹角 · %s] n=%d mean=%.1f° med=%.1f° max=%.1f° >30°: %d" % (
                lbl, len(a), a.mean(), np.median(a), a.max(), int((a > 30).sum())))
        worst = sorted(pairs, key=lambda p: -p["after_sim"])[:8]
        print("      施加最佳R后最差 8 对: %s" % [(p["parent"], p["child"], round(p["raw"], 1), round(p["after_sim"], 1)) for p in worst])
    r["dir_pairs"] = pairs
    return r

SRC = {
    "A: inv(IBM) 平移列": W_ibm[:, :3, 3],
    "B: node TRS 复合 平移列": W_tree[:, :3, 3],
    "C: IBM 原始平移列 m[0:3,3]": np.stack([IBMm[j][:3, 3] for j in range(NJ)]),
    "D: IBM 转置读法 m[3,0:3]": np.stack([IBMm[j][3, :3] for j in range(NJ)]),
    "E: 节点局部 translation": np.stack([NODES[JOINTS[j]].get("translation", [0, 0, 0]) for j in range(NJ)]),
}
allres = {}
for tag, P in SRC.items():
    allres[tag] = evaluate(P, tag)

# 附带: 网格与骨骨架的整体尺度/包围盒
print("\n[包围盒] 网格 POSITION min=%s max=%s span=%s" % (
    np.round(POS.min(0), 3).tolist(), np.round(POS.max(0), 3).tolist(), np.round(np.ptp(POS, axis=0), 3).tolist()))
fA = fitset(SRC["A: inv(IBM) 平移列"])
print("  %-26s min=%s max=%s span=%s" % ("蒙皮重心(参与拟合骨)", np.round(C[fA].min(0), 3).tolist(),
                                         np.round(C[fA].max(0), 3).tolist(), np.round(np.ptp(C[fA], axis=0), 3).tolist()))
for tag in ("A: inv(IBM) 平移列", "B: node TRS 复合 平移列", "C: IBM 原始平移列 m[0:3,3]", "E: 节点局部 translation"):
    P = SRC[tag]
    print("  %-26s min=%s max=%s span=%s" % (tag, np.round(P.min(0), 3).tolist(), np.round(P.max(0), 3).tolist(),
                                             np.round(np.ptp(P, axis=0), 3).tolist()))

json.dump(dict(glb=str(GLB), names=names, root=names[ROOT], jpar=[names[j] if j >= 0 else None for j in jpar_joint],
               centroids=C.tolist(), weight_sum=Wt.tolist(), covered=[int(x) for x in np.where(covered)[0]],
               sources={k: v.tolist() for k, v in SRC.items()},
               world_ibm=W_ibm.tolist(), world_tree=W_tree.tolist(),
               crosscheck=dict(max_elem_diff=float(dAB.max()), n_mismatch=int((dAB > 1e-3).sum()),
                               rot_gap_deg=rot_gap, origin_gap=tp.tolist()),
               evals=allres),
          (OUT / "data.json").open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nwrote data.json")
