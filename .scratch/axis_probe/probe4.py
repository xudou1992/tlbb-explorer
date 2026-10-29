"""probe4.py — 收尾判据：重心相对 Mraw 原点的偏移是否沿骨轴方向（证明 Mraw 就是网格空间里的 bone→world 矩阵）"""
import math, numpy as np, glbcore as G
D = G.build(); NJ = D["NJ"]; names = D["names"]; Mraw = D["Mraw"]; W = D["W"]
tC = np.stack([Mraw[j][:3, 3] for j in range(NJ)]); tA = W[:, :3, 3]
C, S, N, cov, ROOT, nused = G.centroids(D, True)
fit = np.array([j for j in np.where(cov)[0] if j != ROOT])
def minang(M, v):
    v = v / np.linalg.norm(v); best = 180.0; bi = 0
    for k in range(3):
        c = M[:3, k]; c = c / np.linalg.norm(c)
        a = math.degrees(math.acos(max(-1.0, min(1.0, float(c @ v))))); a = min(a, 180 - a)
        if a < best: best, bi = a, k
    return best, bi
for lbl, T, MM in [("Mraw(未逆)", tC, Mraw), ("inv(Mraw)", tA, W)]:
    ang = []; idx = []; res = []
    for j in fit:
        v = C[j] - T[j]; n = float(np.linalg.norm(v))
        if n < 1e-6: continue
        a, bi = minang(MM[j], v); ang.append(a); idx.append(bi); res.append(n)
    ang = np.array(ang); res = np.array(res)
    print("%-12s n=%d |c-t| mean=%.4f med=%.4f max=%.4f | (c-t) 与矩阵列最小夹角 mean=%.1f° med=%.1f° <20°:%d/%d | 选中列分布 %s" % (
        lbl, len(ang), res.mean(), np.median(res), res.max(), ang.mean(), np.median(ang), int((ang < 20).sum()), len(ang),
        {c: idx.count(c) for c in sorted(set(idx))}))
# 沿骨轴分量的符号: 重心应落在骨的正向局部轴一侧
sg = []
for j in fit:
    v = C[j] - tC[j]; n = float(np.linalg.norm(v))
    if n < 1e-6: continue
    a, bi = minang(Mraw[j], v)
    c = Mraw[j][:3, bi]; c = c / np.linalg.norm(c)
    sg.append(float(np.sign(c @ v)))
print("重心相对原点的轴向符号: +1 占 %.0f%% (%d 正 / %d 负)" % (100 * sg.count(1.0) / len(sg), sg.count(1.0), sg.count(-1.0)))
print("\n参与拟合的 26 根骨逐骨残差 (C=Mraw平移列 vs 重心):")
for j in fit:
    print("   %-28s |c-t|=%.4f  sumw=%6.1f  verts=%3d" % (names[j], float(np.linalg.norm(C[j]-tC[j])), S[j], N[j]))
print("\n对照 inv(Mraw) 的逐骨残差:")
for j in fit:
    print("   %-28s |c-t|=%.4f" % (names[j], float(np.linalg.norm(C[j]-tA[j]))))
