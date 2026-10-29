"""wave20：把带符号置换 A_j 代进复合，且同一 A 沿子树共用（上一班 perbone_axis 没传播，结论不算）。

模型（列向量、4x4 共轭）：
  根：A_parent := A_j
  Δ'_j = A_parent^{-1} · Δ_j · A_j
       R' = A_p^{-1} R_ani A_j
       t' = A_p^{-1} t_ani
全身同一 A 时退化为 A^{-1} Δ A。大肢分组时只在组界 A_parent ≠ A_j。

搜索有界：A 只取 48 个带符号坐标置换；先全身一个 A，再五大肢各一个 A
（坐标下降 + 脊柱×单肢 48²，不给每骨独立任意旋转）。

指标：
  1) frame0 世界骨位 vs bind 骨位 / bind 骨长，中位 < 0.05
  2) 蒙皮帧均位移不回到 ~1.9
两条同时成立才 🟢。
"""
import json, math, itertools, collections, sys, os, io
import numpy as np
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, quat_mat

OUT_DIR = r"D:\TLGL\.scratch\wave20\perbone"
ANIM = sys.argv[1] if len(sys.argv) > 1 else "idle01"
PASS_F0 = 0.05
PASS_SKIN = 1.0          # 明确低于 ~1.75 基线 / ~1.9 上一班炸值
SKIN_BROKEN = 1.5        # 「回到 ~1.9」的判定带

D = build()
NJ = D["NJ"]
names = D["names"]
jpar = D["jpar"]
B = D["B"]
IBM = D["IBM"]
per = read_anims(D)[ANIM]
NF = len(per[sorted(per)[0]]["translation"][1])

use = (~D["root_only"]) & (D["wsum"] > 0.999)
POS = D["POS"][use]
W = D["Wm"][use]
JSL = D["JOI"][use]
WAL = D["WEI"][use]
NV = len(POS)
HOM = np.concatenate([POS, np.ones((NV, 1))], axis=1)
jsum = W.sum(0)
covj = np.where(jsum > 1e-9)[0]
covj = covj[covj != 0]

Lrot = np.tile(np.eye(3), (NJ, NF, 1, 1))
Ltr = np.zeros((NJ, NF, 3))
has = np.zeros(NJ, bool)
for j, d in per.items():
    has[j] = True
    Ltr[j] = d["translation"][1][:NF]
    Lrot[j] = np.stack([quat_mat(q) for q in d["rotation"][1][:NF]])
for j in range(NJ):
    if not has[j]:
        Lrot[j] = D["blocal"][j][:3, :3]
        Ltr[j] = D["blocal"][j][:3, 3]

seq, done = [], set()
while len(seq) < NJ:
    for j in range(NJ):
        p = jpar[j]
        if j not in done and (p < 0 or p in done):
            seq.append(j)
            done.add(j)
            break

children = [[] for _ in range(NJ)]
for j, p in enumerate(jpar):
    if p >= 0:
        children[p].append(j)

name_i = {n: i for i, n in enumerate(names)}


def subtree(root):
    out, st = [], [root]
    while st:
        j = st.pop()
        out.append(j)
        st.extend(children[j])
    return out


GROUPS = ("spine", "l_arm", "r_arm", "l_leg", "r_leg")
LIMB_ROOTS = {
    "l_arm": "bip01_l_clavicle",
    "r_arm": "bip01_r_clavicle",
    "l_leg": "bip01_l_thigh",
    "r_leg": "bip01_r_thigh",
}
gof = ["spine"] * NJ
for g, rn in LIMB_ROOTS.items():
    if rn not in name_i:
        raise SystemExit("missing limb root %s" % rn)
    for j in subtree(name_i[rn]):
        gof[j] = g
gix = {g: i for i, g in enumerate(GROUPS)}
gof_i = np.array([gix[g] for g in gof], int)

