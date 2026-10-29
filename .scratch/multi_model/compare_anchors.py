"""多怪锚点验证（2026-10-07）：「播放锚 = 逐动作 frame0」跨怪复测。

问题：yifu_001 上 15/15 条动作 frame0 锚全胜裸 bind 锚，是这副骨架的偶然，
还是 .ani 格式的通例？

做法照 .scratch/ani_axis/k2_cross.py（口径不改动，只参数化到任意 GLB）：
  A0 裸 bind 锚   = GLB skins[0].inverseBindMatrices（= 现状导出口径，.mesh 96B 记录）；
  A1 逐动作 f0 锚 = inv(world_frame0)（每条动作自己的）；
  A2 单锚对照    = 第一条动作（名字排序）的 frame0 锚播全部动作。
每条动作量（mask = 非 root_only 且权重和>0.999，与 k2_cross 相同）：
  帧均 = max over frames of (mean over verts ||Vp - POS||)；
  全max = 全帧全局最大位移。
判定（主判据 = 帧均）：
  win  : fm1 < fm0 - 1e-9
  tie  : |fm1 - fm0| <= 1e-9
  loss : fm1 > fm0 + 1e-9
附带形态数字（反例分析用）：骨数、有权重骨数、root_only 占比、
IBM vs inv(node树 bind 世界) 最大差（口径自洽性）、frame0 vs bind 的 |Δt|/角差、
该动作 frame0 与首条动作 frame0 是否相同。
输出 compare_anchors.txt / compare_anchors.json
"""
import sys, json, math
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import build, compose_worlds, locals_frames, skin, ang

GLBDIR = r"D:\TLGL\.scratch\multi_model\glb"
MODELS = {
    "yifu(对照)":     r"D:\TLGL\.scratch\glb_rigged\m_db18794d0000cd38.glb",
    "shoutao(对照)":  r"D:\TLGL\.scratch\glb_rigged\m_8ff895cd00003a5c.glb",
    "hmz_lian":       GLBDIR + r"\m_0720df4800003144.glb",
    "hmz_shoutao":    GLBDIR + r"\m_c010856d00002860.glb",
    "hmz_yifu":       GLBDIR + r"\m_b744d942000085f4.glb",
    "daheixiong":     GLBDIR + r"\m_71b37e1800008248.glb",
    "daomuzei":       GLBDIR + r"\m_4e32e3b40000deb4.glb",
    "baolong":        GLBDIR + r"\m_7ce704550000dbd0.glb",
    "jiuweihu":       GLBDIR + r"\m_ce4380cf00048234.glb",
    "lk_lian":        GLBDIR + r"\m_7e8190650000fea0.glb",
    "lk_yifu":        GLBDIR + r"\m_46a8f8fd0000db00.glb",
    "xiaobaishe":     GLBDIR + r"\m_e21651fc00003dc0.glb",
    "heihou":         GLBDIR + r"\m_f2804ef700005f00.glb",
    "duzhizhu":       GLBDIR + r"\m_7fa02b560000a294.glb",
    "xuanhaima":      GLBDIR + r"\m_7f0bd31700007864.glb",
    "bird":           GLBDIR + r"\m_50a2fd110003856c.glb",
    "buliandeng":     GLBDIR + r"\m_c153349600004a9c.glb",
}

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


