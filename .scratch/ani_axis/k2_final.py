"""终局管线测试（2026-10-07）：.ani 静态区 rest 相对蒙皮。

引擎模型 H_engine：
  rest_local_j = [qrest_j, off48(parent_j)]  （off48 = .ani 静态区 +48，= 子骨 rest 平移）
  rest 世界 W0_j = 沿树复合；
  palette M_j(f) = world_j(f) · W0_j^{-1} · B_j   （B = .mesh bind 世界 = IBM⁻¹）
  => 等价于把 IBM' = W0_j^{-1}·B_j 烘焙进 GLB skin，动画通道原样 —— 一次固定，无需逐动作重锚。

检验：
  [V] W0 vs bind B（记录骨逐骨差）—— 静态 rest 与 mesh bind 的关系
  [W] 15 条动作 × M_j(f)=world·W0⁻¹·B 蒙皮：帧均/全max 位移 + 重心残差
      对照：frame0 锚（逐动作）与裸 bind 锚
  [X] qrest 四元数分量序 battery（24 排列 × 逆）：vs 精确 blocal⁻¹ 的命中数
输出 k2_final.txt
"""
import sys, struct, math, json, itertools
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, compose_worlds, ang, skin, centroid_resid
from k2_rest import parse_ani, qmul

ANIDIR = r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_xiyuqiezei\ani"
OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def qmat(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]], float)


def mq(R):
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0:
        s = math.sqrt(t + 1) * 2; w = s / 4; x = (R[2, 1] - R[1, 2]) / s; y = (R[0, 2] - R[2, 0]) / s; z = (R[1, 0] - R[0, 1]) / s
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2; w = (R[2, 1] - R[1, 2]) / s; x = s / 4; y = (R[0, 1] + R[1, 0]) / s; z = (R[0, 2] + R[2, 0]) / s
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2; w = (R[0, 2] - R[2, 0]) / s; x = (R[0, 1] + R[1, 0]) / s; y = s / 4; z = (R[1, 2] + R[2, 1]) / s
    else:
        s = math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2; w = (R[1, 0] - R[0, 1]) / s; x = (R[0, 2] + R[2, 0]) / s; y = (R[1, 2] + R[2, 1]) / s; z = s / 4
    return [x, y, z, w]


def qang(a, b):
    return ang(qmat(a) @ qmat(b).T)


D = build(GLBS["yifu"])
AN = read_anims(D)
NJ, names, jpar = D["NJ"], D["names"], D["jpar"]
B, IBM, C = D["B"], D["IBM"], D["C"]
covj = np.where(D["cov"])[0]; covj = covj[covj != 0]
Rb = D["blocal"][:, :3, :3].copy(); blt = D["blocal"][:, :3, 3].copy()
ph = [j for j in range(NJ) if np.linalg.norm(blt[j]) < 1e-6 and np.abs(Rb[j] - np.eye(3)).max() < 1e-5]

A = parse_ani(ANIDIR + r"\w1351_monster_xiyuqiezei_idle01.ani")
name2i = {nm: i for i, nm in enumerate(A["names"])}
name2j = {nm: j for j, nm in enumerate(names)}
i2j = {i: name2j[nm] for i, nm in enumerate(A["names"]) if nm}
ani_of = {names[j]: i for j in range(NJ) for i in [name2i.get(names[j])] if i is not None}

# 静态区 rest 局部
qrest = {}; off48 = {}
for i, nm in enumerate(A["names"]):
    if nm:
        qrest[i2j[i]] = A["rests"][i][1]
        off48[i2j[i]] = np.array(A["rests"][i][2])
# 未命名轨道的记录也在（46 条）；找未命名下标，挂到无轨的骨上无意义，先跳过

def rest_local(j):
    """rest 局部 [qrest_j, off48(parent)]；父无记录时用自身轨道 frame0 平移。"""
    L = np.eye(4)
    if j in qrest:
        L[:3, :3] = qmat(qrest[j])
    p = jpar[j]
    if p >= 0 and p in off48:
        L[:3, 3] = off48[p]
    elif j in ani_of:
        L[:3, 3] = np.array(A["tracks"][ani_of[j]]["pos"][0])
    return L


W0 = compose_worlds(np.stack([rest_local(j)[:3, :3] for j in range(NJ)]),
                    np.stack([rest_local(j)[:3, 3] for j in range(NJ)]), D)

