"""刀1 判定性实验（2026-10-07）：.ani 旋转通道是不是「bind 静置旋转上的增量」？

背景：k1_kstruct 的 K 递归在 4 种读法下都不漂亮 -> 不是全局/逐骨轴映射。
新假设 H_delta：引擎局部 = bind 局部 ∘ .ani 增量，即
    true_local_j(f) = [Rb_j · Ra_j(f) 或 Ra_j(f) · Rb_j,  t_j(f)（可能带 Rb 共轭）]
其中 Rb_j = bind 局部旋转（无记录骨 = I 占位），Ra/t = .ani 通道原值。
若 H_delta 成立且 L(0)=I（静置起播的动作），frame0 世界应还原 bind 骨架
（含「无记录骨由 .ani 常量偏移补齐」的修正版），bind 锚直接可播、无撕裂。

步骤：
  [G] L_ani(0) 与 I / 与 Rb 的逐骨角差（idle01 全骨）——判定通道语义。
  [H] 12 种组合变体（rot 4 种 x t 3 种）复合 frame0 世界：
      vs bind 的 |Δt|/角差、静态重心判据、解剖高度。
  [I] 最优变体下播完整 idle01 + walk（bind 锚）：蒙皮位移/重心残差，
      对照上一班数字（raw+bind 1.75/2.43；raw+frame0 0.23/0.85）。
  [J] 干净骨（自有记录且父有记录）t_ani vs blocal_t 向量级对照（刀3 方向+模长）。
输出 k1_variant.txt
"""
import sys, json, itertools, math
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import (GLBS, build, locals_frames, compose_worlds, ang, perm_R, skin,
                     centroid_resid)

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


D = build(GLBS["yifu"])
AN = read_anims(D)
NJ, names, jpar = D["NJ"], D["names"], D["jpar"]
B, IBM, C = D["B"], D["IBM"], D["C"]
covj = np.where(D["cov"])[0]; covj = covj[covj != 0]
Rb = D["blocal"][:, :3, :3].copy()
blt = D["blocal"][:, :3, 3].copy()

placeholder = [j for j in range(NJ)
               if np.linalg.norm(blt[j]) < 1e-6 and np.abs(Rb[j] - np.eye(3)).max() < 1e-5]
clean = [j for j in range(NJ) if j not in placeholder and jpar[j] >= 0 and jpar[j] not in placeholder]

# .ani 局部轨道（idle01 全帧）
NF = len(list(AN["idle01"].values())[0]["translation"][0])
Lrot, Ltr, has = locals_frames(AN["idle01"], D, NF)

# ---- [G] L(0) 的语义 ----
say("=== [G] idle01 第0帧局部旋转 Ra_j(0) 的语义（46 骨）===")
dI = np.array([ang(Lrot[j, 0]) for j in range(NJ)])          # vs 单位阵
dB = np.array([ang(Lrot[j, 0] @ Rb[j].T) for j in range(NJ)])  # vs bind 局部旋转
dT = np.array([ang(Lrot[j, 0].T @ Rb[j].T) for j in range(NJ)])  # Ra^T vs Rb
say("  Ra(0) vs I   : median %.3f°  <0.01° 的骨 %d/%d" % (np.median(dI), int((dI < 0.01).sum()), NJ))
say("  Ra(0) vs Rb  : median %.3f°  <0.01° 的骨 %d/%d" % (np.median(dB), int((dB < 0.01).sum()), NJ))
say("  Ra(0)ᵀ vs Rb : median %.3f°  <0.01° 的骨 %d/%d" % (np.median(dT), int((dT < 0.01).sum()), NJ))
say("  （ Ra(0)≈I => 增量语义; Ra(0)≈Rb => 绝对语义 ）")
say("  Ra(0) vs I 最小的 10 根: " + ", ".join("%s(%.2f°)" % (names[j], dI[j]) for j in np.argsort(dI)[:10]))
say("  Ra(0) vs I 最大的 5 根: " + ", ".join("%s(%.2f°)" % (names[j], dI[j]) for j in np.argsort(-dI)[:5]))
# 其它静置起播的动作 L(0) 是否也 = I
say("\n  各动作 L(0) vs I 的 median/max 角差（全骨）:")
for a in sorted(AN):
    lr, lt, _ = locals_frames(AN[a], D, len(list(AN[a].values())[0]["translation"][0]))
    dd = np.array([ang(lr[j, 0]) for j in range(NJ)])
    say("    %-16s median %7.3f°  max %7.3f°  <0.01° 骨数 %d" %
        (a, np.median(dd), dd.max(), int((dd < 0.01).sum())))

