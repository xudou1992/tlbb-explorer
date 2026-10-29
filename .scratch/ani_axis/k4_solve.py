"""终局：反解无记录骨的真 rest 旋转 -> 全骨精确 blocal -> K 递归全解 -> 修正复合播放。

原理链（全部已证）：
  1) 静态区 qrest（列口径读法取转置）= bind 局部旋转，对「父有记录」的记录骨成立（15/20 + 跨怪 13/16、14/16）；
  2) 轨道常量平移 = bind 局部平移（干净骨向量级相等）；
  3) 于是 rest 局部 L_rec(j) = [R(qrest_j)ᵀ, t_rest(j)] 对已知部分可重建 bind；
  4) 无记录骨的旋转缺失 -> 用其**有记录子孙**的真实 bind 世界反解：
     W_b := B_c · L_rec(c)⁻¹（c = b 的任一有记录孩子），再用其余有记录孩子/后代验证。
  5) 46 根 blocal 全部精确后，K 递归（K_j = L_j(0)⁻¹ K_p blocal_j）给出逐骨帧映射，
     修正复合 W_j(f) = K_j⁻¹ G_j(f) K_j + IBM 锚 = 引擎播放口径。
验证：idle01 / deadbegin / walk 修正复合后蒙皮位移与重心残差。
输出 k4_solve.txt
"""
import sys, math, json
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, compose_worlds, ang, skin, centroid_resid, locals_frames
from k2_rest import parse_ani

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


D = build(GLBS["yifu"])
AN = read_anims(D)
NJ, names, jpar = D["NJ"], D["names"], D["jpar"]
B, IBM, C = D["B"], D["IBM"], D["C"]
covj = np.where(D["cov"])[0]; covj = covj[covj != 0]
Rb = D["blocal"][:, :3, :3].copy(); blt = D["blocal"][:, :3, 3].copy()
ph = [j for j in range(NJ) if np.linalg.norm(blt[j]) < 1e-6 and np.abs(Rb[j] - np.eye(3)).max() < 1e-5]
use = (~D["root_only"]) & (D["wsum"] > 0.999)

A = parse_ani(ANIDIR + r"\w1351_monster_xiyuqiezei_idle01.ani")
name2i = {nm: i for i, nm in enumerate(A["names"])}
ani_of = {j: name2i[names[j]] for j in range(NJ) if names[j] in name2i}
qrest = {}
tmed = {}
for j in range(NJ):
    if j in ani_of:
        tr = np.array(A["tracks"][ani_of[j]]["pos"])
        tmed[j] = np.median(tr, axis=0)
for i, nm in enumerate(A["names"]):
    if nm:
        qrest[names.index(nm)] = A["rests"][i][1]
# pelvis 的 rest 平移 = off48(bip01)（根运动骨特例）
j_pelvis = names.index("bip01_pelvis")
j_bip01 = names.index("bip01")
tmed[j_pelvis] = A["rests"][A["names"].index("bip01")][2]

kids = {}
for j in range(NJ):
    p = jpar[j]
    if p >= 0:
        kids.setdefault(p, []).append(j)


def L_rec(j):
    """静态区 rest 局部（被动读法）。"""
    L = np.eye(4)
    if j in qrest:
        L[:3, :3] = qmat(qrest[j]).T
    if j in tmed:
        L[:3, 3] = tmed[j]
    return L


# 步骤 1：反解无记录骨的世界（BFS，自根向下）
say("=== 反解无记录骨的 rest 世界（用有记录孩子的真实 bind 世界）===")
Wrec = {}
solved = {}
for j in D["seq"]:
    p = jpar[j]
    if j not in ph and j in ani_of:  # 有记录骨：世界 = 记录逆（GLB B 即真实世界）
        Wrec[j] = B[j]
        continue
    # 无记录骨：用有记录孩子反解
    cands = []
    for c in kids.get(j, []):
        if c not in ph:
            cands.append(c)
    got = None
    for c in cands:
        # W_b = B_c · L_rec(c)⁻¹
        Wb = B[c] @ np.linalg.inv(L_rec(c))
        got = Wb
        break
    if got is None:
        # 没有有记录孩子：从父世界 + 静态局部推（精度依赖父已解）
        Wp = Wrec.get(p, B[p] if p >= 0 else np.eye(4))
        got = Wp @ L_rec(j)
        solved[j] = "fallback"
    else:
        solved[j] = "solved"
    Wrec[j] = got
for j in range(NJ):
    if j in ph:
        say("  %-24s %s" % (names[j], solved.get(j, "?")))
# 验证 1：反解出的 W_spine1 与另一个有记录孩子（r_clavicle vs r_upperarm 链?）交叉验证
say("\n  交叉验证：spine1 由不同有记录孩子反解的差")
cands = [c for c in kids.get(names.index("bip01_spine1"), [])]
Ws = []
for c in cands:
    if c not in ph:
        Ws.append((names[c], B[c] @ np.linalg.inv(L_rec(c))))
