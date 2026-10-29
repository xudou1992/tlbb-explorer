"""
probe2.py — 决定性证据：GLB 里的 'IBM' 槽位装的到底是 bone→world 绑定矩阵，还是它的逆？
(1) 逐骨对照表: Mraw 平移列 vs inv(Mraw) 平移列 vs 蒙皮重心
(2) 复现主 agent 的 1.84（不剔除根骨独占顶点、含全部覆盖骨）
(3) 骨轴测试: 真绑定矩阵的某个列向量必须与 '本骨→子骨' 方向平行（Biped 骨沿局部 X）
(4) Mraw 3x3 的正交性/行列式/缩放
"""
import math, json
import numpy as np
import glbcore as G

D = G.build(); NJ = D["NJ"]; names = D["names"]; Mraw = D["Mraw"]; W = D["W"]
tC = np.stack([Mraw[j][:3, 3] for j in range(NJ)])          # 'IBM' 自己的平移列 (C)
tA = W[:, :3, 3]                                            # inv('IBM') 的平移列 (A = 管线用的 bind 世界原点)

Cd, Sd, Nd, cov, ROOT, nused = G.centroids(D, True)
print("剔除根骨独占顶点版: 参与顶点 %d, 根骨 joint %d '%s', 覆盖骨 %d" % (nused, ROOT, names[ROOT], int(cov.sum())))
Cp, Sp, Np, covp, _, nusedp = G.centroids(D, False)
print("未剔除(污染)版: 参与顶点 %d" % nusedp)

fit = np.array([j for j in np.where(cov)[0] if j != ROOT])
print("\n(2) 复现主 agent 的 1.84：")
for lbl, P, Cc, sel in [("A=inv(Mraw) 原点 vs 干净重心", tA, Cd, fit),
                        ("A=inv(Mraw) 原点 vs 污染重心", tA, Cp, fit),
                        ("A vs 污染重心, 全部覆盖骨(含根骨)", tA, Cp, np.where(covp)[0]),
                        ("A vs 干净重心, 全部覆盖骨(含根骨)", tA, Cd, np.where(cov)[0]),
                        ("C=Mraw 平移列 vs 干净重心", tC, Cd, fit),
                        ("C=Mraw 平移列 vs 污染重心", tC, Cp, fit)]:
    d = np.linalg.norm(P[sel] - Cc[sel], axis=1)
    print("   %-46s n=%2d  mean=%.4f median=%.4f max=%.4f" % (lbl, len(sel), d.mean(), np.median(d), d.max()))

print("\n(1) 逐骨表  (单位: GLB 场景空间)")
print("%-2s %-27s %-24s %-24s %-24s %5s %4s" % ("j", "bone", "C=Mraw平移(未逆)", "A=inv(Mraw)平移", "重心 c_j", "sumw", "v"))
for j in list(range(NJ)):
    c = Cd[j] if cov[j] else np.array([np.nan]*3)
    print("%2d %-27s (%7.4f %7.4f %7.4f)  (%7.4f %7.4f %7.4f)  (%7.4f %7.4f %7.4f) %6.1f %4d" % (
        j, names[j], *tC[j], *tA[j], *c, Sd[j], Nd[j]))

# (4) 3x3 块性质
print("\n(4) Mraw 的 3x3：")
for j in range(NJ):
    Rb = Mraw[j, :3, :3]
    odev = np.abs(Rb.T @ Rb - np.eye(3)).max(); det = np.linalg.det(Rb)
    sv = np.linalg.svd(Rb, compute_uv=False)
    if j < 8 or odev > 1e-3:
        print("   %-27s det=%+.4f  正交偏差=%.2e  奇异值=%s" % (names[j], det, odev, np.round(sv, 4).tolist()))
