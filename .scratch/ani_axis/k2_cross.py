"""跨动作锚测试（2026-10-07）：一个锚能否服务全部 15 条动作？

背景：15 条动作里 9 条 frame0 完全相同（=引擎 rest 姿态候选），6 条不同
（walk/run/idle02/dead/flyingdeadbegin/behit01 起步在半程）。
播放接线候选：
  A1 逐动作 frame0 锚（上一班方案）
  A2 全局锚 = idle01 的 frame0（9 条动作共享的那个姿态）
  A3 全局锚 = 静态区重建 rest Brec=[R(qrest)ᵀ, off48(父)] 的世界（刀3 闭合产物）
  A0 裸 bind 锚（现状, 对照）
每条动作量：帧均位移 min~max / 全max / 重心残差 mean。
输出 k2_cross.txt
"""
import sys, struct, math, json
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, compose_worlds, ang, skin, centroid_resid
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
qrest = {i2j: None for i2j in []}
qrest = {}
off48 = {}
for i, nm in enumerate(A["names"]):
    if nm:
        j = [jj for jj, nn in enumerate(names) if nn == nm][0]
        qrest[j] = A["rests"][i][1]
        off48[j] = np.array(A["rests"][i][2])

# A3: 静态区重建 rest 世界（两种 pelvis 例外处理：原样 / 强制逆）
def build_rest(pelvis_fix):
    rec_local = np.zeros((NJ, 4, 4))
    for j in range(NJ):
        L = np.eye(4)
        if j in qrest:
            R = qmat(qrest[j]).T
            if pelvis_fix and names[j] == "bip01_pelvis":
                R = qmat(qrest[j])  # pelvis 是唯一「正序」例外 -> 取逆
            L[:3, :3] = R
        p = jpar[j]
        if p >= 0 and p in off48:
            L[:3, 3] = off48[p]
        elif j in ani_of:
            L[:3, 3] = np.array(A["tracks"][ani_of[j]]["pos"][0])
        rec_local[j] = L
    W = {}
    for j in D["seq"]:
        p = jpar[j]
        W[j] = rec_local[j] if p < 0 else W[p] @ rec_local[j]
    return np.stack([W[j] for j in range(NJ)])


Brec = build_rest(True)
dt = np.linalg.norm(Brec[:, :3, 3] - B[:, :3, 3], axis=1)
dr = np.array([ang(Brec[j, :3, :3] @ B[j, :3, :3].T) for j in range(NJ)])
rec = [j for j in range(NJ) if j not in ph]
say("静态区重建 rest(pelvis 修正) vs bind：记录骨 |Δt| med %.5f max %.5f ; 角差 med %.3f° max %.3f° ; <0.01° %d/%d"
    % (np.median(dt[rec]), dt[rec].max(), np.median(dr[rec]), dr[rec].max(), int((dr[rec] < 0.01).sum()), len(rec)))
mask_ph = np.array([j in ph for j in covj])
offc = np.linalg.norm(C[covj] - Brec[covj, :3, 3], axis=1)
say("  重心判据: 记录骨 mean %.4f | 占位骨(有权重, n=%d) mean %.4f  (bind 记录骨参照 0.1488)"
    % (offc[~mask_ph].mean(), int(mask_ph.sum()), offc[mask_ph].mean() if mask_ph.sum() else -1))
for nm in ("bip01_spine1", "bip01_neck", "bip01_head", "bip01_l_clavicle", "bip01_l_forearm", "bip01_l_thigh"):
    j = names.index(nm)
    say("    %-18s 重建位 %s  重心 C %s  |Δ|=%.4f" %
        (nm, np.round(Brec[j, :3, 3], 4), np.round(C[j], 4),
         np.linalg.norm(Brec[j, :3, 3] - C[j]) if D["cov"][j] else -1))

# 各锚
G0s = {}
for a in sorted(AN):
    per = AN[a]
    nf = len(list(per.values())[0]["translation"][0])
    Lrot = np.tile(np.eye(3), (NJ, nf, 1, 1))
    Ltr = np.tile(D["blocal"][None, :, :3, 3], (nf, 1, 1)).transpose(1, 0, 2)
    for j, d in per.items():
        if "translation" in d and "rotation" in d:
            Ltr[j] = d["translation"][1][:nf]
            Lrot[j] = np.stack([qmat(q) for q in d["rotation"][1][:nf]])
    G0s[a] = compose_worlds(Lrot[:, 0], Ltr[:, 0], D)  # frame0 世界
    AN[a + "_G"] = compose_worlds(Lrot, Ltr, D)

idle0 = np.stack([np.linalg.inv(G0s["idle01"][j]) for j in range(NJ)])
Brec_inv = np.stack([np.linalg.inv(Brec[j]) for j in range(NJ)])

say("\n%-16s %22s %22s %22s %22s" % ("动作", "A0 裸bind", "A1 逐动作f0", "A2 idle01f0(全局)", "A3 静态重建rest"))
summary = {}
for a in sorted(AN):
    G = AN[a + "_G"]
    row = []
    for anchor in (IBM, None, idle0, Brec_inv):
        anc = np.stack([np.linalg.inv(G0s[a][j]) for j in range(NJ)]) if anchor is None else anchor
        Vp = skin(G, anc, D)
        disp = np.linalg.norm(Vp - D["POS"][:, None, :], axis=2)
        fm = disp[use].mean(0)
        d2 = centroid_resid(G, Vp, D)
        row.append((float(fm.min()), float(fm.max()), float(disp[use].max()), float(d2[covj].mean())))
    summary[a] = row
    say("%-16s %7.3f~%7.3f/%6.3f %7.3f~%7.3f/%6.3f %7.3f~%7.3f/%6.3f %7.3f~%7.3f/%6.3f" %
        (a, row[0][1], row[0][2], row[0][3], row[1][1], row[1][2], row[1][3],
         row[2][1], row[2][2], row[2][3], row[3][1], row[3][2], row[3][3]))
for k, nm in ((1, "A1逐动作f0"), (2, "A2 idle01f0"), (3, "A3静态rest")):
    say("  %s: 全动作 帧均最坏 %.4f 全max最坏 %.4f" %
        (nm, max(v[k][1] for v in summary.values()), max(v[k][2] for v in summary.values())))
json.dump({a: v for a, v in summary.items()}, open(r"D:\TLGL\.scratch\ani_axis\k2_cross.json", "w"))
open(r"D:\TLGL\.scratch\ani_axis\k2_cross.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k2_cross.txt / k2_cross.json")