# bind 骨长：父子世界原点距。塌缩骨不进中位（否则 /0 或假 0）。
blen = np.zeros(NJ)
for j in range(NJ):
    p = jpar[j]
    if p < 0:
        blen[j] = float(np.linalg.norm(B[j, :3, 3]))
    else:
        blen[j] = float(np.linalg.norm(B[j, :3, 3] - B[p, :3, 3]))
valid = (blen > 1e-4) & np.array([n != "000" for n in names])
valid_idx = np.where(valid)[0]

AX = []
for pm in itertools.permutations(range(3)):
    for sg in itertools.product((1.0, -1.0), repeat=3):
        A = np.zeros((3, 3))
        for i in range(3):
            A[i, pm[i]] = sg[i]
        AX.append((A, pm, tuple(int(x) for x in sg), float(np.linalg.det(A))))
AXM = np.stack([a[0] for a in AX])  # (48,3,3)
N48 = len(AX)


def tag(k):
    _, pm, sg, det = AX[k]
    return "%s%s det%+.0f" % (pm, sg, det)


def compose(Aj, frames=None):
    """Aj: (NJ,3,3)。frames=None 全帧，否则切片。A_parent(root)=A_j。"""
    if frames is None:
        rot, tr = Lrot, Ltr
        nf = NF
    else:
        rot, tr = Lrot[:, frames], Ltr[:, frames]
        nf = rot.shape[1]
    Ap = Aj.copy()
    for j in range(NJ):
        p = jpar[j]
        if p >= 0:
            Ap[j] = Aj[p]
    Apt = np.transpose(Ap, (0, 2, 1))
    Lin = np.einsum("jab,jfbc,jcd->jfad", Apt, rot, Aj)
    T = np.einsum("jab,jfb->jfa", Apt, tr)
    Loc = np.zeros((NJ, nf, 4, 4))
    Loc[:, :, :3, :3] = Lin
    Loc[:, :, :3, 3] = T
    Loc[:, :, 3, 3] = 1.0
    G = np.empty_like(Loc)
    for j in seq:
        p = jpar[j]
        G[j] = Loc[j] if p < 0 else np.matmul(G[p], Loc[j])
    return G


def compose_own(Aj, frames=None):
    """对照：每骨只用自己的 A_j^{-1} Δ A_j（组界不混父）。全身同时退化为同一式。"""
    if frames is None:
        rot, tr = Lrot, Ltr
        nf = NF
    else:
        rot, tr = Lrot[:, frames], Ltr[:, frames]
        nf = rot.shape[1]
    Apt = np.transpose(Aj, (0, 2, 1))
    Lin = np.einsum("jab,jfbc,jcd->jfad", Apt, rot, Aj)
    T = np.einsum("jab,jfb->jfa", Apt, tr)
    Loc = np.zeros((NJ, nf, 4, 4))
    Loc[:, :, :3, :3] = Lin
    Loc[:, :, :3, 3] = T
    Loc[:, :, 3, 3] = 1.0
    G = np.empty_like(Loc)
    for j in seq:
        p = jpar[j]
        G[j] = Loc[j] if p < 0 else np.matmul(G[p], Loc[j])
    return G


def f0_rel(G0):
    """G0: (NJ,4,4) frame0 世界。返回 per-bone 相对差与汇总。"""
    dt = np.linalg.norm(G0[:, :3, 3] - B[:, :3, 3], axis=1)
    rel = np.full(NJ, np.nan)
    rel[valid] = dt[valid] / blen[valid]
    v = rel[valid]
    skip_root = np.array([n not in ("000", "bip01") for n in names])
    dt_med_all = float(np.median(dt[skip_root]))
    return dict(
        per=rel, dt=dt,
        med=float(np.median(v)), mean=float(np.mean(v)),
        p90=float(np.percentile(v, 90)), mx=float(np.max(v)),
        dt_med=dt_med_all,
        n=int(valid.sum()),
        n_lt_005=int(np.sum(v < 0.05)),
        n_lt_010=int(np.sum(v < 0.10)),
        n_lt_050=int(np.sum(v < 0.50)),
    )


