"""穷举判定：.ani 逐骨局部 TRS 是否与 bind/网格空间差一个全局定轴（带符号置换）旋转 R。
扫描：48 个带符号置换矩阵（= 题面 24 真旋转 + 24 镜像，全扫不挑）× 平移 2 种取法 = 96 组合。
段：命令行给定动画（默认 idle01，41 帧）。
指标：① 蒙皮位移（帧均值 min/max + 全局 max）② 变形后重心 vs 该骨位姿原点 ③ frame0 是否近静置。
"""
import numpy as np, sys, itertools, json
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, quat_mat

ANIM = sys.argv[1] if len(sys.argv) > 1 else "idle01"
OUT = sys.argv[2] if len(sys.argv) > 2 else r"D:\TLGL\.scratch\ani_axis\sweep_%s.json" % ANIM

D = build(); NJ = D["NJ"]; names = D["names"]
per = read_anims(D)[ANIM]
NF = len(per[sorted(per)[0]]["translation"][1])

use = (~D["root_only"]) & (D["wsum"] > 0.999)
POS = D["POS"][use]; W = D["Wm"][use]
JSL = D["JOI"][use]; WAL = D["WEI"][use]; NV = len(POS)
HOM = np.concatenate([POS, np.ones((NV, 1))], axis=1)
jsum = W.sum(0); covj = np.where(jsum > 1e-9)[0]
covj = covj[covj != 0]                       # 根骨不参与重心指标

# 动画局部拆成 旋转3x3 + 平移3（scale 实测恒为 1，见 verify 输出）
Lrot = np.tile(np.eye(3), (NJ, NF, 1, 1)); Ltr = np.zeros((NJ, NF, 3)); has = np.zeros(NJ, bool)
for j, d in per.items():
    has[j] = True
    Ltr[j] = d["translation"][1][:NF]
    Lrot[j] = np.stack([quat_mat(q) for q in d["rotation"][1][:NF]])
for j in range(NJ):
    if not has[j]:
        Lrot[j] = D["blocal"][j][:3, :3]; Ltr[j] = D["blocal"][j][:3, 3]

seq, done = [], set()
while len(seq) < NJ:
    for j in range(NJ):
        p = D["jpar"][j]
        if j not in done and (p < 0 or p in done):
            seq.append(j); done.add(j); break
IBM = D["IBM"]


def evaluate(R, tv):
    Rt = R.T
    Lin = np.matmul(np.matmul(Rt, Lrot), R)          # R^{-1} M R, 广播到 (NJ,NF,3,3)
    T = Ltr @ Rt if tv == 1 else Ltr @ R             # tv1: t'=R t   tv2: t'=R^T t (=题面 t·R)
    A = np.zeros((NJ, NF, 4, 4)); A[:, :, :3, :3] = Lin; A[:, :, :3, 3] = T; A[:, :, 3, 3] = 1.0
    G = np.empty_like(A)
    for j in seq:
        p = D["jpar"][j]
        G[j] = A[j] if p < 0 else np.matmul(G[p], A[j])
    P = np.stack([G[j] @ IBM[j] for j in range(NJ)])
    Vp = np.zeros((NV, NF, 3))
    for s in range(4):
        Vp += WAL[:, s][:, None, None] * np.einsum('vfij,vj->vfi', P[JSL[:, s]], HOM)[:, :, :3]
    disp = np.linalg.norm(Vp - POS[:, None, :], axis=2)          # (NV,NF)
    fm = disp.mean(0)
    cent = np.einsum('vj,vfm->jfm', W, Vp) / np.maximum(jsum, 1e-12)[:, None, None]
    d2 = np.linalg.norm(cent - G[:, :, :3, 3], axis=2)           # (NJ,NF)
    return dict(P=P, G=G, Vp=Vp, disp=disp, fm=fm, d2=d2,
                fm_min=float(fm.min()), fm_max=float(fm.max()), gmax=float(disp.max()),
                m2=float(d2[covj].mean()), m2_max=float(d2[covj].max()),
                m2_f0=float(d2[covj, 0].mean()), fm_f0=float(fm[0]))