say("=== [V] 静态区 rest 世界 W0 vs bind 世界 B（记录骨）===")
dt = np.linalg.norm(W0[:, :3, 3] - B[:, :3, 3], axis=1)
dr = np.array([ang(W0[j, :3, :3] @ B[j, :3, :3].T) for j in range(NJ)])
rec = [j for j in range(NJ) if j not in ph]
say("  记录骨: |Δt| med %.4f max %.4f ; 角差 med %.2f° max %.2f° ; <0.01° 的骨 %d/%d" %
    (np.median(dt[rec]), dt[rec].max(), np.median(dr[rec]), dr[rec].max(),
     int((dr[rec] < 0.01).sum()), len(rec)))
offc = np.linalg.norm(C[covj] - W0[covj, :3, 3], axis=1)
say("  静态重心判据 |C-W0位|: mean %.4f (bind 参照 0.1488, raw frame0 1.85)" % offc.mean())

# 关键: IBM' = W0^-1 · B
W0inv = np.stack([np.linalg.inv(W0[j]) for j in range(NJ)])
IBM2 = np.stack([W0inv[j] @ B[j] for j in range(NJ)])

use = (~D["root_only"]) & (D["wsum"] > 0.999)
say("\n=== [W] 15 条动作蒙皮（yifu, 781 顶点）===")
say("  %-16s %26s %26s %26s" % ("动作",
    "裸bind锚(现状) 帧均~max", "frame0锚(逐动作) 帧均~max", "rest锚IBM'=W0⁻¹B 帧均~max"))
summary = {}
for a in sorted(AN):
    per = AN[a]
    nf = len(list(per.values())[0]["translation"][0])
    Lrot = np.tile(np.eye(3), (NJ, nf, 1, 1)); Ltr = np.tile(D["blocal"][None, :, :3, 3], (nf, 1, 1)).transpose(1, 0, 2)
    has = np.zeros(NJ, bool)
    for j, d in per.items():
        if "translation" in d and "rotation" in d:
            has[j] = True
            Ltr[j] = d["translation"][1][:nf]
            Lrot[j] = np.stack([qmat(q) for q in d["rotation"][1][:nf]])
    G = compose_worlds(Lrot, Ltr, D)
    # 三种锚
    out = []
    for anchor, tag in ((IBM, "bind"), (None, "f0"), (IBM2, "rest")):
        if anchor is None:
            anchor = np.stack([np.linalg.inv(G[j, 0]) for j in range(NJ)])
        Vp = skin(G, anchor, D)
        disp = np.linalg.norm(Vp - D["POS"][:, None, :], axis=2)
        fm = disp[use].mean(0)
        d2 = centroid_resid(G, Vp, D)
        out.append((fm.min(), fm.max(), disp[use].max(), d2[covj].mean()))
    summary[a] = out
    say("  %-16s %10.4f~%8.4f/%7.4f %10.4f~%8.4f/%7.4f %10.4f~%8.4f/%7.4f" %
        (a, out[0][0], out[0][1], out[0][2], out[1][0], out[1][1], out[1][2],
         out[2][0], out[2][1], out[2][2]))
w = [v[2][2] for v in summary.values()]
say("  rest 锚全动作全max 位移 = %.4f ; 帧均最坏 = %.4f" % (max(w), max(v[2][1] for v in summary.values())))
w0 = [v[1][2] for v in summary.values()]
say("  frame0 锚全动作全max = %.4f" % max(w0))
wB = [v[0][2] for v in summary.values()]
say("  裸 bind 锚全动作全max = %.4f" % max(wB))
json.dump({a: [[float(x) for x in o] for o in v] for a, v in summary.items()},
          open(r"D:\TLGL\.scratch\ani_axis\k2_final.json", "w"))

say("\n=== [X] qrest 四元数分量序 battery（vs 精确记录骨 blocal⁻¹）===")
# 精确骨：自有记录且父有记录（blocal 精确）——qrest 应等于 blocal^{-1} 或其分量重排
clean = [j for j in range(NJ) if j not in ph and jpar[j] >= 0 and jpar[j] not in ph and j in qrest]
best = None
for perm in itertools.permutations(range(4)):
    for inv in (0, 1):
        n = 0
        for j in clean:
            q = [qrest[j][perm[0]], qrest[j][perm[1]], qrest[j][perm[2]], qrest[j][perm[3]]]
            qq = q if not inv else [-q[0], -q[1], -q[2], q[3]]
            qb = mq(Rb[j])
            if qang(qq, [-qb[0], -qb[1], -qb[2], qb[3]]) < 0.01:
                n += 1
        if best is None or n > best[0]:
            best = (n, perm, inv)
        if n > 3:
            say("  分量序 %s inv=%d: 命中 %d/%d" % (perm, inv, n, len(clean)))
say("  最优: 分量序 %s inv=%d 命中 %d/%d（-clean 定义见上）" % (best[1], best[2], best[0], len(clean)))

open(r"D:\TLGL\.scratch\ani_axis\k2_final.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k2_final.txt / k2_final.json")
