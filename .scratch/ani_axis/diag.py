"""残差形状诊断：对最优候选，看剩下那 ~0.5 的位移错在哪一层。
A) 逐骨 frame0 局部残差（共轭后的 ani 局部 vs bind 局部）：旋转角 / 平移差
B) 累积世界残差角（G_j(0) vs B_j）——判断误差是「某条子链继承」还是「每骨独立」
C) 顶点位移按主导骨分组：哪些骨的顶点被撕得最狠
D) 骨架刚性：|G_j(f)-G_par(f)| 跨帧是否恒定（恒定=骨长没被拉断，误差在别处）
E) 位移场里能被「单一全局刚体」解释的比例（余量小 => 只是整体偏移，不是局部错）
"""
import numpy as np, sys, math
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, quat_mat

ANIM = sys.argv[1] if len(sys.argv) > 1 else "idle01"
CAND = eval(sys.argv[2]) if len(sys.argv) > 2 else [((2, 0, 1), (1.0, 1.0, 1.0), 1)]
D = build(); NJ = D["NJ"]; names = D["names"]
per = read_anims(D)[ANIM]
NF = len(per[sorted(per)[0]]["translation"][1])
use = (~D["root_only"]) & (D["wsum"] > 0.999)
POS = D["POS"][use]; W = D["Wm"][use]; JSL = D["JOI"][use]; WAL = D["WEI"][use]
NV = len(POS); HOM = np.concatenate([POS, np.ones((NV, 1))], axis=1)
jsum = W.sum(0); covj = np.where(jsum > 1e-9)[0]; covj = covj[covj != 0]
dom = W.argmax(1)

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


def rot_angle(M):
    tr = max(-1.0, min(3.0, np.trace(M)))
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1) / 2))))


def run(R, tv):
    Rt = R.T
    Lin = np.matmul(np.matmul(Rt, Lrot), R)
    T = Ltr @ Rt if tv == 1 else (Ltr @ R if tv == 2 else Ltr)
    A = np.zeros((NJ, NF, 4, 4)); A[:, :, :3, :3] = Lin; A[:, :, :3, 3] = T; A[:, :, 3, 3] = 1.0
    G = np.empty_like(A)
    for j in seq:
        p = D["jpar"][j]
        G[j] = A[j] if p < 0 else np.matmul(G[p], A[j])
    P = np.stack([G[j] @ IBM[j] for j in range(NJ)])
    Vp = np.zeros((NV, NF, 3))
    for s in range(4):
        Vp += WAL[:, s][:, None, None] * np.einsum('vfij,vj->vfi', P[JSL[:, s]], HOM)[:, :, :3]
    return A, G, P, Vp


