"""刀1 前置探查（本班新文件）：
  [0] 两份 GLB 的结构：骨数、权重覆盖、记录骨/无记录骨名单（bind 局部平移≈0 且旋转≈I 视为占位）
  [1] 动画清单与帧数
  [2] 两模型动画数据同一性（逐动作 frame0 局部差 + idle01 全帧差）——
      若同源，「多模型投票」对动画内容问题要打折，必须如实记。
输出 k1_explore.txt
"""
import sys, json
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import GLBS, build

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


Dall = {}
for tag, path in GLBS.items():
    Dall[tag] = build(path)

D = Dall["yifu"]; D2 = Dall["shoutao"]
say("=== [0] 结构 ===")
say("yifu: NJ=%d verts=%d tris?(~846) | shoutao: NJ=%d verts=%d" %
    (D["NJ"], len(D["POS"]), D2["NJ"], len(D2["POS"])))
say("骨名序列一致: %s" % (D["names"] == D2["names"]))
say("父链一致: %s" % (D["jpar"] == D2["jpar"]))

for tag, Dx in Dall.items():
    placeholder = []
    for j in range(Dx["NJ"]):
        bl = Dx["blocal"][j]
        is_ph = (np.linalg.norm(bl[:3, 3]) < 1e-9 and np.abs(bl[:3, :3] - np.eye(3)).max() < 1e-9
                 and np.abs(bl[:3, :3] - np.eye(3)).max() < 1e-9)
        if is_ph:
            placeholder.append(j)
    withw = [j for j in range(Dx["NJ"]) if Dx["Wm"][:, j].sum() > 1e-9]
    say("[%s] 占位骨(无96B记录, 局部=I) %d 根: %s" % (tag, len(placeholder), ", ".join(Dx["names"][j] for j in placeholder)))
    say("[%s] 带蒙皮权重的骨 %d 根; 占位骨中有权重的 %d 根: %s" %
        (tag, len(withw), len([j for j in placeholder if j in withw]),
         ", ".join(Dx["names"][j] for j in placeholder if j in withw)))
    say("[%s] root_only 顶点 %d / %d; wsum<0.999 的顶点 %d" %
        (tag, int(Dx["root_only"].sum()), len(Dx["POS"]), int((Dx["wsum"] < 0.999).sum())))

say("")
say("=== [1] 动画清单与帧数 ===")
AN = {tag: read_anims(Dx) for tag, Dx in Dall.items()}
for tag in GLBS:
    fs = {a: len(list(p.values())[0].get("translation", ((None,),)))[0] if False else
          len(list(p.values())[0]["translation"][0]) for a, p in AN[tag].items()}
    say("[%s] %d 条动作: %s" % (tag, len(AN[tag]), json.dumps(fs, ensure_ascii=False)))

say("")
say("=== [2] 两模型动画数据同一性 ===")
a_y, a_s = AN["yifu"], AN["shoutao"]
say("动作名集合相同: %s" % (set(a_y) == set(a_s)))
worst_t, worst_r, worst_name = 0.0, 0.0, ""
for a in sorted(a_y):
    py, ps = a_y[a], a_s[a]
    dmax_t, dmax_r = 0.0, 0.0
    for j in set(py) & set(ps):
        ty, ts = py[j]["translation"][1], ps[j]["translation"][1]
        ry, rs = py[j]["rotation"][1], ps[j]["rotation"][1]
        n = min(len(ty), len(ts))
        dmax_t = max(dmax_t, float(np.abs(np.asarray(ty[:n]) - np.asarray(ts[:n])).max()))
        dmax_r = max(dmax_r, float(np.abs(np.asarray(ry[:n]) - np.asarray(rs[:n])).max()))
    if dmax_t > worst_t or dmax_r > worst_r:
        worst_name = a
    worst_t = max(worst_t, dmax_t); worst_r = max(worst_r, dmax_r)
    say("  %-16s 逐骨逐帧 max|Δt|=%.3e max|Δq|=%.3e" % (a, dmax_t, dmax_r))
say("两模型动画数据最大差: |Δt|=%.3e |Δq|=%.3e (最不一致的动作: %s)" % (worst_t, worst_r, worst_name))

open(r"D:\TLGL\.scratch\ani_axis\k1_explore.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> k1_explore.txt")
