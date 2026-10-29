import numpy as np, sys
sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import build, read_anims, anim_keyframe, trs_mat, affine_inv4, quat_mat

D = build()
NJ, names = D["NJ"], D["names"]
print("NJ=%d  verts=%d  root_only_verts=%d  wsum_min=%.6f" %
      (NJ, len(D["POS"]), int(D["root_only"].sum()), float(D["wsum"].min())))
print("root bone:", names[0], "blocal[0]=\n", D["blocal"][0])

# 1. IBM 是否 = inv(B)
err = np.abs(D["IBM"] - np.stack([affine_inv4(D["B"][j]) for j in range(NJ)])).max()
print("[1] max|IBM - inv(B_composed)| = %.3e" % err)
# 1b. IBM 与 node 静态 TRS 复合的另一种口径（B vs inv(IBM)）
err2 = np.abs(np.stack([D["B"][j] - affine_inv4(D["IBM"][j]) for j in range(NJ)])).max()
print("[1b] max|B - inv(IBM)| = %.3e" % err2)
# 1c. IBM 第4行
print("[1c] IBM row3 dev:", np.abs(D["IBM"][:, 3, :] - np.array([0, 0, 0, 1.])).max())

# 2. 静置蒙皮 = I ?
rest = np.stack([D["B"][j] @ D["IBM"][j] for j in range(NJ)])
print("[2] max|B·IBM - I| = %.3e" % np.abs(rest - np.eye(4)[None]).max())

# 3. 骨位 vs 蒙皮加权重心（静态）
used = (~D["root_only"]) & (D["wsum"] > 0.999)
V, Wm = D["POS"][used], D["Wm"][used]
C = np.zeros((NJ, 3)); cov = np.zeros(NJ, bool)
for j in range(NJ):
    w = Wm[:, j]; s = w.sum()
    if s > 1e-9: C[j] = (V[w > 0] * w[w > 0, None]).sum(0) / s; cov[j] = True
off = np.linalg.norm(C - D["B"][:, :3, 3], axis=1)
print("[3] covered bones=%d (含根骨)  |C-B_t| mean(all)=%.4f" % (int(cov.sum()), off[cov].mean()))
noc = cov.copy(); noc[0] = False
print("[3] 剔根骨后 covered=%d  mean=%.4f median=%.4f max=%.4f" %
      (noc.sum(), off[noc].mean(), np.median(off[noc]), off[noc].max()))
print("[3] root bone |C-B_t| = %.4f (不参与)" % off[0])
for j in range(NJ):
    if noc[j] and off[j] > 0.30:
        print("    hi-resid", names[j], round(off[j], 4))

# 4. 骨长 & 站立高度
Bt = D["B"][:, :3, 3]
print("[4] B_t y-range: %.4f .. %.4f (总高 %.4f)" % (Bt[:, 1].min(), Bt[:, 1].max(), Bt[:, 1].max() - Bt[:, 1].min()))
bl = []
for j in range(NJ):
    if D["jpar"][j] >= 0:
        bl.append((np.linalg.norm(Bt[j] - Bt[D["jpar"][j]]), names[j]))
bl.sort()
print("[4] bone lengths min/max: %.4f (%s) / %.4f (%s)" % (bl[0][0], bl[0][1], bl[-1][0], bl[-1][1]))

# 5. 动画结构
AN = read_anims(D)
per = AN["idle01"]
cnt = {k: len(v["translation"][0]) if "translation" in v else 0 for k, v in per.items()}
print("[5] idle01: joints with channels=%d, key counts uniq=%s" % (len(per), sorted(set(cnt.values()))))
tot = {p: sum(1 for j, d in per.items() if p in d) for p in ("translation", "rotation", "scale")}
print("[5] channel counts:", tot, " interp:", set(d.get("_interp") for d in per.values()))
j0 = sorted(per)[0]
tms = per[j0]["translation"][0]
print("[5] times of joint %s: %s -> tick=%.4f" % (names[j0], np.round(tms[:5], 6), tms[1] - tms[0]))
print("[5] all anim frame counts:", {k: (len(v["translation"][0]) if "translation" in v else None) for k, v in sorted(AN.items())} if False else {a: len(list(p.values())[0].get("translation", (None, []))[0]) for a, p in AN.items()})
print("[5] root(000) has channels?", 0 in per)
# scale 通道统计
sc = np.concatenate([per[j]["scale"][1] for j in per if "scale" in per[j]])
print("[5] ani scale: min %s max %s | dev from 1: max %.4f | nonuniform frac %.3f" %
      (np.round(sc.min(0), 4), np.round(sc.max(0), 4), np.abs(sc - 1).max(), float((np.abs(sc[:, 0] - sc[:, 1]) > 1e-3).mean())))
# 旋转四元数是否单位 / 半球
qs = np.concatenate([per[j]["rotation"][1] for j in per if "rotation" in per[j]])
print("[5] quat norms dev %.2e ; w<0 frac %.3f" % (np.abs(np.linalg.norm(qs, axis=1) - 1).max(), float((qs[:, 3] < 0).mean())))
# frame0 vs bind 局部
f0 = []
for j in per:
    if "translation" in per[j]:
        a = trs_mat(anim_keyframe(per, j, "translation", 0, 3, None), anim_keyframe(per, j, "rotation", 0, 4, None), anim_keyframe(per, j, "scale", 0, 3, None))
        f0.append(np.abs(a - D["blocal"][j]).max())
print("[5] frame0 local vs bind local: mean maxdiff %.4f  (0 => frame0 就是 bind)" % np.mean(f0))
