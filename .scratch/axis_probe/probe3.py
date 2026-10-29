"""
probe3.py — 追加核对
(a) 两个 GLB 都跑一遍核心量: A=inv(Mraw) 与 C=Mraw平移列 各自到蒙皮重心的 Umeyama 拟合与 48 轴变换穷举
(b) 动画侧: 用现成 GLB 复现撕裂量 (位移 mean/max)，看动画 key 落在哪个空间
(c) 骨骼刚性检查: 父子骨原点距离在动画各帧是否守恒
"""
import json, struct, math, itertools, pathlib
import numpy as np
import glbcore as G

CT = {"5126": "f", "5123": "H"}
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

def load_any(path):
    data = path.read_bytes(); off, g, BIN = 12, None, b""
    while off + 8 <= len(data):
        clen, ctype = struct.unpack_from("<II", data, off); off += 8
        ch = data[off:off+clen]; off += clen
        if ctype == 0x4E4F534A: g = json.loads(ch.decode("utf-8"))
        elif ctype == 0x004E4942: BIN = ch
    return g, BIN

def acc(g, BIN, ai):
    a = g["accessors"][ai]; bv = g["bufferViews"][a["bufferView"]]
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    fmt = "<" + CT[str(a["componentType"])] * NCOMP[a["type"]]
    stride = bv.get("byteStride") or struct.calcsize(fmt)
    o = np.empty((a["count"], NCOMP[a["type"]]))
    for i in range(a["count"]): o[i] = struct.unpack_from(fmt, BIN, base + i*stride)
    return o

def affine_inv4(m):
    R = m[:3, :3]; t = m[:3, 3]; Ri = np.linalg.inv(R)
    o = np.eye(4); o[:3, :3] = Ri; o[:3, 3] = -Ri @ t; return o

def quat_mat(q):
    x, y, z, w = q; n = math.sqrt(x*x+y*y+z*z+w*w); x, y, z, w = x/n, y/n, z/n, w/n
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])

def umeyama(Ps, Ct, allow_scale=True):
    pm = Ps.mean(0); cm = Ct.mean(0); A = Ps - pm; B = Ct - cm
    U, D, Vt = np.linalg.svd(A.T @ B); S = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0: S[2, 2] = -1
    R = Vt.T @ S @ U.T
    s = float(np.trace(np.diag(D) @ S) / (A*A).sum()) if allow_scale else 1.0
    return s, R, cm - s * R @ pm

def perms():
    for pi in itertools.permutations(range(3)):
        for sg in itertools.product([1, -1], repeat=3):
            M = np.zeros((3, 3))
            for r, (c, s_) in enumerate(zip(pi, sg)): M[r, c] = s_
            yield pi, sg, M

def fit_fixed(Rf, Ps, Ct, allow_scale=True):
    pm = Ps.mean(0); cm = Ct.mean(0); A = Ps - pm; B = Ct - cm
    s = float((A @ Rf.T * B).sum() / (A*A).sum()) if allow_scale else 1.0
    t = cm - s * Rf @ pm
    L = np.linalg.norm((s*(Rf@Ps.T).T + t) - Ct, axis=1)
    return s, float(np.sqrt((L**2).mean())), float(L.mean()), L