# ---- [H] 变体扫描（frame0）----
say("\n=== [H] 12 变体复合 frame0 世界 vs bind ===")
RA0 = Lrot[:, 0, :, :]
TA0 = Ltr[:, 0, :]


def compose_variant(rotmode, tmode):
    Lr = np.zeros_like(RA0); Lt = np.zeros_like(TA0)
    for j in range(NJ):
        if rotmode == "RaRb":
            Lr[j] = RA0[j] @ Rb[j]
        elif rotmode == "RbRa":
            Lr[j] = Rb[j] @ RA0[j]
        elif rotmode == "Ra":
            Lr[j] = RA0[j]
        elif rotmode == "RaT":
            Lr[j] = RA0[j].T
        if tmode == "t":
            Lt[j] = TA0[j]
        elif tmode == "Rbt":
            Lt[j] = Rb[j] @ TA0[j]
        elif tmode == "RbTt":
            Lt[j] = Rb[j].T @ TA0[j]
    return compose_worlds(Lr, Lt, D)


rows = []
for rotmode in ("RaRb", "RbRa", "Ra", "RaT"):
    for tmode in ("t", "Rbt", "RbTt"):
        G0 = compose_variant(rotmode, tmode)
        dt = np.linalg.norm(G0[:, :3, 3] - B[:, :3, 3], axis=1)
        dr = np.array([ang(G0[j, :3, :3] @ B[j, :3, :3].T) for j in range(NJ)])
        off = np.linalg.norm(C[covj] - G0[covj, :3, 3], axis=1)
        rows.append((float(off.mean()), rotmode, tmode, float(dt.mean()), float(dt.max()),
                     float(np.median(dr)), float(dr.max()), G0))
rows.sort(key=lambda r: r[0])
say("  %-6s %-6s %8s %8s %8s %8s %8s   (重心判据, bind 参照 0.1488)" %
    ("rot", "t", "重心mean", "|Δt|mean", "|Δt|max", "角差med", "角差max"))
for m, rm, tm, dtm, dtM, drm, drM, _ in rows:
    say("  %-6s %-6s %8.4f %8.4f %8.4f %8.2f %8.2f" % (rm, tm, m, dtm, dtM, drm, drM))
best = rows[0]
say("  最优变体: rot=%s t=%s" % (best[1], best[2]))
G0b = best[7]
say("  最优变体 frame0 骨位高度: pelvis %.4f head %.4f l_foot %.4f l_toe0 %.4f (bind: %.4f %.4f %.4f %.4f)" %
    (G0b[names.index("bip01_pelvis"), 1, 3], G0b[names.index("bip01_head"), 1, 3],
     G0b[names.index("bip01_l_foot"), 1, 3], G0b[names.index("bip01_l_toe0"), 1, 3],
     B[names.index("bip01_pelvis"), 1, 3], B[names.index("bip01_head"), 1, 3],
     B[names.index("bip01_l_foot"), 1, 3], B[names.index("bip01_l_toe0"), 1, 3]))

# ---- [I] 最优变体全帧播放（bind 锚）----
say("\n=== [I] 最优变体下播 idle01 与 walk（bind 锚=IBM，不重锚）===")
rotmode, tmode = best[1], best[2]
use = (~D["root_only"]) & (D["wsum"] > 0.999)


