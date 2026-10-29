"""决定性实验：全局 R 之外是否还有一层「逐骨轴向」？
模型：local_correct = C_j^{-1} L_ani C_j ，C_j = R_best · A_j，A_j 取 48 个带符号置换之一。
拟合只用 frame0（对 bind 局部旋转取角差最小），随后用 frame1..40 做样本外验证。
若每骨轴向是常数（跨帧不变）-> 样本外残差应当同样小；若是姿态差异 -> 样本外立刻炸。
"""
import numpy as np, sys, math, itertools, collections
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, quat_mat

ANIM = sys.argv[1] if len(sys.argv) > 1 else "idle01"
PM, SG = eval(sys.argv[2]) if len(sys.argv) > 2 else ((2, 0, 1), (1.0, 1.0, 1.0))
TV = int(sys.argv[3]) if len(sys.argv) > 3 else 1
D = build(); NJ = D["NJ"]; names = D["names"]
per = read_anims(D)[ANIM]; NF = len(per[sorted(per)[0]]["translation"][1])
use = (~D["root_only"]) & (D["wsum"] > 0.999)
POS = D["POS"][use]; W = D["Wm"][use]; JSL = D["JOI"][use]; WAL = D["WEI"][use]
NV = len(POS); HOM = np.concatenate([POS, np.ones((NV, 1))], axis=1)
jsum = W.sum(0); covj = np.where(jsum > 1e-9)[0]; covj = covj[covj != 0]
R = np.zeros((3, 3))
for i in range(3): R[i, PM[i]] = SG[i]

Mani = np.tile(np.eye(3), (NJ, NF, 1, 1)); Tani = np.zeros((NJ, NF, 3)); has = np.zeros(NJ, bool)
for j, d in per.items():
    has[j] = True; Tani[j] = d["translation"][1][:NF]
    Mani[j] = np.stack([quat_mat(q) for q in d["rotation"][1][:NF]])
for j in range(NJ):
    if not has[j]:
        Mani[j] = D["blocal"][j][:3, :3]; Tani[j] = D["blocal"][j][:3, 3]
Mb = D["blocal"][:, :3, :3]; Tb = D["blocal"][:, :3, 3]

AX = []
for pm in itertools.permutations(range(3)):
    for sg in itertools.product((1.0, -1.0), repeat=3):
        A = np.zeros((3, 3))
        for i in range(3): A[i, pm[i]] = sg[i]
        AX.append((A, pm, tuple(int(x) for x in sg)))


def ang(E):
    return math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(E) - 1) / 2))))


print("=== 逐骨 frame0 拟合 A_j（48 候选里角差最小）===")
print("%-26s %8s %8s  %s" % ("bone", "只R", "R+A", "A_j"))
bestA = {}; resid1 = []; resid2 = []
for j in range(NJ):
    if not has[j]:
        bestA[j] = np.eye(3); continue
    r0 = ang((R.T @ Mani[j, 0] @ R) @ Mb[j].T)
    cands = []
    for A, pm, sg in AX:
        C = R @ A
        cands.append((ang((C.T @ Mani[j, 0] @ C) @ Mb[j].T), A, pm, sg))
    cands.sort(key=lambda x: x[0])
    a1, A, pm, sg = cands[0]
    bestA[j] = A
    resid1.append(r0); resid2.append(a1)
    tie = [c for c in cands if c[0] < 1e-6]
    print("%-26s %8.2f %8.2f  %s%s%s" % (names[j] + ("*" if j in covj else " "), r0, a1, (pm, sg),
          "  (%d 个并列)" % len(tie) if len(tie) > 1 else "",
          "  par=%s" % (names[D["jpar"][j]] if D["jpar"][j] >= 0 else "-")))
print("  frame0 局部角差：只全局 R mean %.2f med %.2f -> 加逐骨 A mean %.2f med %.2f" %
      (np.mean(resid1), np.median(resid1), np.mean(resid2), np.median(resid2)))
cnt = collections.Counter(tuple(bestA[j].round(3).flatten()) for j in bestA if has[j])
print("  A_j 分布（是否真的『每骨一个常数轴变换』）: %d 种不同取值 / %d 根有通道骨" % (len(cnt), sum(1 for j in bestA if has[j])))
for k, v in cnt.most_common(6): print("    %3d 根共用同一 A_j" % v)

