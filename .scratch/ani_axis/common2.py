"""本班（2026-10-07）共用层：新文件，不改动上一班任何产物。

语义沿 common.py（GLB 列向量口径）：
  IBM = B^{-1}（= .mesh 96B 记录存的「世界绑定矩阵的逆」S）；
  node 静态 TRS 沿树复合 = bind 世界 B；蒙皮 M_j(f) = G_j(f) @ anchor_j。
新增：
  * 任意路径装载 build(path)（common.build 写死了路径）；
  * 动画局部轨道 -> frame0 世界 / 全帧世界（干净共轭版：G' = Q^T G Q，见 conj）；
  * 静态加权重心 C_j（0.1488 判据的参照量）、蒙皮位移、逐帧重心残差。
R 共轭的两种口径都给：
  * conj_clean(G, Q)   : 对已复合的原始世界矩阵直接共轭，世界平移 t -> Q^T t（干净、可解释）；
  * conj_sweep2(Lrot, Ltr, Q): 上一班 sweep2/reanchor 的 tv=1 约定（Lin=Q^T L Q, T=Ltr@Q^T），
    用于和上一班数字对表。
"""
import sys, math, json
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import load_glb, read_acc, quat_mat, trs_mat, affine_inv4  # noqa: E402

GLBS = {
    "yifu":    r"D:\TLGL\.scratch\glb_rigged\m_db18794d0000cd38.glb",
    "shoutao": r"D:\TLGL\.scratch\glb_rigged\m_8ff895cd00003a5c.glb",
}


def build(path):
    g, BIN = load_glb(path)
    prim = g["meshes"][0]["primitives"][0]
    POS = read_acc(g, BIN, prim["attributes"]["POSITION"])
    JOI = read_acc(g, BIN, prim["attributes"]["JOINTS_0"]).astype(int)
    WEI = read_acc(g, BIN, prim["attributes"]["WEIGHTS_0"])
    NODES = g["nodes"]; JOINTS = g["skins"][0]["joints"]; NJ = len(JOINTS)
    IBM = read_acc(g, BIN, g["skins"][0]["inverseBindMatrices"]).reshape(NJ, 4, 4, order="F")
    names = [NODES[ni]["name"] for ni in JOINTS]
    jof = {ni: j for j, ni in enumerate(JOINTS)}
    par = {}
    for ni, n in enumerate(NODES):
        for c in n.get("children", []):
            par[c] = ni
    jpar = [jof.get(par.get(ni, -1), -1) for ni in JOINTS]
    blocal = np.stack([trs_mat(NODES[ni].get("translation", [0, 0, 0]),
                               NODES[ni].get("rotation", [0, 0, 0, 1]),
                               NODES[ni].get("scale", [1, 1, 1])) for ni in JOINTS])
    B = np.zeros_like(blocal)
    todo = set(range(NJ))
    for _ in range(NJ + 2):
        for j in list(todo):
            p = jpar[j]
            if p < 0:
                B[j] = blocal[j]; todo.discard(j)
            elif p not in todo:
                B[j] = B[p] @ blocal[j]; todo.discard(j)
    Binv = np.stack([affine_inv4(B[j]) for j in range(NJ)])
    Wm = np.zeros((len(POS), NJ))
    for s in range(4):
        np.add.at(Wm, (np.arange(len(POS)), JOI[:, s]), WEI[:, s])
    mx = Wm.max(1); amax = Wm.argmax(1); wsum = Wm.sum(1)
    root_only = (mx > 0.999) & (amax == 0) & (wsum > 0.999)
    # 静态加权重心 C_j（bind 姿态网格顶点，网格轴）——verify.py 的 0.1488 判据
    C = np.zeros((NJ, 3)); cov = np.zeros(NJ, bool)
    for j in range(NJ):
        w = Wm[:, j]; s = w.sum()
        if s > 1e-9:
            C[j] = (POS[w > 0] * w[w > 0, None]).sum(0) / s
            cov[j] = True
    # 复合顺序（拓扑）
    seq, done = [], set()
    while len(seq) < NJ:
        for j in range(NJ):
            p = jpar[j]
            if j not in done and (p < 0 or p in done):
                seq.append(j); done.add(j); break
    return dict(g=g, BIN=BIN, POS=POS, JOI=JOI, WEI=WEI, NODES=NODES, JOINTS=JOINTS, NJ=NJ,
                names=names, jpar=jpar, blocal=blocal, B=B, IBM=IBM, Binv=Binv, Wm=Wm,
                root_only=root_only, wsum=wsum, par=par, jof=jof, C=C, cov=cov, seq=seq)


def ang(M):
    """旋转矩阵的转角（度）。"""
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(M) - 1) / 2))))


def perm_R(pm, sg):
    R = np.zeros((3, 3))
    for i in range(3):
        R[i, pm[i]] = sg[i]
    return R


