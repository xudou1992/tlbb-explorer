"""第二层穷举：在题面假设（全局 R 共轭）之外，再叠两个正交的自由度，看误差还剩哪一层。
维度：R(48 带符号置换) x tv(平移取法 2) x inv(局部先求逆? 2) x comp(复合方向 2) = 384 组合。
  inv=0 : A_j = R^{-1} L_j R                （题面假设）
  inv=1 : A_j = R^{-1} L_j^{-1} R           （.ani 存的是 parent->bone 而非 bone->parent）
  comp=fw: G_j = G_parent @ A_j              （引擎口径 world = local·parent_world）
  comp=bw: G_j = A_j @ G_parent              （复合方向写反的情形）
指标同 sweep.py。
"""
import numpy as np, sys, itertools, json
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, quat_mat, affine_inv4

ANIM = sys.argv[1] if len(sys.argv) > 1 else "idle01"
OUT = r"D:\TLGL\.scratch\ani_axis\sweep2_%s.json" % ANIM
D = build(); NJ = D["NJ"]; names = D["names"]
per = read_anims(D)[ANIM]
NF = len(per[sorted(per)[0]]["translation"][1])
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
# inv=1 用的逆局部
LIrot = np.transpose(Lrot, (0, 1, 3, 2))
LItr = -np.einsum('jfab,jfb->jfa', LIrot, Ltr)
seq, done = [], set()
while len(seq) < NJ:
    for j in range(NJ):
        p = D["jpar"][j]
        if j not in done and (p < 0 or p in done): seq.append(j); done.add(j); break
IBM = D["IBM"]


def evaluate(R, tv, inv, comp):
    Rt = R.T
    rot, tr = (LIrot, LItr) if inv else (Lrot, Ltr)
    Lin = np.matmul(np.matmul(Rt, rot), R)
    T = Ltr * 0 + (tr @ Rt if tv == 1 else tr @ R)
    A = np.zeros((NJ, NF, 4, 4)); A[:, :, :3, :3] = Lin; A[:, :, :3, 3] = T; A[:, :, 3, 3] = 1.0
    G = np.empty_like(A)
    for j in seq:
        p = D["jpar"][j]
        if p < 0: G[j] = A[j]
        else: G[j] = np.matmul(G[p], A[j]) if comp == 'fw' else np.matmul(A[j], G[p])
    P = np.stack([G[j] @ IBM[j] for j in range(NJ)])
    Vp = np.zeros((NV, NF, 3))
    for s in range(4):
        Vp += WAL[:, s][:, None, None] * np.einsum('vfij,vj->vfi', P[JSL[:, s]], HOM)[:, :, :3]
    disp = np.linalg.norm(Vp - POS[:, None, :], axis=2)
    fm = disp.mean(0)
    cent = np.einsum('vj,vfm->jfm', W, Vp) / np.maximum(jsum, 1e-12)[:, None, None]
    d2 = np.linalg.norm(cent - G[:, :, :3, 3], axis=2)
    return dict(fm_min=float(fm.min()), fm_max=float(fm.max()), gmax=float(disp.max()),
                m2=float(d2[covj].mean()), m2_max=float(d2[covj].max()),
                m2_f0=float(d2[covj, 0].mean()), fm_f0=float(fm[0]))


res = []
for pm in itertools.permutations(range(3)):
    for sg in itertools.product((1.0, -1.0), repeat=3):
        R = np.zeros((3, 3))
        for i in range(3): R[i, pm[i]] = sg[i]
        det = float(np.linalg.det(R))
        for tv in (1, 2):
            for inv in (0, 1):
                for comp in ('fw', 'bw'):
                    m = evaluate(R, tv, inv, comp)
                    m.update(perm=pm, signs=list(sg), det=det, tv=tv, inv=inv, comp=comp)
                    res.append(m)

base = [r for r in res if r["det"] == 1 and r["perm"] == (0, 1, 2) and all(s > 0 for s in r["signs"])
        and r["inv"] == 0 and r["comp"] == 'fw']
print("=== 基线 R=I inv=0 comp=fw：帧均值 %.4f~%.4f 全局max %.4f | m2 %.4f ===" %
      (base[0]["fm_min"], base[0]["fm_max"], base[0]["gmax"], base[0]["m2"]))
res.sort(key=lambda r: (r["fm_max"], r["m2"]))
print("\n=== 384 组合按 fm_max 前 15 ===")
print("%-16s %-5s %-4s %-4s %-5s %8s %8s %8s %8s %8s %8s" %
      ("perm/signs", "det", "tv", "inv", "comp", "fm_min", "fm_max", "gmax", "m2", "m2_f0", "f0位移"))
for i, r in enumerate(res[:15]):
    print("%-16s %-5.0f %-4d %-4d %-5s %8.4f %8.4f %8.4f %8.4f %8.4f %8.4f" %
          ("%s%s" % (r["perm"], tuple(int(x) for x in r["signs"])), r["det"], r["tv"], r["inv"],
           r["comp"], r["fm_min"], r["fm_max"], r["gmax"], r["m2"], r["m2_f0"], r["fm_f0"]))
print("\n=== 只看题面那一档（inv=0 comp=fw）前 6 ===")
sub = [r for r in res if r["inv"] == 0 and r["comp"] == 'fw']
for r in sub[:6]:
    print("  %-16s det%-4.0f tv%d  fm %.4f~%.4f gmax %.4f | m2 %.4f m2_max %.4f" %
          ("%s%s" % (r["perm"], tuple(int(x) for x in r["signs"])), r["det"], r["tv"],
           r["fm_min"], r["fm_max"], r["gmax"], r["m2"], r["m2_max"]))
print("\n=== 按 m2（重心贴骨位）最优前 8（全 384）===")
for r in sorted(res, key=lambda x: x["m2"])[:8]:
    print("  %-16s det%-4.0f tv%d inv%d comp%-3s fm_max %.4f gmax %.4f | m2 %.4f m2_max %.4f f0位移 %.4f" %
          ("%s%s" % (r["perm"], tuple(int(x) for x in r["signs"])), r["det"], r["tv"], r["inv"],
           r["comp"], r["fm_max"], r["gmax"], r["m2"], r["m2_max"], r["fm_f0"]))
q = [r["fm_max"] for r in res]
print("\nfm_max 分位: min %.4f p10 %.4f med %.4f max %.4f (n=%d)" %
      (min(q), np.percentile(q, 10), np.median(q), max(q), len(q)))
print("m2  分位: min %.4f med %.4f max %.4f  (静置参照 0.1488, 基线 0.2226)" %
      (min(r["m2"] for r in res), np.median([r["m2"] for r in res]), max(r["m2"] for r in res)))
json.dump(res, open(OUT, "w"), default=str)
print("saved ->", OUT)