RS = []
for pm in itertools.permutations(range(3)):
    for sg in itertools.product((1.0, -1.0), repeat=3):
        R = np.zeros((3, 3))
        for i in range(3): R[i, pm[i]] = sg[i]
        RS.append((R, pm, sg, float(np.linalg.det(R))))


def euler_xyz(R):
    sy = max(-1.0, min(1.0, R[0, 2]))
    import math
    if abs(sy) < 0.99999:
        p = math.asin(sy); y = math.atan2(-R[1, 2], R[2, 2]); r = math.atan2(-R[0, 1], R[0, 0])
    else:
        p = math.asin(sy); y = math.atan2(R[2, 1], R[1, 1]); r = 0.0
    return [round(math.degrees(v), 2) for v in (r, y, p)]


res = []
for k, (R, pm, sg, det) in enumerate(RS):
    for tv in (1, 2):
        m = evaluate(R, tv)
        res.append(dict(idx=k, perm=pm, signs=list(sg), det=det, tv=tv,
                        euler=euler_xyz(R) if det > 0 else None,
                        fm_min=m["fm_min"], fm_max=m["fm_max"], gmax=m["gmax"],
                        m2=m["m2"], m2_max=m["m2_max"], m2_f0=m["m2_f0"], fm_f0=m["fm_f0"]))

base = [r for r in res if r["det"] == 1.0 and r["perm"] == (0, 1, 2) and all(s == 1 for s in r["signs"])]
print("=== 基线（R=I，两种平移取法同值）===")
for r in base:
    print("  tv=%d  帧均值 %.4f~%.4f  全局max %.4f  |  重心-骨位 mean %.4f  f0 %.4f  | f0位移 %.4f" %
          (r["tv"], r["fm_min"], r["fm_max"], r["gmax"], r["m2"], r["m2_f0"], r["fm_f0"]))

res.sort(key=lambda r: (r["fm_max"], r["m2"]))
print("\n=== 96 组合按「帧均值上界 fm_max」排序，前 12 ===")
print("%-4s %-16s %-6s %-4s %-16s %8s %8s %8s %8s %8s %8s" %
      ("#", "perm/signs", "det", "tv", "eulerXYZ(deg)", "fm_min", "fm_max", "gmax", "m2", "m2_f0", "f0位移"))
for i, r in enumerate(res[:12]):
    print("%-4d %-16s %-6.0f %-4d %-16s %8.4f %8.4f %8.4f %8.4f %8.4f %8.4f" %
          (i + 1, "%s%s" % (r["perm"], tuple(int(s) for s in r["signs"])), r["det"], r["tv"],
           str(r["euler"]), r["fm_min"], r["fm_max"], r["gmax"], r["m2"], r["m2_f0"], r["fm_f0"]))
print("\n=== 同样 96 组合按「重心-骨位 m2」排序，前 8 ===")
for i, r in enumerate(sorted(res, key=lambda x: x["m2"])[:8]):
    print("%-4d %-16s det%-4.0f tv%-3d %-14s fm_min %.4f fm_max %.4f gmax %.4f | m2 %.4f m2_max %.4f" %
          (i + 1, "%s%s" % (r["perm"], tuple(int(s) for s in r["signs"])), r["det"], r["tv"],
           str(r["euler"]), r["fm_min"], r["fm_max"], r["gmax"], r["m2"], r["m2_max"]))
print("\n=== 最差 3 ===")
for r in res[-3:]:
    print("  %s%s det%.0f tv%d  fm_max %.4f m2 %.4f" % (r["perm"], tuple(int(s) for s in r["signs"]), r["det"], r["tv"], r["fm_max"], r["m2"]))
q = [r["fm_max"] for r in res]
print("\n分位：fm_max min %.4f / p25 %.4f / med %.4f / max %.4f  (n=%d)" %
      (min(q), np.percentile(q, 25), np.percentile(q, 50), max(q), len(q)))
json.dump(dict(anim=ANIM, NF=NF, baseline=base, results=res), open(OUT, "w"), default=str)
print("saved ->", OUT)
