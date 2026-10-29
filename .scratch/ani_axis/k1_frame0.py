"""刀1（2026-10-07）：frame0 是不是另一副 rest pose？播放基准该用什么？

对 yifu_001（781 顶点，唯一有真实蒙皮的样品）+ shoutao_001（42 顶点全绑根骨，仅作对照）：
  [A] 逐动作 frame0 世界矩阵（R=I 原始 .ani 轴）；
      跨 15 条动作的逐骨稳定性：平移 max pairwise |Δt|、旋转 max 夹角。
  [B] frame0 vs bind（.mesh B）：逐骨 |Δt| / 旋转角差；差异的结构分解：
      E_j = G0_j·B_j^{-1}（bind 锚在 frame0 的错，世界轴）逐骨角/平移，
      以及 E 旋转部分逐骨是否同一个旋转（=全局刚体差）。
  [C] 物理重心判据（verify.py 0.1488 的同款）：|C_j - 骨位|，
      bind vs frame0原始 vs frame0 经 48 个带符号置换 Q 映射（t -> Q^T t）。
      同时给最优 Q 下骨架解剖高度。
  [D] 跨动作锚互用：用 idle01 的 frame0 锚播其它动作，frame0 处位移（刚体平移量）
      与逐骨锚差角（非刚体成分）。
输出 k1_frame0.txt / k1_frame0.json
"""
import sys, json, itertools, math
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, locals_frame0, compose_worlds, ang, perm_R

OUT = []
JS = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def spread(vals):
    """vals: list of (NJ, ...) -> 逐骨 max pairwise 差。"""
    n = len(vals)
    sp_t = np.zeros(len(vals[0]))
    for a, b in itertools.combinations(range(n), 2):
        sp_t = np.maximum(sp_t, np.linalg.norm(vals[a] - vals[b], axis=-1))
    return sp_t


def rot_spread(Rs):
    n = len(Rs)
    sp = np.zeros(Rs[0].shape[0])
    for a, b in itertools.combinations(range(n), 2):
        for j in range(Rs[0].shape[0]):
            sp[j] = max(sp[j], ang(Rs[a][j] @ Rs[b][j].T))
    return sp


