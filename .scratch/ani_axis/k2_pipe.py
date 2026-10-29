"""K-递归解 × mat64 对照 + 全管线闭合检验（2026-10-07）。

假设 H_biped：.ani 局部帧 = Max Biped 式骨坐标系（+X 指向子骨，见常量偏移沿 +X），
bind/mesh 帧 = 引擎帧；两者之间每骨差一个常量旋转 K_j（无「漂亮」结构可言，
之前拿「距带符号置换的角」当判据是选错了尺子）。K 由 K 递归精确可解：
    K_j = L_j(0)^{-1} · K_p · blocal_j,  K_root = I（corrected_local = K_p^{-1} L_j K_j = bind 局部）。

本脚本：
  [P] 三种 .ani 读法（as-is / rowcol / inv）各自解 K，与 mat64 对照（K, Kᵀ vs mat64, mat64ᵀ）。
  [Q] mat64 与 K 的轴角数值（pelvis/bone01 等肉眼比对）。
  [R] 决定性闭合测试：corrected world W_j(f) = K_p^{-1} G_raw_j(f) K_j，
      以 IBM（bind 锚）蒙皮，量 idle01/walk 的蒙皮位移与重心残差。
      若位移塌到运动幅度（~0.1-0.2），K 修正就是引擎复合方式 —— 全线贯通。
输出 k2_pipe.txt
"""
import sys, json, math
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, locals_frames, compose_worlds, ang, skin, centroid_resid

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


def mat_inv_affine(M):
    R = M[:3, :3]; t = M[:3, 3]; Ri = np.linalg.inv(R)
    O = np.eye(4); O[:3, :3] = Ri; O[:3, 3] = -Ri @ t
    return O


def axang(R):
    """轴角表示（便于肉眼比对）。"""
    a = ang(R)
    if a < 1e-6:
        return "(I)"
    c = math.cos(math.radians(a))
    k = 0.5 * (R[0, 0] + R[1, 1] + R[2, 2] - 3 * c)
    if abs(k) < 1e-9:
        return "(%.1f°, 轴~180°型)" % a
    x = (R[2, 1] - R[1, 2]) / (2 * k); y = (R[0, 2] - R[2, 0]) / (2 * k); z = (R[1, 0] - R[0, 1]) / (2 * k)
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return "(%.1f° | %.2f,%.2f,%.2f)" % (a, x / n, y / n, z / n)


D = build(GLBS["yifu"])
AN = read_anims(D)
NJ, names, jpar = D["NJ"], D["names"], D["jpar"]
B, IBM, C = D["B"], D["IBM"], D["C"]
covj = np.where(D["cov"])[0]; covj = covj[covj != 0]
Rb = D["blocal"][:, :3, :3].copy(); blt = D["blocal"][:, :3, 3].copy()
ph = [j for j in range(NJ) if np.linalg.norm(blt[j]) < 1e-6 and np.abs(Rb[j] - np.eye(3)).max() < 1e-5]
NF = len(list(AN["idle01"].values())[0]["translation"][0])
Lrot, Ltr, has = locals_frames(AN["idle01"], D, NF)
k2 = json.load(open(r"D:\TLGL\.scratch\ani_axis\k2_mat64_yifu.json"))
mats = {e["name"]: np.array(e["mats"][0]).reshape(4, 4) for e in k2["entries"] if e["mats"]}