def analyse(path):
    g, BIN = load_any(path)
    prim = g["meshes"][0]["primitives"][0]
    POS = acc(g, BIN, prim["attributes"]["POSITION"])
    JOI = acc(g, BIN, prim["attributes"]["JOINTS_0"]); WEI = acc(g, BIN, prim["attributes"]["WEIGHTS_0"])
    NODES = g["nodes"]; JOINTS = g["skins"][0]["joints"]; NJ = len(JOINTS)
    Mraw = acc(g, BIN, g["skins"][0]["inverseBindMatrices"]).reshape(NJ, 4, 4, order="F")
    names = [NODES[ni]["name"] for ni in JOINTS]
    Wm = np.zeros((len(POS), NJ))
    for s in range(4): np.add.at(Wm, (np.arange(len(POS)), JOI[:, s].astype(int)), WEI[:, s])
    wsum = Wm.sum(1); mx = Wm.max(1); am = Wm.argmax(1)
    cnt = {j: int(((am == j) & (mx > .999) & (wsum > .999)).sum()) for j in range(NJ)}
    ROOT = max(cnt, key=cnt.get)
    used = (wsum > .999) & ~((mx > .999) & (am == ROOT))
    V = POS[used]; Wv = Wm[used]
    C = np.zeros((NJ, 3)); cov = np.zeros(NJ, bool)
    for j in range(NJ):
        w = Wv[:, j]; sel = w > 0
        if sel.any(): C[j] = (V[sel]*w[sel, None]).sum(0)/w[sel].sum(); cov[j] = True
    W = np.stack([affine_inv4(Mraw[j]) for j in range(NJ)])
    fit = np.array([j for j in np.where(cov)[0] if j != ROOT], dtype=int)
    print("\n### %s  骨%d 顶点%d 根骨'%s'独占%d 参与重心%d 参与拟合%d" % (
        path.name, NJ, len(POS), names[ROOT], cnt[ROOT], int(used.sum()), len(fit)))
    if len(fit) < 4:
        print("  覆盖骨不足（该文件 prim0 只有 %d 顶点，%d 个图元）→ 跳过" % (len(POS), len(g["meshes"][0]["primitives"])))
        return
    for lbl, P in [("A=inv(Mraw)", W[:, :3, 3]), ("C=Mraw平移列", np.stack([Mraw[j][:3, 3] for j in range(NJ)]))]:
        Ps, Ct = P[fit], C[fit]
        pre = np.linalg.norm(Ps - Ct, axis=1)
        s, R, t = umeyama(Ps, Ct, False); L = np.linalg.norm((R@Ps.T).T + t - Ct, axis=1)
        ss, Rs, ts = umeyama(Ps, Ct, True); Ls = np.linalg.norm((ss*(Rs@Ps.T).T + ts) - Ct, axis=1)
        bc = [tuple(fit_fixed(M, Ps, Ct, False)[1:3]) + (pi, sg) for pi, sg, M in perms()]
        best = min(bc)
        bs = [tuple(fit_fixed(M, Ps, Ct, True)[1:3]) + (fit_fixed(M, Ps, Ct, True)[0], pi, sg) for pi, sg, M in perms()]
        bsc = min(bs)
        print("  %-14s 拟合前 mean=%.4f med=%.4f max=%.4f" % (lbl, pre.mean(), np.median(pre), pre.max()))
        print("     Umeyama刚体: RMS=%.4f mean=%.4f  R偏离整数最大=%.4f  R偏离单位阵=%.4f" % (
            np.sqrt((L**2).mean()), L.mean(), np.abs(R-np.round(R)).max(), np.abs(R-np.eye(3)).max()))
        print("     Umeyama相似: scale=%.4f RMS=%.4f mean=%.4f R偏离整数=%.4f" % (ss, np.sqrt((Ls**2).mean()), Ls.mean(), np.abs(Rs-np.round(Rs)).max()))
        print("     48轴变换最优(无缩放): RMS=%.4f mean=%.4f perm=%s signs=%s" % (best[0], best[1], best[2], best[3]))
        print("     48轴变换最优(含缩放): RMS=%.4f mean=%.4f scale=%.4f perm=%s signs=%s" % (bsc[0], bsc[1], bsc[2], bsc[3], bsc[4]))
    return g, BIN, NODES, JOINTS, Mraw, W, names, POS, Wm, ROOT, JOI, WEI

# ---- 动画侧
res = analyse(G.GLB)
g, BIN, NODES, JOINTS, Mraw, W, names, POS, Wm, ROOT, JOI, WEI = res
analyse(pathlib.Path(r"D:\TLGL\.scratch\glb_rigged\m_8ff895cd00003a5c.glb"))
NJ = len(JOINTS)
parents = {}
for ni, n in enumerate(NODES):
    for c in n.get("children", []): parents[c] = ni
jpar = [(JOINTS.index(parents[ni]) if (ni in parents and parents[ni] in JOINTS) else -1) for ni in JOINTS]

def local_from(trs):
    m = np.eye(4)
    m[:3, :3] = quat_mat(trs.get("rotation", [0, 0, 0, 1])) * np.array(trs.get("scale", [1, 1, 1]))
    m[:3, 3] = trs.get("translation", [0, 0, 0]); return m

def world(ni, overrides):
    chain = []
    while True:
        chain.append(ni)
        if ni not in parents: break
        ni = parents[ni]
    m = np.eye(4)
    for a in reversed(chain): m = m @ (overrides.get(a, local_from(NODES[a])))
    return m

print("\n### 动画通道构成")
kinds = {}
for a in g["animations"]:
    for ch in a["channels"]: kinds[ch["target"]["path"]] = kinds.get(ch["target"]["path"], 0) + 1
print("   15 段动画的通道 path 计数:", kinds, " 采样数(每通道)示例:", g["animations"][0]["samplers"][0])

# (d) .ani 静态区 +48 三元组 与两种空间的 pelvis 平移 对比
pel = names.index("bip01_pelvis")
ani = np.array([-0.0007, 0.0507, 1.0979])
T90 = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]])     # Rx(+90°): (x,y,z)->(x,-z,y)
Tm90 = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]])    # Rx(-90°): (x,y,z)->(x,z,-y)
print("\n### .ani 静态区 +48 三元组 (%.4f, %.4f, %.4f) 与各空间 pelvis 平移的关系" % (*ani,))
for lbl, t in [("Mraw 平移列(未逆)", Mraw[pel][:3, 3]), ("inv(Mraw) 平移列", W[pel][:3, 3])]:
    for nm, M in [("恒等", np.eye(3)), ("Rx(+90)", T90), ("Rx(-90)", Tm90)]:
        v = M @ t
        print("   %-20s %s -> (%7.4f %7.4f %7.4f)  与 .ani 差 |Δ|=%.5f 逐分量=%s" % (
            lbl, nm, *v, float(np.linalg.norm(v - ani)), np.round(v - ani, 5).tolist()))