seq, done = [], set()
while len(seq) < NJ:
    for j in range(NJ):
        p = D["jpar"][j]
        if j not in done and (p < 0 or p in done): seq.append(j); done.add(j); break
IBM = D["IBM"]


def skin(Cj, tv):
    Lin = np.einsum('jab,jbc,jcd->jad', [Cj[j].T for j in range(NJ)], Mani, Cj) if False else \
        np.stack([Cj[j].T @ Mani[j] @ Cj[j] for j in range(NJ)])
    T = np.stack([(Cj[j] @ Tani[j].T).T if tv == 1 else (Cj[j].T @ Tani[j].T).T for j in range(NJ)])  # tv1: t'=C t ; tv2: t'=C^T t
    A = np.zeros((NJ, NF, 4, 4)); A[:, :, :3, :3] = Lin; A[:, :, :3, 3] = T; A[:, :, 3, 3] = 1.0
    G = np.empty_like(A)
    for j in seq:
        p = D["jpar"][j]
        G[j] = A[j] if p < 0 else np.matmul(G[p], A[j])
    P = np.stack([G[j] @ IBM[j] for j in range(NJ)])
    Vp = np.zeros((NV, NF, 3))
    for s in range(4):
        Vp += WAL[:, s][:, None, None] * np.einsum('vfij,vj->vfi', P[JSL[:, s]], HOM)[:, :, :3]
    disp = np.linalg.norm(Vp - POS[:, None, :], axis=2)
    cent = np.einsum('vj,vfm->jfm', W, Vp) / np.maximum(jsum, 1e-12)[:, None, None]
    d2 = np.linalg.norm(cent - G[:, :, :3, 3], axis=2)
    return disp, float(d2[covj].mean()), G


Cg = [R] * NJ
Cp = [R @ bestA[j] for j in range(NJ)]
for nm, Cj in (("全局 R only", Cg), ("全局 R + 逐骨 A_j", Cp)):
    for tv in (1, 2):
        disp, m2, G = skin(Cj, tv)
        fm = disp.mean(0)
        print("\n[%s tv=%d] 帧均值 %.4f~%.4f 全局max %.4f | f0 %.4f | f1..40 %.4f~%.4f | m2 %.4f" %
              (nm, tv, fm.min(), fm.max(), disp.max(), fm[0], fm[1:].min(), fm[1:].max(), m2))
        lo = [ang((Cj[j].T @ Mani[j, f] @ Cj[j]) @ Mb[j].T) for j in per for f in range(1, NF)]
        f0 = [ang((Cj[j].T @ Mani[j, 0] @ Cj[j]) @ Mb[j].T) for j in per]
        print("      样本外 frame1..40 逐骨局部角差 mean %.2f med %.2f max %.2f | frame0 时 mean %.2f" %
              (np.mean(lo), np.median(lo), max(lo), np.mean(f0)))
        if tv == 1 and nm.startswith("全局 R +"):
            print("\n      逐骨 frame0 平移：C t vs bind|tb| 与 C^T t vs tb 谁更贴")
            for variant, fn in (("C t", lambda C, t: t @ C.T), ("C^T t", lambda C, t: t @ C)):
                d = [float(np.linalg.norm(fn(Cj[j], Tani[j, 0]) - Tb[j])) for j in per]
                print("        %-6s mean %.4f med %.4f max %.4f" % (variant, np.mean(d), np.median(d), max(d)))
            blen = [(float(np.linalg.norm(Tani[j, 0])), float(np.linalg.norm(Tb[j])), names[j]) for j in per]
            mismatch = [b for b in blen if b[1] > 1e-6 and abs(b[0] / b[1] - 1) > 0.02]
            zero_b = [b for b in blen if b[1] < 1e-6 and b[0] > 1e-4]
            print("        模长对不上(bind非零) %d 根；bind塌缩为0但 .ani 有偏移 %d 根" % (len(mismatch), len(zero_b)))
            print("        塌缩骨: " + ", ".join("%s(%.3f)" % (b[2], b[0]) for b in zero_b))