def solve_K(reading):
    K = {}
    for j in D["seq"]:
        p = jpar[j]
        L = np.eye(4)
        if reading == "asis":
            L[:3, :3] = Lrot[j, 0]; L[:3, 3] = Ltr[j, 0]
        elif reading == "rowcol":
            L[:3, :3] = Lrot[j, 0].T; L[:3, 3] = Ltr[j, 0]
        elif reading == "inv":
            L = mat_inv_affine(np.eye(4) if False else
                               np.array([[0, 0, 0, 0]] * 4))  # placeholder 不用
        if p < 0:
            K[j] = np.eye(4)
        else:
            Lj = np.eye(4)
            if reading == "asis":
                Lj[:3, :3] = Lrot[j, 0]; Lj[:3, 3] = Ltr[j, 0]
            elif reading == "rowcol":
                Lj[:3, :3] = Lrot[j, 0].T; Lj[:3, 3] = Ltr[j, 0]
            elif reading == "inv":
                Lj = mat_inv_affine(np.block([[Lrot[j, 0], Ltr[j, 0][:, None]],
                                              [np.zeros((1, 3)), np.ones((1, 1))]]))
            K[j] = np.linalg.inv(Lj) @ K[p] @ D["blocal"][j]
    return K


say("=== [P] 三种读法的 K 与 mat64 对照（只看 K 干净的骨 ∩ mat64 骨）===")
clean = [j for j in range(NJ) if j not in ph and jpar[j] >= 0 and jpar[j] not in ph]
for reading in ("asis", "rowcol", "inv"):
    K = solve_K(reading)
    say("  读法 %s:" % reading)
    for j in clean:
        nm = names[j]
        if nm in mats:
            rm = mats[nm]
            for tagM, Rm in (("mat64", rm[:3, :3].T), ("mat64T", rm[:3, :3])):
                say("    %-24s K %s  vs %s: %.2f°" % (nm, axang(K[j][:3, :3]), tagM,
                                                      ang(K[j][:3, :3] @ Rm.T)))

say("\n=== [Q] 参考数值 ===")
K = solve_K("asis")
for nm in ("bip01_pelvis", "bone01", "bip01_r_finger1"):
    j = names.index(nm)
    say("  %-16s K(asis) %s" % (nm, axang(K[j][:3, :3])))
    if nm in mats:
        say("  %-16s mat64   %s" % (nm, axang(mats[nm][:3, :3].T)))

say("\n=== [R] 全管线闭合测试：corrected world = K_p^-1 · G_raw · K_j，IBM 锚蒙皮 ===")
use = (~D["root_only"]) & (D["wsum"] > 0.999)


def pipeline(reading, anim):
    K = solve_K(reading)
    nf = len(list(AN[anim].values())[0]["translation"][0])
    lr, lt, _ = locals_frames(AN[anim], D, nf)
    # 原始复合
    G = compose_worlds(lr, lt, D)
    # corrected: W_j = K_{parent(j)}^{-1} G_j K_j（K_root=I）
    W = np.empty_like(G)
    for j in range(NJ):
        p = jpar[j]
        Cp = K[p] if p >= 0 else np.eye(4)
        W[j] = np.linalg.inv(Cp) @ G[j] @ K[j]
    Vp = skin(W, IBM, D)
    disp = np.linalg.norm(Vp - D["POS"][:, None, :], axis=2)
    fm = disp[use].mean(0)
    d2 = centroid_resid(W, Vp, D)
    # frame0 vs bind
    dt0 = np.linalg.norm(W[:, 0, :3, 3] - B[:, :3, 3], axis=1)
    return fm, disp, d2, dt0


for reading in ("asis", "rowcol"):
    for anim in ("idle01", "walk"):
        fm, disp, d2, dt0 = pipeline(reading, anim)
        say("  [%s/%s] 帧均位移 %.4f~%.4f 全max %.4f | 重心残差 mean %.4f | frame0 |Δt| med %.4f max %.4f"
            % (reading, anim, fm.min(), fm.max(), disp[use].max(), d2[covj].mean(),
               np.median(dt0), dt0.max()))

say("\n  参照（上一班）：raw+bind 1.7471~1.8201/2.4338；raw+frame0锚 0.0000~0.2309/0.8489；"
    "\n  静置重心参照 0.1488")

open(r"D:\TLGL\.scratch\ani_axis\k2_pipe.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k2_pipe.txt")