allev = [np.abs(Mraw[j, :3, :3].T @ Mraw[j, :3, :3] - np.eye(3)).max() for j in range(NJ)]
print("   全部骨: 正交偏差 max=%.2e  median=%.2e ; det 集合=%s ; 缩放(奇异值)范围 %.4f..%.4f" % (
    max(allev), float(np.median(allev)), sorted({round(float(np.linalg.det(Mraw[j, :3, :3])), 4) for j in range(NJ)}),
    min(np.linalg.svd(Mraw[j, :3, :3], compute_uv=False).max() for j in range(NJ)),
    max(np.linalg.svd(Mraw[j, :3, :3], compute_uv=False).min() for j in range(NJ))))

# (3) 骨轴测试
def axis_angle(M, v):
    v = v / np.linalg.norm(v)
    angs = []
    for k in range(3):
        col = M[:3, k]; col = col / np.linalg.norm(col)
        angs.append(math.degrees(math.acos(max(-1.0, min(1.0, float(col @ v))))))
        angs[-1] = min(angs[-1], 180 - angs[-1])   # 允许反向
    return min(angs), angs

pairs = []
for k in range(NJ):
    j = D["jpar"][k]
    if j < 0 or not (cov[j] and cov[k]) or j == ROOT or k == ROOT: continue
    dv = Cd[k] - Cd[j]; nv = float(np.linalg.norm(dv))     # '父->子' 的独立观测(重心差)
    if nv < 1e-3: continue
    a_raw = min(axis_angle(Mraw[k], dv)[0], axis_angle(Mraw[j], dv)[0])   # Mraw 的列能否解释骨走向
    a_inv = min(axis_angle(W[k], dv)[0], axis_angle(W[j], dv)[0])
    pairs.append(dict(parent=names[j], child=names[k], cen_gap=nv, raw_min=a_raw, inv_min=a_inv,
                      len_raw=float(np.linalg.norm(tC[k] - tC[j]))))
print("\n(3) 父子骨对：'父->子 的重心差方向' 与 矩阵列向量 的最小夹角(允许反向)")
print("    %-27s %-27s %8s %8s %8s %8s" % ("parent", "child", "|c_k-c_j|", "Mraw列角°", "inv列角°", "|t_k-t_j|Mraw"))
for p in pairs:
    print("    %-27s %-27s %8.3f %8.1f %8.1f %8.3f" % (p["parent"], p["child"], p["cen_gap"], p["raw_min"], p["inv_min"], p["len_raw"]))
if pairs:
    a = np.array([p["raw_min"] for p in pairs]); b = np.array([p["inv_min"] for p in pairs])
    print("    汇总: Mraw 列对齐 mean=%.1f° med=%.1f° <20°:%d/%d | inv(Mraw) 列对齐 mean=%.1f° med=%.1f° <20°:%d/%d" % (
        a.mean(), np.median(a), int((a < 20).sum()), len(a), b.mean(), np.median(b), int((b < 20).sum()), len(b)))

# 额外: 层级自洽性 —— 若 Mraw 是真 world 绑定矩阵，local = inv(M_parent) @ M_child 应是小偏移的合理 TRS
print("\n(5) 层级自洽: local = inv(M_parent)·M_child 的平移长度 (应≈ 父子真实骨长，且远小于世界坐标)")
for k in range(NJ):
    j = D["jpar"][k]
    if j < 0: continue
    for lbl, MM in [("Mraw", Mraw), ("inv(Mraw)", W)]:
        loc = G.affine_inv4(MM[j]) @ MM[k]
        lt = np.linalg.norm(loc[:3, 3]); lr = math.degrees(math.acos(max(-1, min(1, (np.trace(loc[:3, :3]) - 1) / 2))))
        if lbl == "Mraw":
            s1 = (lt, lr)
        else:
            s2 = (lt, lr)
    if names[k] not in ("000",):
        print("   %-27s Mraw: |local t|=%6.3f rot=%6.1f° | inv: |local t|=%6.3f rot=%6.1f°" % (names[k], s1[0], s1[1], s2[0], s2[1]))
