"""刀1 深挖（2026-10-07）：
  [E] 6 条 frame0 与 idle01 不同的动作：逐骨看局部差（|Δt| / 旋转角差），
      判「差在运动骨（pelvis/footsteps）」还是「差在全身」；并查 6 条之间是否互相相同。
  [F] K 递归：把「.ani 局部(第0帧)」与「bind 局部」沿树对齐，解逐骨常量 K_j：
      定义 corrected_local_j = K_p^{-1} · L_j(0) · K_j，要求 corrected = bind 局部，
      得 K_j = L_j(0)^{-1} · K_p · blocal_j，K_root = I。
      三种 .ani 局部读法都试：as-is 列口径 / 行转列(R^T,t) / 全仿射逆。
      看 K_j 是否「漂亮」：全部同一个旋转（=全局轴差，刀4 有解）/
      逐骨不同但都是带符号置换（=逐骨轴，刀2）/ 乱旋转（=真 rest pose 差）。
      只对「自有记录且父有记录」的骨（blocal 精确）判 niceness。
输出 k1_kstruct.txt
"""
import sys, json, itertools, math
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, locals_frame0, ang, perm_R

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


D = build(GLBS["yifu"])
AN = read_anims(D)
NJ, names, jpar = D["NJ"], D["names"], D["jpar"]
anims = sorted(AN)

placeholder = []
for j in range(NJ):
    bl = D["blocal"][j]
    if np.linalg.norm(bl[:3, 3]) < 1e-6 and np.abs(bl[:3, :3] - np.eye(3)).max() < 1e-5:
        placeholder.append(j)
say("占位骨(局部=I, 无记录) %d 根: %s" % (len(placeholder), ", ".join(names[j] for j in placeholder)))
hasrec = [j for j in range(NJ) if j not in placeholder]
clean = [j for j in hasrec if jpar[j] >= 0 and jpar[j] in hasrec]
say("自有记录且父有记录（blocal 精确）的骨 %d 根: %s" % (len(clean), ", ".join(names[j] for j in clean)))

# ---- [E] frame0 局部差逐骨 ----
say("\n[E] 各动作 frame0 局部 vs idle01 frame0 局部（原始数据，无任何复合）")
Lr0 = {}; Lt0 = {}
for a in anims:
    Lr0[a], Lt0[a], _ = locals_frame0(AN[a], D)

for a in anims:
    dt = np.array([np.linalg.norm(Lt0[a][j] - Lt0["idle01"][j]) for j in range(NJ)])
    dr = np.array([ang(Lr0[a][j] @ Lr0["idle01"][j].T) for j in range(NJ)])
    nb = int(((dt > 1e-6) | (dr > 0.01)).sum())
    say("  %-16s 局部有差的骨 %2d/45: max|Δt|=%.4f max角差=%.2f°" % (a, nb, dt.max(), dr.max()))
    if 0 < nb <= 8:
        for j in range(NJ):
            if dt[j] > 1e-6 or dr[j] > 0.01:
                say("      %-26s |Δt|=%.4f 角差=%7.2f°" % (names[j], dt[j], dr[j]))

# 6 条差异动作之间是否互同
group = ["behit01", "dead", "flyingdeadbegin", "idle02", "run", "walk"]
say("\n[E2] 差异动作两两之间 frame0 局部差（有差骨数 / max角差）")
for a, b in itertools.combinations(group, 2):
    dt = np.array([np.linalg.norm(Lt0[a][j] - Lt0[b][j]) for j in range(NJ)])
    dr = np.array([ang(Lr0[a][j] @ Lr0[b][j].T) for j in range(NJ)])
    nb = int(((dt > 1e-6) | (dr > 0.01)).sum())
    say("  %-16s vs %-16s 有差骨 %2d  max|Δt|=%.4f max角差=%.2f°" % (a, b, nb, dt.max(), dr.max()))

# ---- [F] K 递归 ----
say("\n[F] K 递归（corrected_local = K_p^{-1}·L_j(0)·K_j =? bind 局部；K_j = L_j(0)^{-1}·K_p·blocal_j）")


def mat_inv_affine(M):
    R = M[:3, :3]; t = M[:3, 3]
    Ri = np.linalg.inv(R)
    O = np.eye(4); O[:3, :3] = Ri; O[:3, 3] = -Ri @ t
    return O


def run_variant(tagv, make_local):
    """make_local(j) -> 4x4 的 .ani 第0帧局部（列口径）。返回 K_j dict。"""
    K = {}
    for j in D["seq"]:
        p = jpar[j]
        if p < 0:
            K[j] = np.eye(4)
        else:
            L = make_local(j)
            K[j] = np.linalg.inv(L) @ K[p] @ D["blocal"][j]
    return K


def report(tagv, K):
    Kr = {j: K[j][:3, :3] for j in range(NJ)}
    # niceness 1: K_j 之间的最大互差（clean 集内）-> 是否同一个旋转
    mx = 0.0
    for a, b in itertools.combinations(clean, 2):
        mx = max(mx, ang(Kr[a] @ Kr[b].T))
    # niceness 2: K_j 距最近的带符号置换的角度
    perms = []
    for pm in itertools.permutations(range(3)):
        for sg in itertools.product((1.0, -1.0), repeat=3):
            perms.append(perm_R(pm, sg))
    near = []
    for j in clean:
        best = min(ang(Kr[j] @ Q.T) for Q in perms)
        near.append((best, j))
    near.sort()
    n_perm = int(sum(1 for b, _ in near if b < 1.0))
    say("  [%s] clean 集 %d 根: K 互差 max %.2f° | 距最近带符号置换 <1° 的 %d 根 (median %.3f° max %.3f°)"
        % (tagv, len(clean), mx, n_perm, np.median([b for b, _ in near]), near[-1][0]))
    say("      逐骨（按距最近置换角排序, 前12 + 最差3）:")
    for b, j in near[:12] + near[-3:]:
        # 找到最近置换
        bestQ, besta = None, 1e9
        for pm in itertools.permutations(range(3)):
            for sg in itertools.product((1.0, -1.0), repeat=3):
                Q = perm_R(pm, sg)
                a = ang(Kr[j] @ Q.T)
                if a < besta:
                    besta, bestQ = a, (pm, sg)
        say("        %-26s 角差%7.2f°  最近置换 (%s)%s" %
            (names[j], b, bestQ[0], tuple(int(x) for x in bestQ[1])))
    return mx, n_perm


def mk_asis(j):
    M = np.eye(4); M[:3, :3] = Lr0["idle01"][j]; M[:3, 3] = Lt0["idle01"][j]
    return M


def mk_rowcol(j):
    M = np.eye(4); M[:3, :3] = Lr0["idle01"][j].T; M[:3, 3] = Lt0["idle01"][j]
    return M


def mk_inv(j):
    return mat_inv_affine(mk_asis(j))


def mk_inv_rowcol(j):
    return mat_inv_affine(mk_rowcol(j))


for tagv, fn in (("as-is(R,t)", mk_asis), ("row->col(Rᵀ,t)", mk_rowcol),
                 ("inv(R,t)", mk_inv), ("inv+rowcol", mk_inv_rowcol)):
    K = run_variant(tagv, fn)
    report(tagv, K)

open(r"D:\TLGL\.scratch\ani_axis\k1_kstruct.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k1_kstruct.txt")