RESULT = {}
for tag, path in GLBS.items():
    D = build(path)
    AN = read_anims(D)
    NJ, names = D["NJ"], D["names"]
    B = D["B"]; C = D["C"]; cov = D["cov"]; covj = np.where(cov)[0]
    covj = covj[covj != 0]  # 与上一班同口径：剔根骨 000
    anims = sorted(AN)
    res = {"tag": tag}

    say("#" * 70)
    say("=== 模型 %s (NJ=%d verts=%d 带权重骨=%d) ===" % (tag, NJ, len(D["POS"]), int(cov.sum())))

    # ---- [A] frame0 世界 & 跨动作稳定性 ----
    G0s, R0s, T0s = {}, {}, {}
    for a in anims:
        Lr0, Lt0, has0 = locals_frame0(AN[a], D)
        G0 = compose_worlds(Lr0, Lt0, D)
        G0s[a] = G0; R0s[a] = G0[:, :3, :3]; T0s[a] = G0[:, :3, 3]
    sp_t = spread([T0s[a] for a in anims])
    sp_r = rot_spread([R0s[a] for a in anims])
    n_const_t = int((sp_t < 1e-6).sum()); n_const_r = int((sp_r < 0.01).sum())
    say("\n[A] frame0 跨 15 条动作逐骨稳定性（原始 .ani 轴, R=I）")
    say("    平移 max|Δt| < 1e-6 的骨 %d/%d ; 旋转 max夹角 < 0.01° 的骨 %d/%d" %
        (n_const_t, NJ, n_const_r, NJ))
    say("    平移 spread: median %.3e  p90 %.3e  max %.4f (%s)" %
        (np.median(sp_t), np.percentile(sp_t, 90), sp_t.max(), names[int(sp_t.argmax())]))
    say("    旋转 spread: median %.4f° p90 %.4f° max %.4f° (%s)" %
        (np.median(sp_r), np.percentile(sp_r, 90), sp_r.max(), names[int(sp_r.argmax())]))
    worst = np.argsort(-sp_t)[:8]
    say("    平移 spread 最大的 8 根骨:")
    for j in worst:
        say("      %-26s max|Δt|=%.4f  max夹角=%.3f°" % (names[j], sp_t[j], sp_r[j]))
    res["spread_t"] = sp_t.tolist(); res["spread_r_deg"] = sp_r.tolist()

    # ---- [B] frame0 vs bind ----
    # 基准 frame0：取各动作 frame0 的逐骨中位（稳定性[A]会说明这步差多少）
    T0m = np.median(np.stack([T0s[a] for a in anims]), axis=0)
    R0m = np.stack([R0s[a] for a in anims])  # 用 idle01 代表做旋转基准（下面先验证差异小）
    G0i = G0s["idle01"]
    say("\n[B] frame0(idle01) vs bind B（原始 .ani 轴）")
    dt = np.linalg.norm(G0i[:, :3, 3] - B[:, :3, 3], axis=1)
    dr = np.array([ang(G0i[j, :3, :3] @ B[j, :3, :3].T) for j in range(NJ)])
    say("    逐骨 |Δt|: min %.4f median %.4f max %.4f ; =0(<1e-6) 的骨 %d" %
        (dt.min(), np.median(dt), dt.max(), int((dt < 1e-6).sum())))
    say("    逐骨旋转角差: min %.3f° median %.3f° max %.3f° ; <0.01° 的骨 %d" %
        (dr.min(), np.median(dr), dr.max(), int((dr < 0.01).sum())))
    # E_j = G0_j B_j^{-1}：bind 锚在 frame0 的误差
    E = np.stack([G0i[j] @ D["Binv"][j] for j in range(NJ)])
    Ea = np.array([ang(E[j, :3, :3]) for j in range(NJ)])
    Et = np.linalg.norm(E[:, :3, 3], axis=1)
    # E 旋转部分是否同一个旋转：逐骨与「全体平均旋转」的最大夹角
    Ravg = E[:, :3, :3].mean(0)
    U, _, Vt = np.linalg.svd(Ravg)
    Rproj = U @ np.eye(3) @ Vt if np.linalg.det(U @ Vt) > 0 else U @ np.diag([1, 1, -1]) @ Vt
    dE = np.array([ang(E[j, :3, :3] @ Rproj.T) for j in range(NJ)])
    say("    E=G0·B⁻¹（bind 锚的 frame0 误差）: 旋转角 min %.2f° med %.2f° max %.2f°；"
        "E 平移 |Et| med %.4f max %.4f" % (Ea.min(), np.median(Ea), Ea.max(), np.median(Et), Et.max()))
    say("    E 的旋转部分逐骨互差（vs 最近正交平均）: median %.3f° max %.3f° -> %s" %
        (np.median(dE), dE.max(),
         "同一个全局旋转" if dE.max() < 1.0 else "逐骨不同，不是单一全局刚体差"))
    # 平移部分是否同一个平移
    tmed = np.median(E[:, :3, 3], axis=0)
    dtE = np.linalg.norm(E[:, :3, 3] - tmed[None], axis=1)
    say("    E 的平移部分逐骨互差: median %.4f max %.4f -> %s" %
        (np.median(dtE), dtE.max(), "同一个全局平移" if dtE.max() < 1e-3 else "逐骨不同"))
    worst = np.argsort(-dt)[:10]
    say("    |Δt| 最大的 10 根骨（frame0 vs bind）:")
    for j in worst:
        say("      %-26s |Δt|=%.4f  角差=%7.2f°  |Et|=%.4f  E角=%7.2f°" %
            (names[j], dt[j], dr[j], Et[j], Ea[j]))
    res["f0_vs_bind_dt"] = dt.tolist(); res["f0_vs_bind_dr_deg"] = dr.tolist()
    res["E_ang_deg"] = Ea.tolist(); res["E_t"] = E[:, :3, 3].tolist()

    # ---- [C] 物理重心判据 ----
    if not len(covj):
        say("\n[C] %s 无蒙皮顶点（全部绑根骨 000），重心判据与蒙皮统计跳过" % tag)
        RESULT[tag] = res
        say("")
        continue
    offB = np.linalg.norm(C[covj] - B[covj, :3, 3], axis=1)
    say("\n[C] 静态加权重心判据 |C_j-骨位|（covered=%d 根，剔根骨；bind 参照 0.1488）" % len(covj))
    say("    bind  B       : mean %.4f median %.4f max %.4f" %
        (offB.mean(), np.median(offB), offB.max()))
    off0 = np.linalg.norm(C[covj] - G0i[covj, :3, 3], axis=1)
    say("    frame0 原始轴 : mean %.4f median %.4f max %.4f" %
        (off0.mean(), np.median(off0), off0.max()))
    # 48 个带符号置换 Q：t -> Q^T t
    rows = []
    for pm in itertools.permutations(range(3)):
        for sg in itertools.product((1.0, -1.0), repeat=3):
            Q = perm_R(pm, sg)
            tQ = (Q.T @ G0i[covj, :3, 3].T).T
            off = np.linalg.norm(C[covj] - tQ, axis=1)
            rows.append((float(off.mean()), pm, sg, float(off.max())))
    rows.sort()
    say("    frame0 经 48 个带符号置换 Q (t->Q^T t) 映射后，最优 6 个：")
    for m, pm, sg, mx in rows[:6]:
        det = round(float(np.linalg.det(perm_R(pm, sg))))
        say("      Q=(%s)%s det%+d : mean %.4f max %.4f" %
            (",".join(map(str, pm)), "".join("+" if x > 0 else "-" for x in sg), det, m, mx))
    res["centroid_bind_mean"] = float(offB.mean())
    res["centroid_f0_raw_mean"] = float(off0.mean())
    res["centroid_f0_topQ"] = [{"mean": m, "perm": list(pm), "signs": list(sg), "max": mx}
                               for m, pm, sg, mx in rows[:6]]
    # 最优 Q 下的解剖高度
    Qb = perm_R(rows[0][1], rows[0][2])
    tQ = (Qb.T @ G0i[:, :3, 3].T).T
    for nm in ("bip01_pelvis", "bip01_head", "bip01_l_foot", "bip01_l_toe0", "bip01_l_hand"):
        j = names.index(nm)
        say("      %-16s frame0@Q t=%s" % (nm, np.round(tQ[j], 4)))
    say("      (bind 参照: pelvis %s head %s l_foot %s)" %
        (np.round(B[names.index("bip01_pelvis"), :3, 3], 4),
         np.round(B[names.index("bip01_head"), :3, 3], 4),
         np.round(B[names.index("bip01_l_foot"), :3, 3], 4)))

    # ---- [D] 跨动作锚互用（idle01 的 frame0 锚借给其它动作）----
    say("\n[D] 跨动作锚互用（原始轴 R=I）：A_j = G0^idle_j^{-1}，其它动作 frame0 处的误差")
    AncI = np.stack([np.linalg.inv(G0s["idle01"][j]) for j in range(NJ)])
    M0 = np.stack([G0s[a][j] @ AncI[j] for a in anims for j in range(NJ)])
    M0 = M0.reshape(len(anims), NJ, 4, 4)
    for i, a in enumerate(anims):
        rot = [ang(M0[i, j, :3, :3]) for j in range(NJ)]
        tr = np.linalg.norm(M0[i, :, :3, 3], axis=1)
        say("    %-16s frame0处 M=G0^a·A^idle: 旋转 max %.3f°  平移 max %.4f (med %.4f)" %
            (a, max(rot), tr.max(), np.median(tr)))
    res["anchor_share"] = {
        a: {"rot_max_deg": float(max(ang(M0[i, j, :3, :3]) for j in range(NJ))),
            "t_max": float(np.linalg.norm(M0[i, :, :3, 3], axis=1).max())}
        for i, a in enumerate(anims)}
    RESULT[tag] = res
    say("")

json.dump(RESULT, open(r"D:\TLGL\.scratch\ani_axis\k1_frame0.json", "w"))
open(r"D:\TLGL\.scratch\ani_axis\k1_frame0.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k1_frame0.txt / k1_frame0.json")
