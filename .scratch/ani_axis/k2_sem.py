"""mat64 语义判定 + 管线闭合检验（2026-10-07）。
  [M] 对 15 张 mat64 纯旋转：与 Ra(0)/Rb 的 6 种组合对照，找相等的那个。
  [M2] mat64 两模型是否一致（同一怪物骨架）。
  [N] 无记录骨：.ani 常量偏移 vs bind 局部平移（=0 占位）——.ani 就是缺失平移的候选。
  [O] 管线假设检验：true_local = [Ra(f) 旋转(按 [M] 结论修正), .ani 平移] 复合 frame0 世界，
      对有记录骨 vs bind 世界逐骨差 —— 判「.ani(修正后) frame0 == bind」是否闭合。
输出 k2_sem.txt
"""
import sys, json, math
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build, locals_frames, compose_worlds, ang

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


k2 = json.load(open(r"D:\TLGL\.scratch\ani_axis\k2_mat64_yifu.json"))
k2s = json.load(open(r"D:\TLGL\.scratch\ani_axis\k2_mat64_shoutao.json"))

D = build(GLBS["yifu"])
AN = read_anims(D)
NJ, names, jpar = D["NJ"], D["names"], D["jpar"]
Rb = D["blocal"][:, :3, :3].copy()
blt = D["blocal"][:, :3, 3].copy()
placeholder = [j for j in range(NJ)
               if np.linalg.norm(blt[j]) < 1e-6 and np.abs(Rb[j] - np.eye(3)).max() < 1e-5]
NF = len(list(AN["idle01"].values())[0]["translation"][0])
Lrot, Ltr, has = locals_frames(AN["idle01"], D, NF)

# mat64 字典（yifu），行主序 -> 列口径旋转 Rc = rows.T
mats_y = {e["name"]: np.array(e["mats"][0]).reshape(4, 4) for e in k2["entries"] if e["mats"]}
mats_s = {e["name"]: np.array(e["mats"][0]).reshape(4, 4) for e in k2s["entries"] if e["mats"]}

say("=== [M2] 两模型 mat64 一致性 ===")
same = sum(1 for nm in mats_y if nm in mats_s and np.abs(mats_y[nm] - mats_s[nm]).max() < 1e-6)
say("  yifu %d 张 / shoutao %d 张 / 完全相同 %d 张" % (len(mats_y), len(mats_s), same))

say("\n=== [M] mat64 旋转语义（列口径两种读法 x 组合）===")
say("  %-26s %7s %7s %7s %7s %7s %7s" %
    ("bone", "=Ra0", "=Rb", "Ra·m=Rb", "m·Ra=Rb", "Raᵀ·m=Rb", "m·Raᵀ=Rb"))
for nm, rm in mats_y.items():
    j = names.index(nm)
    Rm1 = rm[:3, :3].T   # 行->列
    Rm2 = rm[:3, :3]     # 不转置
    Ra0 = Lrot[j, 0]
    Rb = D["blocal"][j][:3, :3]
    a1 = ang(Rm1 @ Ra0.T); a2 = ang(Rm1 @ Rb.T)
    a3 = ang((Ra0 @ Rm1) @ Rb.T); a4 = ang((Rm1 @ Ra0) @ Rb.T)
    a5 = ang((Ra0.T @ Rm2) @ Rb.T); a6 = ang((Rm2 @ Ra0.T) @ Rb.T)
    say("  %-26s %7.2f %7.2f %7.2f %7.2f %7.2f %7.2f" % (nm, a1, a2, a3, a4, a5, a6))

# 也看 mat64 是否彼此相等/是否都是同一类旋转
vals = [rm[:3, :3].T for rm in mats_y.values()]
mx = max(ang(vals[a] @ vals[b].T) for a in range(len(vals)) for b in range(a + 1, len(vals)))
say("  mat64 旋转两两互差 max: %.2f°" % mx)

say("\n=== [N] 无记录骨（16 根）: .ani 常量平移（|t| med）与 mat64 有无 ===")
for j in placeholder:
    nm = names[j]
    tv = np.median(Ltr[j], axis=0) if has[j] else None
    say("  %-26s mat64=%s  ani|t|=%s  ani t=%s" %
        (nm, "Y" if nm in mats_y else "-",
         "%.4f" % np.linalg.norm(tv) if tv is not None else "-",
         np.round(tv, 4) if tv is not None else "-"))

open(r"D:\TLGL\.scratch\ani_axis\k2_sem.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k2_sem.txt")