print("\n### 撕裂复现")
displ_all = []; rigid_dev = []
S_rest = np.stack([world(JOINTS[j], {}) @ Mraw[j] for j in range(NJ)])
print("   静置自检 W_j(rest)·IBM_j 应=单位阵: 最大元素偏差 = %.2e" % np.abs(S_rest - np.eye(4)).max())
for ai, a in enumerate(g["animations"]):
    chmap = {}
    for ch in a["channels"]:
        chmap.setdefault(ch["target"]["node"], {})[ch["target"]["path"]] = ch["sampler"]
    times = {}
    def samp(si, path):
        s = a["samplers"][si]
        t = acc(g, BIN, s["input"]); out = acc(g, BIN, s["output"])
        return t, out
    for fr in range(21):
        overrides = {}
        for ni, paths in chmap.items():
            cur = dict(NODES[ni])
            for p, si in paths.items():
                s = a["samplers"][si]
                T = acc(g, BIN, s["input"]); O = acc(g, BIN, s["output"])
                k = min(fr, len(T)-1)
                if p == "rotation": cur["rotation"] = O[k]
                elif p == "translation": cur["translation"] = O[k]
                else: cur["scale"] = O[k]
            overrides[ni] = local_from(cur)
        S = np.stack([world(JOINTS[j], overrides) @ Mraw[j] for j in range(NJ)])
        disp = np.zeros_like(POS)
        for slot in range(4):
            idx = JOI[:, slot].astype(int); wq = WEI[:, slot]
            p = np.einsum("nij,nj->ni", S[idx, :3, :3], POS) + S[idx, :3, 3]
            disp += wq[:, None] * p
        d = np.linalg.norm(disp - POS, axis=1)
        displ_all.append(d)
        O = S[:, :3, 3]
        for k in range(NJ):
            j = jpar[k]
            if j >= 0 and np.linalg.norm(O[k]-O[j]) > 1e-4:
                rigid_dev.append((names[j], names[k], float(np.linalg.norm(O[k]-O[j]))))
        if ai == 0 and fr in (0, 10, 20):
            print("   [%s frame %2d] mean位移=%.4f max位移=%.4f  S_j 平移列最大=%.3f  S_j 非正交偏差=%.2e" % (
                a["name"], fr, d.mean(), d.max(), np.abs(S[:, :3, 3]).max(),
                max(np.abs(S[j, :3, :3].T@S[j, :3, :3]-np.eye(3)).max() for j in range(NJ))))
if displ_all:
    A = np.concatenate([x for x in displ_all])
    print("   全部 %d 段 × 21 帧: 顶点位移 mean=%.4f  median=%.4f  p95=%.4f  max=%.4f (按权重折算)" % (
        len(g["animations"]), A.mean(), np.median(A), np.percentile(A, 95), A.max()))
by = {}
for p, c, L in rigid_dev: by.setdefault((p, c), []).append(L)
if by:
    devs = [(k[0], k[1], float(np.ptp(v)), float(np.mean(v))) for k, v in by.items()]
    devs.sort(reverse=True)
    print("   父子骨世界原点距离跨帧变化 (刚体骨架应≈0): top5 %s" % [(d[0][:12], d[1][:14], round(d[2], 3)) for d in devs[:5]])
    print("   平均骨长 vs 平均跨帧变化: %.3f / %.3f" % (np.mean([d[3] for d in devs]), np.mean([d[2] for d in devs])))

# 动画 translation key 的分量分布：判断动画落在哪个空间
print("\n### 动画 translation key 的各分量范围 (取 3 段动画)")
for a in g["animations"][:3]:
    trs = [ch for ch in a["channels"] if ch["target"]["path"] == "translation"]
    if not trs: continue
    vals = np.concatenate([acc(g, BIN, a["samplers"][ch["sampler"]]["output"]) for ch in trs[:6]])
    nms = [NODES[ch["target"]["node"]]["name"] for ch in trs[:6]]
    print("   %-12s %d 条 translation 通道; 样本骨 %s" % (a["name"], len(trs), nms[:3]))
    print("      x %.3f..%.3f  y %.3f..%.3f  z %.3f..%.3f" % (vals[:,0].min(), vals[:,0].max(), vals[:,1].min(), vals[:,1].max(), vals[:,2].min(), vals[:,2].max()))