def skin_from_G(G):
    nf = G.shape[1]
    P = np.stack([G[j] @ IBM[j] for j in range(NJ)])
    Vp = np.zeros((NV, nf, 3))
    for s in range(4):
        Vp += WAL[:, s][:, None, None] * np.einsum(
            "vfij,vj->vfi", P[JSL[:, s]], HOM)[:, :, :3]
    disp = np.linalg.norm(Vp - POS[:, None, :], axis=2)
    fm = disp.mean(0)
    return dict(
        fm_min=float(fm.min()), fm_max=float(fm.max()),
        fm_mean=float(fm.mean()), gmax=float(disp.max()),
        f0=float(fm[0]),
    )


def Aj_from_gids(gids):
    """gids: length-5 ints into AX."""
    Aj = np.empty((NJ, 3, 3))
    for gi, k in enumerate(gids):
        Aj[gof_i == gi] = AXM[k]
    return Aj


def pack(label, gids, G, skin, extra=None):
    f0 = f0_rel(G[:, 0] if G.ndim == 4 else G)
    rec = dict(
        label=label,
        gids=[int(x) for x in gids],
        groups={GROUPS[i]: tag(int(gids[i])) for i in range(5)},
        dets=[AX[int(k)][3] for k in gids],
        f0_med=f0["med"], f0_mean=f0["mean"], f0_p90=f0["p90"], f0_max=f0["mx"],
        f0_dt_med=f0["dt_med"],
        f0_n=f0["n"], f0_n_lt_005=f0["n_lt_005"], f0_n_lt_010=f0["n_lt_010"],
        f0_n_lt_050=f0["n_lt_050"],
        skin_fm_mean=skin["fm_mean"], skin_fm_min=skin["fm_min"],
        skin_fm_max=skin["fm_max"], skin_gmax=skin["gmax"], skin_f0=skin["f0"],
        pass_f0=bool(f0["med"] < PASS_F0),
        pass_skin=bool(skin["fm_mean"] < PASS_SKIN),
        skin_broken=bool(skin["fm_mean"] >= SKIN_BROKEN),
    )
    rec["both"] = bool(rec["pass_f0"] and rec["pass_skin"])
    if extra:
        rec.update(extra)
    rec["_per"] = f0["per"]
    rec["_dt"] = f0["dt"]
    return rec


def eval_gids(gids, full_skin=True, mode="chain"):
    Aj = Aj_from_gids(gids)
    if full_skin:
        G = compose(Aj) if mode == "chain" else compose_own(Aj)
        sk = skin_from_G(G)
    else:
        G = compose(Aj, frames=[0]) if mode == "chain" else compose_own(Aj, frames=[0])
        sk = skin_from_G(G)
        sk = dict(fm_min=sk["f0"], fm_max=sk["f0"], fm_mean=sk["f0"],
                  gmax=sk["gmax"], f0=sk["f0"])
    return G, sk


def fmt_row(r):
    return ("%-28s f0_med=%.4f mean=%.4f p90=%.4f max=%.4f  "
            "lt.05=%d/%d  skin_mean=%.4f (%.4f~%.4f) gmax=%.4f  %s%s" % (
                r["label"][:28], r["f0_med"], r["f0_mean"], r["f0_p90"], r["f0_max"],
                r["f0_n_lt_005"], r["f0_n"], r["skin_fm_mean"], r["skin_fm_min"],
                r["skin_fm_max"], r["skin_gmax"],
                "[BOTH]" if r["both"] else (
                    ("[f0-ok]" if r["pass_f0"] else "") + ("[skin-ok]" if r["pass_skin"] else "")),
                "  SKIN~1.9" if r["skin_broken"] else ""))


lines = []