def locals_frame0(per, D):
    """某条动画第 0 帧的局部 (Lrot0 NJx3x3, Ltr0 NJx3, has NJbool)。无通道骨用 blocal。"""
    NJ = D["NJ"]
    Lrot0 = np.stack([D["blocal"][j][:3, :3] for j in range(NJ)])
    Ltr0 = np.stack([D["blocal"][j][:3, 3] for j in range(NJ)])
    has = np.zeros(NJ, bool)
    for j, d in per.items():
        if "translation" in d and "rotation" in d:
            has[j] = True
            Ltr0[j] = d["translation"][1][0]
            Lrot0[j] = quat_mat(d["rotation"][1][0])
    return Lrot0, Ltr0, has


def locals_frames(per, D, NF):
    """某条动画全帧局部 (Lrot NJxNFx3x3, Ltr NJxNFx3, has NJbool)。无通道骨用 blocal。"""
    NJ = D["NJ"]
    Lrot = np.tile(np.eye(3), (NJ, NF, 1, 1))
    Ltr = np.tile(D["blocal"][None, :, :3, 3], (NF, 1, 1)).transpose(1, 0, 2)
    has = np.zeros(NJ, bool)
    for j, d in per.items():
        if "translation" in d and "rotation" in d:
            has[j] = True
            Ltr[j] = d["translation"][1][:NF]
            Lrot[j] = np.stack([quat_mat(q) for q in d["rotation"][1][:NF]])
    return Lrot, Ltr, has


def compose_worlds(Lrot, Ltr, D):
    """列向量口径 world = parent @ local。Lrot (J,...,3,3), Ltr (J,...,3)。"""
    NJ = D["NJ"]
    sh = () if Ltr.ndim == 2 else Ltr.shape[1:-1]
    A = np.zeros((NJ,) + sh + (4, 4))
    A[..., :3, :3] = Lrot
    A[..., :3, 3] = Ltr
    A[..., 3, 3] = 1.0
    G = np.empty_like(A)
    for j in D["seq"]:
        p = D["jpar"][j]
        G[j] = A[j] if p < 0 else G[p] @ A[j]
    return G


def conj_clean(G, Q):
    """对复合好的世界矩阵做干净共轭：G' = C^T G C，C=blkdiag(Q,1) => 世界平移 t -> Q^T t。"""
    C = np.eye(4); C[:3, :3] = Q
    Ct = C.T
    return Ct @ G @ C


def conj_sweep2(Lrot, Ltr, Q, D):
    """上一班 sweep2/reanchor 的 tv=1 约定：Lin = Q^T L Q，T = Ltr @ Q^T，world = parent@A。
    Lrot (J,F,3,3)+Ltr (J,F,3) -> G (J,F,4,4)；Lrot (J,3,3)+Ltr (J,3) -> G (J,4,4)。"""
    Qt = Q.T
    full = Lrot.ndim == 4
    NJ = D["NJ"]
    if full:
        Lin = np.matmul(np.matmul(Qt[None, None], Lrot), Q[None, None])
        T = Ltr @ Qt
        A = np.zeros((NJ, Ltr.shape[1], 4, 4))
        A[:, :, :3, :3] = Lin
        A[:, :, :3, 3] = T
    else:
        Lin = Qt @ Lrot @ Q
        T = (Ltr[None, :] @ Qt)[0]
        A = np.zeros((NJ, 4, 4))
        A[:, :3, :3] = Lin
        A[:, :3, 3] = T
    A[..., 3, 3] = 1.0
    G = np.empty_like(A)
    for j in D["seq"]:
        p = D["jpar"][j]
        G[j] = A[j] if p < 0 else G[p] @ A[j]
    return G


def skin(G, anchor, D):
    """蒙皮。G (J,F,4,4) 或 (J,4,4)；anchor (J,4,4)。返回 Vp (NV,F,3)（F=1 时 (NV,1,3)）。"""
    if G.ndim == 4:
        P = np.einsum('jfac,jcb->fjab', G, anchor)
    else:
        P = np.einsum('jac,jcb->jab', G, anchor)[None]
    JOI, WEI, POS = D["JOI"], D["WEI"], D["POS"]
    NV = len(POS)
    HOM = np.concatenate([POS, np.ones((NV, 1))], axis=1)
    Vp = np.zeros((NV, P.shape[0], 3))
    for s in range(4):
        PM = P[:, JOI[:, s]]  # (F,NV,4,4)
        Vp += WEI[:, s][:, None, None] * np.einsum('fvkl,vk->vfl', PM, HOM)[..., :3]
    return Vp


def centroid_resid(G, Vp, D):
    """逐骨逐帧 |蒙皮加权重心 - 骨世界位|。返回 d2 (J,F)。"""
    W = D["Wm"]; jsum = W.sum(0)
    cent = np.einsum('vj,vfm->jfm', W, Vp) / np.maximum(jsum, 1e-12)[:, None, None]
    if G.ndim == 4:
        gt = G[:, :, :3, 3]          # (J,F,3)
    else:
        gt = G[None, :, :3, 3].transpose(2, 1, 0)  # (J,1,3)
    return np.linalg.norm(cent - gt, axis=2)