def play(anim):
    nf = len(list(AN[anim].values())[0]["translation"][0])
    lr, lt, _ = locals_frames(AN[anim], D, nf)
    Lr = np.zeros_like(lr); Lt = np.zeros_like(lt)
    for j in range(NJ):
        if rotmode == "RaRb":
            Lr[j] = lr[j] @ Rb[j][None]
        elif rotmode == "RbRa":
            Lr[j] = Rb[j][None] @ lr[j]
        elif rotmode == "Ra":
            Lr[j] = lr[j]
        else:  # RaT
            Lr[j] = np.transpose(lr[j], (0, 2, 1))
        if tmode == "t":
            Lt[j] = lt[j]
        elif tmode == "Rbt":
            Lt[j] = lt[j] @ Rb[j].T
        else:  # RbTt
            Lt[j] = lt[j] @ Rb[j]
    G = compose_worlds(Lr, Lt, D)
    Vp = skin(G, IBM, D)
    return G, Vp


for anim in ("idle01", "walk"):
    G, Vp = play(anim)
    POS = D["POS"]
    disp = np.linalg.norm(Vp - POS[:, None, :], axis=2)  # (NV,F)
    fm = disp[use].mean(0)
    d2 = centroid_resid(G, Vp, D)
    say("  %-7s [%s/%s] bind锚: 帧均位移 %.4f~%.4f 全max %.4f | 重心残差 mean %.4f max %.4f" %
        (anim, rotmode, tmode, fm.min(), fm.max(), disp[use].max(),
         d2[covj].mean(), d2[covj].max()))
    # 对照：同一变体 + frame0 锚
    anc = np.stack([np.linalg.inv(G[j, 0]) for j in range(NJ)])
    Vp2 = skin(G, anc, D)
    disp2 = np.linalg.norm(Vp2 - POS[:, None, :], axis=2)
    fm2 = disp2[use].mean(0)
    d22 = centroid_resid(G, Vp2, D)
    say("          同变体 frame0锚: 帧均 %.4f~%.4f 全max %.4f | 重心残差 mean %.4f" %
        (fm2.min(), fm2.max(), disp2[use].max(), d22[covj].mean()))

# ---- [J] 干净骨 t_ani vs blocal_t（向量级）----
say("\n=== [J] 干净骨（自有记录且父有记录，%d 根）: .ani 常量平移 vs bind 局部平移 ===" % len(clean))
say("  %-26s %9s %9s %9s %9s %9s" % ("bone", "|t_ani|", "|blt|", "|Δvec|", "夹角°", "夹角(Rbt)°"))
n_exact = 0
for j in sorted(clean, key=lambda j: -np.linalg.norm(blt[j])):
    if not has[j]:
        continue
    tm = np.median(Ltr[j], axis=0)
    dm = np.linalg.norm(tm - blt[j])
    cs = float(tm @ blt[j] / max(1e-12, np.linalg.norm(tm) * np.linalg.norm(blt[j])))
    a1 = math.degrees(math.acos(max(-1, min(1, cs))))
    cs2 = float((Rb[j] @ tm) @ blt[j] / max(1e-12, np.linalg.norm(tm) * np.linalg.norm(blt[j])))
    a2 = math.degrees(math.acos(max(-1, min(1, cs2))))
    if dm < 1e-4:
        n_exact += 1
    say("  %-26s %9.4f %9.4f %9.4f %9.2f %9.2f%s" %
        (names[j], np.linalg.norm(tm), np.linalg.norm(blt[j]), dm, a1, a2,
         "  <== 向量相等" if dm < 1e-4 else ""))
say("  向量级完全相等（|Δ|<1e-4）的干净骨 %d/%d" % (n_exact, len(clean)))

open(r"D:\TLGL\.scratch\ani_axis\k1_variant.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k1_variant.txt")