if len(Ws) >= 2:
    for k in range(1, len(Ws)):
        dW = Ws[0][1] @ np.linalg.inv(Ws[k][1])
        say("    %s vs %s : 相对旋转 %.3f° 平移 %.5f" %
            (Ws[0][0], Ws[k][0], ang(dW[:3, :3]), np.linalg.norm(dW[:3, 3])))
else:
    say("    spine1 只有 %d 个有记录孩子，无法交叉验证" % len(Ws))

# 步骤 2：全骨精确 blocal = Wrec_parent⁻¹ · Wrec_j
blocalT = np.zeros((NJ, 4, 4))
for j in D["seq"]:
    p = jpar[j]
    blocalT[j] = Wrec[j] if p < 0 else np.linalg.inv(Wrec[p]) @ Wrec[j]
# 验证 2：对「干净记录骨」blocalT == blocal
clean = [j for j in range(NJ) if j not in ph and jpar[j] >= 0 and jpar[j] not in ph]
dR = np.array([ang(blocalT[j, :3, :3] @ Rb[j].T) for j in clean])
dT = np.array([np.linalg.norm(blocalT[j, :3, 3] - Rb[j].T @ (blt[j] - blt[j]) + blocalT[j, :3, 3] - blt[j] * 0 - blt[j]) for j in clean])
say("\n=== 验证：反解 blocal vs GLB blocal（干净骨 %d 根）===" % len(clean))
say("  旋转角差: median %.4f° max %.4f° ; 平移差: median %.5f max %.5f" %
    (np.median(dR), dR.max(), np.median([np.linalg.norm(blocalT[j, :3, 3] - blt[j]) for j in clean]),
     max(np.linalg.norm(blocalT[j, :3, 3] - blt[j]) for j in clean)))
# 静态区模式在「父已反解」的记录骨上是否成立（现在父精确了）
say("  qrest==blocal⁻¹（全部记录骨, 父已精确）: ", )
h = t2 = 0
for j in range(NJ):
    if j not in ph and j in qrest and jpar[j] >= 0:
        t2 += 1
        # blocalT[j] vs qrest 逆
        if ang(blocalT[j, :3, :3] @ qmat(qrest[j])) < 0.01:
            h += 1
say("%d/%d" % (h, t2))

# 步骤 3：K 递归全解（用精确 blocalT）+ 修正复合播放
say("\n=== K 递归全解 + 修正复合播放（W_j(f) = K_j⁻¹ · G_j(f) · K_j, IBM 锚）===")
Lr0, Lt0, has0 = locals_frames(AN["idle01"], D, len(list(AN["idle01"].values())[0]["translation"][0]))
Lr0f = Lr0[:, 0]; Lt0f = Lt0[:, 0]
K = {}
for j in D["seq"]:
    p = jpar[j]
    if p < 0:
        K[j] = np.eye(4)
    else:
        L = np.eye(4); L[:3, :3] = Lr0f[j]; L[:3, 3] = Lt0f[j]
        K[j] = np.linalg.inv(L) @ K[p] @ blocalT[j]
# frame0 修正世界 vs bind（现在应全骨闭合）
G0 = compose_worlds(Lr0f, Lt0f, D)
W0c = np.stack([np.linalg.inv(K[j]) @ G0[j] @ K[j] for j in range(NJ)])
dt0 = np.linalg.norm(W0c[:, :3, 3] - B[:, :3, 3], axis=1)
dr0 = np.array([ang(W0c[j, :3, :3] @ B[j, :3, :3].T) for j in range(NJ)])
say("  frame0 修正世界 vs B: |Δt| med %.5f max %.5f ; 角差 med %.4f° max %.4f°" %
    (np.median(dt0), dt0.max(), np.median(dr0), dr0.max()))

jsonK = {names[j]: K[j].tolist() for j in range(NJ)}
json.dump(jsonK, open(r"D:\TLGL\.scratch\ani_axis\k4_K.json", "w"))
Kinv = {j: np.linalg.inv(K[j]) for j in range(NJ)}

summary = {}
for a in sorted(AN):
    per = AN[a]
    nf = len(list(per.values())[0]["translation"][0])
    Lrot, Ltr, _ = locals_frames(per, D, nf)
    G = compose_worlds(Lrot, Ltr, D)
    Wc = np.empty_like(G)
    for j in range(NJ):
        Wc[j] = Kinv[j] @ G[j] @ K[j]
    Vp = skin(Wc, IBM, D)
    disp = np.linalg.norm(Vp - D["POS"][:, None, :], axis=2)
    fm = disp[use].mean(0)
    d2 = centroid_resid(Wc, Vp, D)
    summary[a] = (float(fm.max()), float(disp[use].max()), float(d2[covj].mean()))
    say("  %-16s 修正复合+IBM锚: 帧均 max %.4f 全max %.4f 重心 mean %.4f" % (a, fm.max(), disp[use].max(), d2[covj].mean()))
json.dump(summary, open(r"D:\TLGL\.scratch\ani_axis\k4_solve.json", "w"))
open(r"D:\TLGL\.scratch\ani_axis\k4_solve.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k4_solve.txt / k4_solve.json / k4_K.json")