results = {}
for tag, path in MODELS.items():
    say("#" * 100)
    say("=== %s  (%s)" % (tag, path.split("\\")[-1]))
    try:
        D = build(path)
    except Exception as e:
        say("  装载失败：%r" % (e,))
        results[tag] = {"error": "build: %r" % (e,)}
        continue
    AN = read_anims(D)
    if not AN:
        say("  无动画，跳过比对")
        results[tag] = {"error": "no animations"}
        continue
    NJ = D["NJ"]
    IBM = D["IBM"]
    ibm_err = float(np.abs(IBM - D["Binv"]).max())
    use = (~D["root_only"]) & (D["wsum"] > 0.999)
    degenerate = False
    if use.sum() == 0:
        # 全部顶点只绑根骨（部件网格）：k2_cross 口径下没有可统计顶点。
        # 退化为「全体有权重顶点」——锚的选择在物体层面仍可判，标 degenerate。
        degenerate = True
        use = (D["wsum"] > 0.999) & (D["Wm"].sum(1) > 0)
    n_use = int(use.sum())
    wsum_bone = D["Wm"].sum(0)
    n_weighted = int((wsum_bone > 1e-9).sum())
    root_frac = float(D["root_only"].mean())
    names = D["names"]

    # frame0 vs bind 形态（带动画通道的骨上量）
    first = sorted(AN)[0]
    G0s = {}
    f0meta = {}
    for a in sorted(AN):
        per = AN[a]
        nfs = sorted({len(d[p][0]) for d in per.values() for p in ("translation", "rotation") if p in d})
        NF = nfs[0]
        if len(nfs) > 1:
            f0meta[a] = {"nf_mixed": nfs}
        Lrot, Ltr, has = locals_frames(per, D, NF)
        G = compose_worlds(Lrot, Ltr, D)
        G0s[a] = G[:, 0].copy()
        if a not in f0meta:
            f0meta[a] = {"nf": NF}
        # frame0 与首条动作的 frame0 逐骨差
        hb = np.where(has)[0]
        dt = np.linalg.norm(G0s[a][hb, :3, 3] - G0s[first][hb, :3, 3], axis=1)
        da = np.array([ang(G0s[a][j, :3, :3] @ G0s[first][j, :3, :3].T) for j in hb])
        f0meta[a]["same_as_first"] = bool(dt.max() < 1e-4 and da.max() < 1e-3)
        f0meta[a]["f0_vs_first_maxdt"] = float(dt.max())
        # frame0 vs bind
        dtb = np.linalg.norm(G0s[a][hb, :3, 3] - D["B"][hb, :3, 3], axis=1)
        dab = np.array([ang(G0s[a][j, :3, :3] @ D["B"][j, :3, :3].T) for j in hb])
        f0meta[a]["f0_vs_bind_dt_med"] = float(np.median(dtb))
        f0meta[a]["f0_vs_bind_dt_max"] = float(dtb.max())
        f0meta[a]["f0_vs_bind_ang_med"] = float(np.median(dab))
        f0meta[a]["f0_vs_bind_ang_max"] = float(dab.max())

    A2anchor = np.linalg.inv(G0s[first])
    say("  骨 %d，有权重骨 %d，root_only 顶点占比 %.3f，参与统计顶点 %d%s，动作 %d 条，首条=%s" %
        (NJ, n_weighted, root_frac, n_use, ("（root_only退化，mask=全体）" if degenerate else ""), len(AN), first))
    say("  IBM vs inv(node树bind世界) 最大差 %.3e（口径自洽）" % ibm_err)
    hb_all = []
    for a in sorted(AN):
        hb_all.append(f0meta[a]["f0_vs_bind_dt_med"])
    say("  frame0 vs bind（各动作中位|Δt|）范围 %.3f ~ %.3f" % (min(hb_all), max(hb_all)))

    say("")
    say("  %-16s %4s %-17s %-17s %-17s %s" %
        ("动作", "帧数", "A0 裸bind 帧/全", "A1 逐动作f0 帧/全", "A2 单锚 帧/全", "判定"))
    rows = {}
    for a in sorted(AN):
        per = AN[a]
        NF = f0meta[a].get("nf") or max(f0meta[a].get("nf_mixed", [0]))
        Lrot, Ltr, has = locals_frames(per, D, NF)
        G = compose_worlds(Lrot, Ltr, D)
        A1anchor = np.linalg.inv(G[:, 0])
        vals = {}
        for key, anc in (("A0", IBM), ("A1", A1anchor), ("A2", A2anchor)):
            Vp = skin(G, anc, D)
            disp = np.linalg.norm(Vp - D["POS"][:, None, :], axis=2)
            fm = disp[use].mean(0)
            vals[key] = (float(fm.max()), float(disp[use].max()))
        fm0, am0 = vals["A0"]; fm1, am1 = vals["A1"]; fm2, am2 = vals["A2"]
        if abs(fm1 - fm0) <= 1e-9:
            v = "tie"
        elif fm1 < fm0:
            v = "WIN"
        else:
            v = "LOSS"
        same = "A1=A2" if f0meta[a]["same_as_first"] else ""
        say("  %-16s %4d %7.3f/%7.3f %7.3f/%7.3f %7.3f/%7.3f  %-4s %s" %
            (a, NF, fm0, am0, fm1, am1, fm2, am2, v, same))
        rows[a] = {"nf": NF, "A0": vals["A0"], "A1": vals["A1"], "A2": vals["A2"],
                   "verdict": v, "same_frame0_as_first": f0meta[a]["same_as_first"],
                   **{k: v2 for k, v2 in f0meta[a].items()}}
    nw = sum(1 for r in rows.values() if r["verdict"] == "WIN")
    nt = sum(1 for r in rows.values() if r["verdict"] == "tie")
    nl = sum(1 for r in rows.values() if r["verdict"] == "LOSS")
    say("  小结：%d 动作中 A1 胜 %d / 平 %d / 负 %d" % (len(rows), nw, nt, nl))
    a2_worse = [a for a in rows if rows[a]["A2"][0] > rows[a]["A1"][0] + 0.01]
    say("  A2 单锚显著差于 A1 的动作 %d 条%s" %
        (len(a2_worse), ("：" + ", ".join(sorted(a2_worse))) if a2_worse else ""))
    results[tag] = {
        "glb": path, "NJ": NJ, "n_weighted_bones": n_weighted, "n_use_verts": n_use,
        "root_only_frac": root_frac, "ibm_err": ibm_err, "n_anims": len(AN),
        "first_anim": first, "rows": rows,
        "win": nw, "tie": nt, "loss": nl,
    }
    say("")

