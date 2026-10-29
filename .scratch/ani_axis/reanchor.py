"""剥层实验：把 palette 的锚从 .mesh bind 换成「同一 R 下的 frame0 动画骨架」，
单独回答两个问题：
  Q1 .ani（经 R 变换后）本身是不是一段温和的 idle？（逐骨相对 frame0 的转角 + 重锚后位移）
  Q2 若重锚后位移很小，则现存的 ~0.50 全部来自「.ani 骨架 vs .mesh bind 骨架」不同源，而不是轴系。
对照：R=I（基线）也做同样重锚，看它是不是本身就炸。
"""
import numpy as np, sys, math, itertools
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, quat_mat, affine_inv4

ANIM = sys.argv[1] if len(sys.argv) > 1 else "idle01"
D = build(); NJ = D["NJ"]; names = D["names"]
per = read_anims(D)[ANIM]; NF = len(per[sorted(per)[0]]["translation"][1])
use = (~D["root_only"]) & (D["wsum"] > 0.999)
POS = D["POS"][use]; W = D["Wm"][use]; JSL = D["JOI"][use]; WAL = D["WEI"][use]
NV = len(POS); HOM = np.concatenate([POS, np.ones((NV, 1))], axis=1)
jsum = W.sum(0); covj = np.where(jsum > 1e-9)[0]; covj = covj[covj != 0]
Lrot = np.tile(np.eye(3), (NJ, NF, 1, 1)); Ltr = np.zeros((NJ, NF, 3)); has = np.zeros(NJ, bool)
for j, d in per.items():
    has[j] = True; Ltr[j] = d["translation"][1][:NF]
    Lrot[j] = np.stack([quat_mat(q) for q in d["rotation"][1][:NF]])
for j in range(NJ):
    if not has[j]:
        Lrot[j] = D["blocal"][j][:3, :3]; Ltr[j] = D["blocal"][j][:3, 3]
seq, done = [], set()
while len(seq) < NJ:
    for j in range(NJ):
        p = D["jpar"][j]
        if j not in done and (p < 0 or p in done): seq.append(j); done.add(j); break
IBM = D["IBM"]


def ang(M):
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(M) - 1) / 2))))


def model(R, tv):
    Rt = R.T
    Lin = np.matmul(np.matmul(Rt, Lrot), R)
    T = Ltr @ Rt if tv == 1 else Ltr @ R
    A = np.zeros((NJ, NF, 4, 4)); A[:, :, :3, :3] = Lin; A[:, :, :3, 3] = T; A[:, :, 3, 3] = 1.0
    G = np.empty_like(A)
    for j in seq:
        p = D["jpar"][j]
        G[j] = A[j] if p < 0 else np.matmul(G[p], A[j])
    return G


def skin(G, anchor):
    P = np.stack([G[j] @ anchor[j] for j in range(NJ)])
    Vp = np.zeros((NV, NF, 3))
    for s in range(4):
        Vp += WAL[:, s][:, None, None] * np.einsum('vfij,vj->vfi', P[JSL[:, s]], HOM)[:, :, :3]
    disp = np.linalg.norm(Vp - POS[:, None, :], axis=2)
    cent = np.einsum('vj,vfm->jfm', W, Vp) / np.maximum(jsum, 1e-12)[:, None, None]
    d2 = np.linalg.norm(cent - G[:, :, :3, 3], axis=2)
    fm = disp.mean(0)
    return fm, disp, d2


CANDS = [("基线 R=I", (0, 1, 2), (1.0, 1.0, 1.0)),
         ("最优 #1 (2,0,1)+++", (2, 0, 1), (1.0, 1.0, 1.0)),
         ("次优 #2 (2,0,1)+-+", (2, 0, 1), (-1.0, 1.0, -1.0)),
         ("第三 (1,2,0)---", (1, 2, 0), (-1.0, -1.0, -1.0))]
print("段 %s，%d 帧。列：以 .mesh bind 为锚 / 以 frame0 动画骨架为锚\n" % (ANIM, NF))
print("%-22s %-7s %7s %7s %7s | %7s %7s %7s | %7s %7s" %
      ("候选", "tv", "帧均min", "帧均max", "全max", "帧均min'", "帧均max'", "全max'", "骨动角mean", "骨动角max"))
for nm, pm, sg in CANDS:
    R = np.zeros((3, 3))
    for i in range(3): R[i, pm[i]] = sg[i]
    G = model(R, 1)
    fm0, dsp0, d20 = skin(G, IBM)
    anc = np.stack([affine_inv4(G[j, 0]) for j in range(NJ)])
    fm1, dsp1, d21 = skin(G, anc)
    # 逐骨相对 frame0 的转角（动画内部幅度）
    mo = [ang(G[j, f, :3, :3].T @ G[j, 0, :3, :3]) for j in per for f in range(NF)]
    print("%-22s %-7d %7.4f %7.4f %7.4f | %7.4f %7.4f %7.4f | %7.2f %7.2f" %
          (nm, 1, fm0.min(), fm0.max(), dsp0.max(), fm1.min(), fm1.max(), dsp1.max(),
           np.mean(mo), np.max(mo)))
    print("      重锚后 m2(变形重心 vs 骨位) %.4f ; 原锚 m2 %.4f ; 静置参照 0.1488" % (d21[covj].mean(), d20[covj].mean()))