for pm, sg, tv in CAND:
    R = np.zeros((3, 3))
    for i in range(3): R[i, pm[i]] = sg[i]
    A, G, P, Vp = run(R, tv)
    disp = np.linalg.norm(Vp - POS[:, None, :], axis=2)
    print("\n########## R perm=%s signs=%s det=%.0f  tv=%d  (%s) ##########" %
          (pm, tuple(int(x) for x in sg), np.linalg.det(R), tv,
           "t'=R t" if tv == 1 else ("t'=R^T t" if tv == 2 else "t'=t")))
    print("  帧均值 %.4f~%.4f  全局max %.4f  f0 %.4f" % (disp.mean(0).min(), disp.mean(0).max(), disp.max(), disp[:, 0].mean()))
    # A) 逐骨 frame0 局部残差
    print("\n  [A] frame0 局部：共轭后 ani 局部 vs bind 局部（旋转角 / 平移差），按父链缩进")
    print("      %-22s %8s %8s" % ("bone", "ang(deg)", "|dt|"))
    rows = []
    for j in range(NJ):
        E = A[j, 0, :3, :3].T @ D["blocal"][j][:3, :3]
        ang = rot_angle(E); dt = float(np.linalg.norm(A[j, 0, :3, 3] - D["blocal"][j][:3, 3]))
        rows.append((ang, dt, j))
    for ang, dt, j in sorted(rows, reverse=True)[:12]:
        print("      %-22s %8.2f %8.4f  (par=%s)" % (names[j], ang, dt, names[D["jpar"][j]] if D["jpar"][j] >= 0 else "-"))
    print("      全骨 ang: mean %.2f med %.2f max %.2f | 除 bip01 外 mean %.2f" %
          (np.mean([r[0] for r in rows]), np.median([r[0] for r in rows]), max(r[0] for r in rows),
           np.mean([r[0] for r in rows if r[2] != 1])))
    # B) 累积世界残差
    print("\n  [B] 世界残差角 |G_j(0) vs B_j|（看误差是否沿子链累积）")
    wr = []
    for j in range(NJ):
        E = G[j, 0, :3, :3].T @ D["B"][j][:3, :3]
        wr.append((rot_angle(E), float(np.linalg.norm(G[j, 0, :3, 3] - D["B"][j][:3, 3])), j))
    for ang, dt, j in sorted(wr, key=lambda x: -x[0])[:12]:
        print("      %-22s ang %7.2f  |dt| %7.4f  par=%s" % (names[j], ang, dt,
              names[D["jpar"][j]] if D["jpar"][j] >= 0 else "-"))
    print("      world ang mean %.2f med %.2f max %.2f" %
          (np.mean([x[0] for x in wr]), np.median([x[0] for x in wr]), max(x[0] for x in wr)))
    # C) 位移按主导骨
    print("\n  [C] 顶点位移按主导骨分组（41 帧均值），前 10 / 后 5")
    tab = []
    for j in np.unique(dom):
        m = dom == j
        tab.append((float(disp[m].mean()), int(m.sum()), names[j]))
    tab.sort(reverse=True)
    for v, n, nm in tab[:10]: print("      %-24s mean %7.4f  verts %d" % (nm, v, n))
    print("      ...")
    for v, n, nm in tab[-5:]: print("      %-24s mean %7.4f  verts %d" % (nm, v, n))
    # D) 骨长跨帧刚性
    print("\n  [D] 父子骨世界原点距离：bind 值 vs 动画 min~max（恒定=骨长没被拉断）")
    bad = []
    for j in range(NJ):
        p = D["jpar"][j]
        if p < 0 or j == 0: continue
        lb = float(np.linalg.norm(D["B"][j][:3, 3] - D["B"][p][:3, 3]))
        if lb < 1e-6: continue
        la = np.linalg.norm(G[j, :, :3, 3] - G[p, :, :3, 3], axis=1)
        bad.append((abs(la.max() - la.min()) / lb, names[j], lb, la.min(), la.max(), float(la.mean())))
    bad.sort(reverse=True)
    for r, nm, lb, mn, mx, mean in bad[:8]:
        print("      %-22s bind %.4f  ani %.4f~%.4f (mean %.4f)  波动 %.3f" % (nm, lb, mn, mx, mean, r))
    print("      波动>10%% 的骨数 %d / %d" % (sum(1 for b in bad if b[0] > 0.1), len(bad)))
    # E) 位移场可被全局刚体解释的比例
    print("\n  [E] 位移场 vs 最优全局刚体（Umeyama 无缩放）残差")
    tot = Vp - POS[:, None, :]
    for f in (0, NF // 2, NF - 1):
        tgt = POS + tot[:, f]
        c0 = POS.mean(0); c1 = tgt.mean(0)
        A0 = POS - c0; A1 = tgt - c1
        U, S, Vt = np.linalg.svd(A0.T @ A1)
        ds = np.sign(np.linalg.det(Vt.T @ U.T))
        Rg = Vt.T @ np.diag([1, 1, ds]) @ U.T
        rr = np.linalg.norm(tgt - (A0 @ Rg.T + c1), axis=1)
        print("      f=%2d  位移 RMS %.4f -> 去掉最优全局刚体后残差 RMS %.4f  (刚体解释 %.1f%%)" %
              (f, float(np.sqrt((tot[:, f] ** 2).sum(1).mean())), float(np.sqrt((rr ** 2).mean())),
               100 * (1 - float(np.sqrt((rr ** 2).mean())) / max(float(np.sqrt((tot[:, f] ** 2).sum(1).mean())), 1e-12))))
