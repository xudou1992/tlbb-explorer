"""模长是带符号置换的不变量 -> 逐骨比 |t_ani| vs bind 局部偏移 |lt|，判「轴系」之外还差什么。
输出：
  1) 逐骨表：bind |lt| / |B_t| / ani |t| 的 min~max 与跨帧 std（std=0 => 该骨的 ani 平移是常量=骨偏移）
  2) 与 bind 骨长做最近邻匹配：ani 骨 j 的 |t| 到底等于哪根 bind 骨的 |lt|（查通道->骨 是否错位）
  3) 最优 R 下逐骨 frame0 方向残差（夹角 vs 模长差），分「方向对模长错」/「方向也错」
"""
import numpy as np, sys, math
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, quat_mat

ANIM = sys.argv[1] if len(sys.argv) > 1 else "idle01"
PM, SG = eval(sys.argv[2]) if len(sys.argv) > 2 else ((2, 0, 1), (1.0, 1.0, 1.0))
D = build(); NJ = D["NJ"]; names = D["names"]
per = read_anims(D)[ANIM]; NF = len(per[sorted(per)[0]]["translation"][1])
R = np.zeros((3, 3))
for i in range(3): R[i, PM[i]] = SG[i]

blt = np.linalg.norm(D["blocal"][:, :3, 3], axis=1)          # bind 局部偏移长度（真骨长）
bwt = np.linalg.norm(D["B"][:, :3, 3], axis=1)
at = np.full((NJ, NF), np.nan)
for j, d in per.items():
    at[j] = np.linalg.norm(d["translation"][1][:NF], axis=1)
print("=== [1] 逐骨：bind 骨长 vs .ani 平移模长（R 无关，纯不变量）===")
print("%-26s %9s %9s %9s %9s %9s %7s" % ("bone", "|lt_bnd|", "|B_t|", "|t|min", "|t|max", "|t|med", "std"))
med = np.zeros(NJ); sd = np.zeros(NJ)
for j in range(NJ):
    if np.isnan(at[j]).all():
        print("%-26s %9.4f %9.4f %9s (无动画通道)" % (names[j], blt[j], bwt[j], "-")); continue
    v = at[j]; med[j] = np.median(v); sd[j] = v.std()
    flag = ""
    if blt[j] > 1e-6:
        r = med[j] / blt[j]
        flag = "ratio %.3f" % r + ("  <== 模长不符" if abs(r - 1) > 0.02 else "  ok")
    print("%-26s %9.4f %9.4f %9.4f %9.4f %9.4f %7.4f  %s" %
          (names[j], blt[j], bwt[j], v.min(), v.max(), med[j], sd[j], flag))
ok = [j for j in range(NJ) if not np.isnan(at[j]).all() and blt[j] > 1e-6 and abs(med[j] / blt[j] - 1) <= 0.02]
bad = [j for j in range(NJ) if not np.isnan(at[j]).all() and blt[j] > 1e-6 and abs(med[j] / blt[j] - 1) > 0.02]
print("\n  模长与 bind 骨长一致(±2%%)的骨 %d 根；不一致 %d 根" % (len(ok), len(bad)))
print("  跨帧 std≈0（<1e-4，即该骨 .ani 平移是常量）的骨 %d/%d" % (int((sd[sd > -1] < 1e-4).sum()), NJ))

print("\n=== [2] ani 骨 j 的 |t|(中位) 在 bind 骨长里的最近邻（查通道->骨错位）===")
hit_id = 0; perm = {}
for j in bad:
    k = int(np.argmin(np.abs(blt - med[j])))
    perm[j] = (names[k], float(abs(blt[k] - med[j])), float(abs(blt[j] - med[j])))
    if k == j: hit_id += 1
    print("  %-26s |t|=%.4f -> 最近 bind 骨 %-24s 差 %.4f | 自己差 %.4f %s" %
          (names[j], med[j], names[k], abs(blt[k] - med[j]), abs(blt[j] - med[j]),
           "(=自己)" if k == j else ""))
print("  -> 最近邻就是自己的 %d/%d（若大面积指向别的骨，则通道-骨映射错位）" % (hit_id, len(bad)))

print("\n=== [3] 最优 R=%s%s 下，逐骨 frame0 平移向量残差（方向角 / 模长差）===" % (PM, tuple(int(x) for x in SG)))
rows = []
for j in sorted(per):
    t0 = per[j]["translation"][1][0]
    tt = R @ t0
    ang = math.degrees(math.acos(max(-1, min(1, float(tt @ D["blocal"][j][:3, 3]) /
                          max(1e-9, np.linalg.norm(tt) * max(blt[j], 1e-9)))))) if blt[j] > 1e-6 else float('nan')
    rows.append((ang, float(np.linalg.norm(tt - D["blocal"][j][:3, 3])), abs(med[j] - blt[j]), names[j]))
rows.sort(key=lambda x: (0 if math.isnan(x[0]) else x[0]))
for ang, dn, dm, nm in rows[:12]:
    print("  %-26s 方向角 %7.2f  向量差 %7.4f  纯模长差 %7.4f" % (nm, ang, dn, dm))
print("  ...")
for ang, dn, dm, nm in rows[-6:]:
    print("  %-26s 方向角 %7.2f  向量差 %7.4f  纯模长差 %7.4f" % (nm, ang, dn, dm))
good_dir = [r for r in rows if not math.isnan(r[0]) and r[0] < 15]
print("  方向角<15°（模长之外方向对上了）的骨 %d/%d；<5° %d" %
      (len(good_dir), len(rows), len([r for r in rows if not math.isnan(r[0]) and r[0] < 5])))

print("\n=== [4] 旋转侧：共轭后 frame0 局部旋转 vs bind 局部旋转的角差，按父链深度 ===")
depth = {}
for j in range(NJ):
    d_ = 0; q = D["jpar"][j]
    while q >= 0: d_ += 1; q = D["jpar"][q]
    depth[j] = d_
res = []
for j in sorted(per):
    M = quat_mat(per[j]["rotation"][1][0])
    Mc = R.T @ M @ R
    E = Mc.T @ D["blocal"][j][:3, :3]
    a = math.degrees(math.acos(max(-1, min(1, (np.trace(E) - 1) / 2))))
    res.append((depth[j], a, names[j], j))
res.sort()
for dp, a, nm, j in res:
    print("  d=%d %-26s 角差 %7.2f" % (dp, nm, a))
import collections
g = collections.defaultdict(list)
for dp, a, nm, j in res: g[dp].append(a)
print("  按深度均值：" + "  ".join("d%d %.1f°" % (k, np.mean(v)) for k, v in sorted(g.items())))