# 汇总
say("#" * 100)
say("总表（只计有动画且参与顶点>0 的模型）")
tot = {"WIN": 0, "tie": 0, "LOSS": 0}
tot_valid = 0
for tag, r in results.items():
    if "error" in r or not r.get("rows"):
        continue
    tot_valid += 1
    tot["WIN"] += r["win"]; tot["tie"] += r["tie"]; tot["LOSS"] += r["loss"]
    say("  %-16s 动作%3d  胜%3d 平%3d 负%3d  骨%3d 有权重骨%3d root_only%.2f" %
        (tag, len(r["rows"]), r["win"], r["tie"], r["loss"],
         r["NJ"], r["n_weighted_bones"], r["root_only_frac"]))
n_all = tot["WIN"] + tot["tie"] + tot["LOSS"]
say("")
say("合计：%d 个模型、%d 条 (模型,动作) 对；A1 胜 %d（%.1f%%）、平 %d（%.1f%%）、负 %d（%.1f%%）" %
    (tot_valid, n_all, tot["WIN"], 100.0 * tot["WIN"] / n_all,
     tot["tie"], 100.0 * tot["tie"] / n_all, tot["LOSS"], 100.0 * tot["LOSS"] / n_all))
losses = [(t, a, r["rows"][a]) for t, r in results.items() if "rows" in r
          for a in r["rows"] if r["rows"][a]["verdict"] == "LOSS"]
if losses:
    say("")
    say("反例清单（主判据帧均）：")
    for t, a, row in losses:
        say("  %s / %s : A0 %.4f/%.4f  A1 %.4f/%.4f  (帧均 A1-A0 = %+.4f, 全max A1-A0 = %+.4f)" %
            (t, a, row["A0"][0], row["A0"][1], row["A1"][0], row["A1"][1],
             row["A1"][0] - row["A0"][0], row["A1"][1] - row["A0"][1]))
ties = [(t, a) for t, r in results.items() if "rows" in r for a in r["rows"] if r["rows"][a]["verdict"] == "tie"]
if ties:
    say("")
    say("平局清单：%s" % ", ".join("%s/%s" % (t, a) for t, a in ties))

json.dump(results, open(r"D:\TLGL\.scratch\multi_model\compare_anchors.json", "w"), ensure_ascii=False, indent=1)
open(r"D:\TLGL\.scratch\multi_model\compare_anchors.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> compare_anchors.txt / .json")