def P(*a):
    s = " ".join(str(x) for x in a) if len(a) != 1 else str(a[0])
    print(s, flush=True)
    lines.append(s)


P("=== wave20 perbone 子树传播  anim=%s  NF=%d NJ=%d valid_bones=%d ===" % (
    ANIM, NF, NJ, int(valid.sum())))
P("PASS: f0_med < %.2f  AND  skin_mean < %.1f  (broken if skin >= %.1f)" % (
    PASS_F0, PASS_SKIN, SKIN_BROKEN))
P("")
P("[分组] 脊柱=其余；四肢=从下列根沿子树")
for g in GROUPS:
    js = [names[j] for j in range(NJ) if gof[j] == g]
    P("  %-6s %2d  %s" % (g, len(js), ", ".join(js)))
P("")
P("[bind 骨长] 进中位的 %d 根（blen>1e-4 且非 000）；排除 %s" % (
    int(valid.sum()),
    ", ".join("%s(%.1e)" % (names[j], blen[j]) for j in range(NJ) if not valid[j])))

# ---------- 0) 对照：A=I 与上一班全局冠军（一致共轭 vs 他们的 tv=1 混用）----------
results = []


def find_I():
    for k, a in enumerate(AX):
        if a[1] == (0, 1, 2) and a[2] == (1, 1, 1):
            return k
    return 0


def find_pm(pm, sg):
    for k, a in enumerate(AX):
        if a[1] == pm and a[2] == sg:
            return k
    raise KeyError((pm, sg))


kI = find_I()
kR = find_pm((2, 0, 1), (1, 1, 1))  # 上一班全局冠军

G, sk = eval_gids([kI] * 5, True)
r = pack("基线 A=I", [kI] * 5, G, sk)
results.append(r)
P("\n" + fmt_row(r))

G, sk = eval_gids([kR] * 5, True)
r = pack("全身 上一班冠军(2,0,1)+++ 一致共轭=tv2", [kR] * 5, G, sk)
results.append(r)
P(fmt_row(r))

# 上一班混用：旋转 A^{-1} M A 但 t' = A t（tv=1）。只作对照，不进搜索主结论。
def compose_mixed_tv1(A, frames=None):
    if frames is None:
        rot, tr = Lrot, Ltr
        nf = NF
    else:
        rot, tr = Lrot[:, frames], Ltr[:, frames]
        nf = rot.shape[1]
    At = A.T
    Lin = np.matmul(np.matmul(At, rot), A)
    T = tr @ At  # t' = A t
    Loc = np.zeros((NJ, nf, 4, 4))
    Loc[:, :, :3, :3] = Lin
    Loc[:, :, :3, 3] = T
    Loc[:, :, 3, 3] = 1.0
    G = np.empty_like(Loc)
    for j in seq:
        p = jpar[j]
        G[j] = Loc[j] if p < 0 else np.matmul(G[p], Loc[j])
    return G

Gmix = compose_mixed_tv1(AXM[kR])
skmix = skin_from_G(Gmix)
rmix = pack("对照 上一班混用 tv=1 R=(2,0,1)+++", [kR] * 5, Gmix, skmix,
            extra={"note": "rotation A^{-1}MA but t'=A t; 不进主搜索"})
results.append(rmix)
P(fmt_row(rmix) + "  [对照·不进主搜索]")

# ---------- 1) 全身一个 A：48 ----------
P("\n=== 1) 全身一个 A（48 带符号置换，一致 4x4 共轭）===")
body = []
for k in range(N48):
    gids = [k] * 5
    G, sk = eval_gids(gids, True)
    r = pack("全身 " + tag(k), gids, G, sk, extra={"phase": "body"})
    body.append(r)
    results.append(r)

body_by_f0 = sorted(body, key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
body_by_sk = sorted(body, key=lambda x: (x["skin_fm_mean"], x["f0_med"]))
body_both = [x for x in body if x["both"]]
P("  按 f0_med 前 8：")
for r in body_by_f0[:8]:
    P("    " + fmt_row(r))
P("  按 skin_mean 前 8：")
for r in body_by_sk[:8]:
    P("    " + fmt_row(r))
P("  同时过线：%d / 48" % len(body_both))
best_body_f0 = body_by_f0[0]
best_body_sk = body_by_sk[0]

# ---------- 2) 五大肢：从最佳全身出发坐标下降 ----------
P("\n=== 2) 大肢分组各一个 A（坐标下降，每轮 5×48）===")


def descent(start_gids, rounds=4, seed_label=""):
    cur = list(start_gids)
    G, sk = eval_gids(cur, True)
    best = pack("肢 " + seed_label + " start " + "/".join(tag(k) for k in cur),
                cur, G, sk, extra={"phase": "limb_cd"})
    hist = [best]
    P("  start: " + fmt_row(best))
    for rd in range(rounds):
        improved = False
        for gi in range(5):  # spine first
            local = []
            for k in range(N48):
                trial = list(cur)
                trial[gi] = k
                G, sk = eval_gids(trial, full_skin=False)  # frame0 skin + f0
                r = pack("cd r%d %s %s" % (rd, GROUPS[gi], tag(k)), trial, G, sk,
                         extra={"phase": "limb_cd_probe"})
                local.append(r)
            # 主目标：在皮肤不炸的前提下压 f0_med；若全炸则仍记最小 f0
            ok = [x for x in local if x["skin_fm_mean"] < PASS_SKIN]
            pool = ok if ok else local
            # 同时跟踪「无约束最小 f0」和「皮肤合格最小 f0」
            pick = min(pool, key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
            unconstrained = min(local, key=lambda x: x["f0_med"])
            if unconstrained["gids"][gi] != cur[gi]:
                P("    r%d %s 无约束最优 %s f0_med=%.4f skin_f0=%.4f%s" % (
                    rd, GROUPS[gi], tag(unconstrained["gids"][gi]),
                    unconstrained["f0_med"], unconstrained["skin_f0"],
                    "  SKIN_BROKEN" if unconstrained["skin_broken"] else ""))
            if pick["gids"][gi] != cur[gi]:
                cur[gi] = pick["gids"][gi]
                improved = True
                P("    r%d %s -> %s  f0_med=%.4f skin_f0=%.4f" % (
                    rd, GROUPS[gi], tag(cur[gi]), pick["f0_med"], pick["skin_f0"]))
        G, sk = eval_gids(cur, True)
        rec = pack("肢 cd r%d " % rd + "/".join(GROUPS[i] + "=" + tag(cur[i]) for i in range(5)),
                   cur, G, sk, extra={"phase": "limb_cd"})
        hist.append(rec)
        results.append(rec)
        P("  round %d: " % rd + fmt_row(rec))
        if not improved:
            P("  收敛于 round %d" % rd)
            break
    return hist


# 两个起点：I，以及全身 f0 最优 / 全身 skin 最优
cd_runs = []
cd_runs += descent([kI] * 5, 4, "from I")
cd_runs += descent([best_body_sk["gids"][0]] * 5, 4, "from body-skin")
cd_runs += descent([best_body_f0["gids"][0]] * 5, 4, "from body-f0")

# ---------- 3) 脊柱 × 单肢 48²（其余跟脊柱）----------
P("\n=== 3) 脊柱×单肢 48²（其余组跟脊柱；内环只算 frame0 骨位，皮肤留给前列）===")
pair_keep = []
for gi, gname in enumerate(GROUPS):
    if gi == 0:
        continue
    tmp = []
    for ks in range(N48):
        Aj = np.broadcast_to(AXM[ks][None], (NJ, 3, 3)).copy()
        for kl in range(N48):
            gids = [ks] * 5
            gids[gi] = kl
            Aj[gof_i == gi] = AXM[kl]
            G0 = compose(Aj, frames=[0])
            f0 = f0_rel(G0[:, 0])
            tmp.append((f0["med"], ks, kl, gids, f0))
        Aj[gof_i == gi] = AXM[ks]
    tmp.sort(key=lambda x: x[0])
    P("  spine×%s  f0_med 前 5（尚未蒙皮）：" % gname)
    for med, ks, kl, gids, f0 in tmp[:5]:
        P("    %s | %s  f0_med=%.4f mean=%.4f lt.05=%d/%d" % (
            tag(ks), tag(kl), f0["med"], f0["mean"], f0["n_lt_005"], f0["n"]))
        pair_keep.append(dict(
            label="pair spine×%s %s | %s" % (gname, tag(ks), tag(kl)),
            gids=gids, phase="pair", limb=gname))
    # 再抽 8 个 f0 中游/差的，防止只验前列
    extra_idx = [12, 24, 48, 96, 200, 500, 1000, len(tmp) - 1]
    for ii in extra_idx:
        if 0 <= ii < len(tmp):
            med, ks, kl, gids, f0 = tmp[ii]
            pair_keep.append(dict(
                label="pair* spine×%s %s | %s" % (gname, tag(ks), tag(kl)),
                gids=gids, phase="pair", limb=gname))

# 对 pair_keep + cd 终态 补全帧皮肤
need_full = []
seen = set()
for r in pair_keep + [x for x in results if x.get("phase") == "limb_cd"]:
    key = tuple(r["gids"])
    if key in seen:
        continue
    seen.add(key)
    need_full.append(r)

P("\n=== 补全帧皮肤（去重候选 %d）===" % len(need_full))
full_recs = []
for r in need_full:
    G, sk = eval_gids(r["gids"], True)
    rr = pack(r["label"], r["gids"], G, sk, extra={"phase": "full"})
    full_recs.append(rr)
    results.append(rr)

# ---------- 4) 对照：混用 t'=A t（上一班皮肤冠军口径）全身 48 + 一组坐标下降 ----------
P("\n=== 4) 对照混用 tv=1（R'=A^{-1} R A, t'=A t；不进主结论）===")


def compose_mixed(Aj, frames=None):
    if frames is None:
        rot, tr = Lrot, Ltr
        nf = NF
    else:
        rot, tr = Lrot[:, frames], Ltr[:, frames]
        nf = rot.shape[1]
    Ap = Aj.copy()
    for j in range(NJ):
        p = jpar[j]
        if p >= 0:
            Ap[j] = Aj[p]
    Apt = np.transpose(Ap, (0, 2, 1))
    Lin = np.einsum("jab,jfbc,jcd->jfad", Apt, rot, Aj)
    T = np.einsum("jab,jfb->jfa", Ap, tr)  # t' = Ap t
    Loc = np.zeros((NJ, nf, 4, 4))
    Loc[:, :, :3, :3] = Lin
    Loc[:, :, :3, 3] = T
    Loc[:, :, 3, 3] = 1.0
    G = np.empty_like(Loc)
    for j in seq:
        p = jpar[j]
        G[j] = Loc[j] if p < 0 else np.matmul(G[p], Loc[j])
    return G


def eval_mixed(gids, full_skin=True):
    Aj = Aj_from_gids(gids)
    G = compose_mixed(Aj) if full_skin else compose_mixed(Aj, frames=[0])
    sk = skin_from_G(G)
    if not full_skin:
        sk = dict(fm_min=sk["f0"], fm_max=sk["f0"], fm_mean=sk["f0"],
                  gmax=sk["gmax"], f0=sk["f0"])
    return G, sk

mixed_body = []
for k in range(N48):
    gids = [k] * 5
    G, sk = eval_mixed(gids, True)
    r = pack("混用全身 " + tag(k), gids, G, sk, extra={"phase": "mixed_body"})
    mixed_body.append(r)
mb_f0 = sorted(mixed_body, key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
mb_sk = sorted(mixed_body, key=lambda x: (x["skin_fm_mean"], x["f0_med"]))
P("  混用全身 按 f0_med 前 5：")
for r in mb_f0[:5]:
    P("    " + fmt_row(r))
P("  混用全身 按 skin 前 5：")
for r in mb_sk[:5]:
    P("    " + fmt_row(r))
P("  混用同时过线：%d / 48" % sum(1 for x in mixed_body if x["both"]))

# 从混用皮肤最优做一轮肢分组 CD（frame0 代理）
cur = list(mb_sk[0]["gids"])
P("  混用 CD start: " + fmt_row(mb_sk[0]))
for gi in range(5):
    local = []
    for k in range(N48):
        trial = list(cur)
        trial[gi] = k
        G, sk = eval_mixed(trial, False)
        local.append(pack("mx", trial, G, sk))
    ok = [x for x in local if x["skin_fm_mean"] < PASS_SKIN] or local
    pick = min(ok, key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
    unc = min(local, key=lambda x: x["f0_med"])
    P("    %s 无约束最优 %s f0_med=%.4f skin_f0=%.4f" % (
        GROUPS[gi], tag(unc["gids"][gi]), unc["f0_med"], unc["skin_f0"]))
    cur[gi] = pick["gids"][gi]
G, sk = eval_mixed(cur, True)
rmix_cd = pack("混用肢 CD " + "/".join(tag(k) for k in cur), cur, G, sk,
               extra={"phase": "mixed_cd"})
P("  混用 CD 终态: " + fmt_row(rmix_cd))
P("  groups: " + json.dumps(rmix_cd["groups"], ensure_ascii=False))
Gmixb, _ = eval_mixed(mb_sk[0]["gids"], True)
f0mix = f0_rel(Gmixb[:, 0])
P("\n[对照混用皮肤最优 逐骨] %s  f0_med=%.4f dt_med=%.4f" % (
    mb_sk[0]["label"], f0mix["med"], f0mix["dt_med"]))
mix_order = sorted(valid_idx, key=lambda j: -f0mix["per"][j])
for j in mix_order[:8]:
    P("    %-28s rel=%.4f |dt|=%.4f blen=%.4f" % (
        names[j], f0mix["per"][j], f0mix["dt"][j], blen[j]))
P("    ... 最好 3 根:")
for j in mix_order[-3:]:
    P("    %-28s rel=%.4f |dt|=%.4f blen=%.4f" % (
        names[j], f0mix["per"][j], f0mix["dt"][j], blen[j]))

# ---------- 汇总 ----------
def strip(r):
    o = {k: v for k, v in r.items() if not k.startswith("_")}
    return o

scored = [x for x in results if "f0_med" in x]
by_f0 = sorted(scored, key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
by_sk = sorted(scored, key=lambda x: (x["skin_fm_mean"], x["f0_med"]))
both = [x for x in scored if x["both"]]
# 主搜索（排除混用对照）
main = [x for x in scored if not str(x["label"]).startswith("对照")]
main_f0 = sorted(main, key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
main_sk = sorted(main, key=lambda x: (x["skin_fm_mean"], x["f0_med"]))
main_both = [x for x in main if x["both"]]
ok_skin_best_f0 = sorted([x for x in main if x["pass_skin"]],
                         key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
ok_f0_best_skin = sorted([x for x in main if x["pass_f0"]],
                         key=lambda x: x["skin_fm_mean"])

P("\n=== 汇总（主搜索=一致共轭；对照混用另列）===")
P("主搜索最小 f0_med: " + fmt_row(main_f0[0]))
P("主搜索最小 skin : " + fmt_row(main_sk[0]))
if ok_skin_best_f0:
    P("皮肤合格下最小 f0_med: " + fmt_row(ok_skin_best_f0[0]))
else:
    P("皮肤合格下最小 f0_med: （无，所有候选皮肤都 ≥ %.1f）" % PASS_SKIN)
if ok_f0_best_skin:
    P("f0 过线下最小 skin: " + fmt_row(ok_f0_best_skin[0]))
else:
    P("f0 过线下最小 skin: （无，没有任何候选 f0_med < %.2f）" % PASS_F0)
P("主搜索同时过线：%d" % len(main_both))
if main_both:
    for r in main_both[:5]:
        P("  [BOTH] " + fmt_row(r))

# 最佳「汇报」候选：若有 both 取 both；否则取皮肤合格下 f0 最好；再否则取全局 f0 最好并标明失败
if main_both:
    best = min(main_both, key=lambda x: (x["f0_med"], x["skin_fm_mean"]))
    verdict = "PASS"
elif ok_skin_best_f0:
    best = ok_skin_best_f0[0]
    verdict = "达不到"
else:
    best = main_f0[0]
    verdict = "达不到"

P("\n=== 汇报候选 [%s] ===" % verdict)
P(fmt_row(best))
P("  groups: " + json.dumps(best["groups"], ensure_ascii=False))

# 逐骨表
Gbest, _ = eval_gids(best["gids"], True)
f0b = f0_rel(Gbest[:, 0])
P("\n[逐骨 frame0 |Δworld|/骨长]  候选=%s" % best["label"])
P("%-28s %6s %8s %8s %8s" % ("bone", "group", "blen", "|dt|", "rel"))
order = sorted(valid_idx, key=lambda j: -f0b["per"][j])
for j in order:
    P("%-28s %6s %8.4f %8.4f %8.4f" % (
        names[j], gof[j], blen[j], f0b["dt"][j], f0b["per"][j]))

# 对照混用的 f0_med 也写进汇报
P("\n[对照] 上一班混用 tv=1 的新口径 f0_med=%.4f skin_mean=%.4f (not PASS)" % (
    rmix["f0_med"], rmix["skin_fm_mean"]))

# 保存
json_path = os.path.join(OUT_DIR, "numbers.json")
txt_path = os.path.join(OUT_DIR, "run.txt")
dump = dict(
    anim=ANIM, NF=NF, NJ=NJ, n_valid=int(valid.sum()),
    pass_f0=PASS_F0, pass_skin=PASS_SKIN,
    groups={g: [names[j] for j in range(NJ) if gof[j] == g] for g in GROUPS},
    excluded=[names[j] for j in range(NJ) if not valid[j]],
    blen={names[j]: float(blen[j]) for j in range(NJ)},
    verdict=verdict,
    best=strip(best),
    best_body_f0=strip(best_body_f0),
    best_body_skin=strip(best_body_sk),
    mixed_tv1_ref=strip(rmix),
    mixed_body_top_f0=[strip(x) for x in mb_f0[:8]],
    mixed_body_top_skin=[strip(x) for x in mb_sk[:8]],
    mixed_cd=strip(rmix_cd),
    mixed_per_bone=[{
        "bone": names[j], "group": gof[j], "blen": float(blen[j]),
        "dt": float(f0mix["dt"][j]), "rel": float(f0mix["per"][j]),
    } for j in mix_order],
    main_min_f0=strip(main_f0[0]),
    main_min_skin=strip(main_sk[0]),
    n_both=len(main_both),
    body_top_f0=[strip(x) for x in body_by_f0[:12]],
    body_top_skin=[strip(x) for x in body_by_sk[:12]],
    per_bone_best=[{
        "bone": names[j], "group": gof[j], "blen": float(blen[j]),
        "dt": float(f0b["dt"][j]), "rel": float(f0b["per"][j]),
    } for j in order],
)
json.dump(dump, open(json_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
open(txt_path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
P("\nsaved %s\nsaved %s" % (json_path, txt_path))
