"""反例形态与平局机制分析（2026-10-07，多怪锚点验证的第二刀）。

Q1 反例（A1 帧均反而差）的逐帧位移剖面：是不是「frame0 半程起步 + 尸体远行」形态？
Q2 平局 41 条是否全部来自「唯一有权重的骨无轨道/恒位」的空载模型（A0≡A1 平凡相等）？
Q3 dead 与 flyingdead、deadbegin 与 flyingdeadbegin 是否同数据（把 181 行折成多少条独立动作数据）？
Q4 反例怪的 frame0-bind 差与胜负的关系：赢的动作和输的动作在 f0_vs_bind 上有没有分野？
输出 counter_analysis.txt
"""
import sys, json, math, glob, os
import numpy as np

sys.path.insert(0, r"D:\TLGL\.scratch\ani_axis")
from common import read_anims
from common2 import build, compose_worlds, locals_frames, skin, ang

GLBDIR = r"D:\TLGL\.scratch\multi_model\glb"
MODELS = {
    "yifu":     r"D:\TLGL\.scratch\glb_rigged\m_db18794d0000cd38.glb",
    "hmz_lian": GLBDIR + r"\m_0720df4800003144.glb",
    "hmz_yifu": GLBDIR + r"\m_b744d942000085f4.glb",
    "daheixiong": GLBDIR + r"\m_71b37e1800008248.glb",
    "daomuzei": GLBDIR + r"\m_4e32e3b40000deb4.glb",
    "baolong":  GLBDIR + r"\m_7ce704550000dbd0.glb",
    "jiuweihu": GLBDIR + r"\m_ce4380cf00048234.glb",
    "lk_lian":  GLBDIR + r"\m_7e8190650000fea0.glb",
    "lk_yifu":  GLBDIR + r"\m_46a8f8fd0000db00.glb",
    "heihou":   GLBDIR + r"\m_f2804ef700005f00.glb",
    # 空载对照（平局机制验证用）
    "shoutao":  r"D:\TLGL\.scratch\glb_rigged\m_8ff895cd00003a5c.glb",
    "xiaobaishe": GLBDIR + r"\m_e21651fc00003dc0.glb",
    "duzhizhu": GLBDIR + r"\m_7fa02b560000a294.glb",
    "bird":     GLBDIR + r"\m_50a2fd110003856c.glb",
}
ANISRC = {
    "yifu": r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_xiyuqiezei\ani",
    "daomuzei": r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_daomuzei\ani",
    "hmz_lian": r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_monster_heimiaozhanshi\ani",
    "lk_yifu": r"D:\TLGL\.scratch\out\tree\data\source\npc\quest\w1351_boss_likui\ani",
}

OUT = []


def say(s=""):
    OUT.append(str(s))
    print(s)


# ---------- Q3 同数据动作对（字节级） ----------
say("## Q3 同一模型里逐字节相同的动作对（把行数折成独立动作数据）")
for tag, adir in ANISRC.items():
    raws = {}
    for p in sorted(glob.glob(os.path.join(adir, "*.ani"))):
        raws[os.path.basename(p)[:-4]] = open(p, "rb").read()
    keys = sorted(raws)
    same = []
    for i in range(len(keys)):
        for k2 in keys[i + 1:]:
            if raws[keys[i]] == raws[k2]:
                same.append((keys[i], k2))
    say("  %s: %d 条 .ani，逐字节相同对：%s" %
        (tag, len(keys), ", ".join("%s≡%s" % p for p in same) if same else "无"))

# ---------- Q2 空载模型机制 + Q1 反例剖面 + Q4 f0-bind 分野 ----------
say("")
say("## Q2 空载（平局）机制：唯一有权重的骨是否有轨道")
for tag in ("shoutao", "xiaobaishe", "duzhizhu", "bird"):
    D = build(MODELS[tag])
    AN = read_anims(D)
    wsum = D["Wm"].sum(0)
    wb = [j for j in range(D["NJ"]) if wsum[j] > 1e-9]
    per = AN[sorted(AN)[0]]
    a = sorted(AN)[0]
    nfs = sorted({len(d[p][0]) for d in per.values() for p in ("translation", "rotation") if p in d})
    NF = nfs[0]
    Lrot, Ltr, has = locals_frames(per, D, NF)
    G = compose_worlds(Lrot, Ltr, D)
    for j in wb:
        nm = D["names"][j]
        dt = np.linalg.norm(G[j, :, :3, 3] - D["B"][j, :3, 3], axis=1).max()
        say("  %s: 权重骨 [%s] 有轨道=%s 全帧世界-vs-bind 最大|Δt|=%.6f -> 蒙皮恒等成立的机制=%s" %
            (tag, nm, bool(has[j]), dt, "骨恒位（A0≡A1 平凡）" if dt < 1e-6 else "骨在动（平局另有原因！）"))

say("")
say("## Q1 反例逐帧剖面（每条：帧均A0/A1 与 首/中/末帧均值、峰值帧）")
CASES = [("hmz_lian", "deadbegin"), ("daomuzei", None), ("lk_yifu", "deadbegin")]
for tag, only in CASES:
    D = build(MODELS[tag])
    AN = read_anims(D)
    use = (~D["root_only"]) & (D["wsum"] > 0.999)
    if use.sum() == 0:
        use = (D["wsum"] > 0.999) & (D["Wm"].sum(1) > 0)
    for a in sorted(AN):
        if only and only not in a and not a.endswith("hit01") and not a.endswith("hit03"):
            continue
        if only and a.endswith("flyingdeadbegin"):
            continue
        per = AN[a]
        nfs = sorted({len(d[p][0]) for d in per.values() for p in ("translation", "rotation") if p in d})
        NF = nfs[0]
        Lrot, Ltr, has = locals_frames(per, D, NF)
        G = compose_worlds(Lrot, Ltr, D)
        A1 = np.linalg.inv(G[:, 0])
        prof = {}
        for key, anc in (("A0", D["IBM"]), ("A1", A1)):
            Vp = skin(G, anc, D)
            disp = np.linalg.norm(Vp - D["POS"][:, None, :], axis=2)
            prof[key] = disp[use].mean(0)
        pk0 = int(prof["A0"].argmax()); pk1 = int(prof["A1"].argmax())
        mid = NF // 2
        gm = {}
        for key, anc in (("A0", D["IBM"]), ("A1", A1)):
            Vp = skin(G, anc, D)
            disp = np.linalg.norm(Vp - D["POS"][:, None, :], axis=2)
            gm[key] = float(disp[use].max())
        say("  %s/%s (%d帧)" % (tag, a, NF))
        say("    A0 帧0/中/末 = %.3f/%.3f/%.3f  帧均峰值=%.3f(帧%d, compare口径帧均)  全max=%.3f" %
            (prof["A0"][0], prof["A0"][mid], prof["A0"][-1], prof["A0"][pk0], pk0, gm["A0"]))
        say("    A1 帧0/中/末 = %.3f/%.3f/%.3f  帧均峰值=%.3f(帧%d, compare口径帧均)  全max=%.3f" %
            (prof["A1"][0], prof["A1"][mid], prof["A1"][-1], prof["A1"][pk1], pk1, gm["A1"]))
        if not only:
            break_ = None

say("")
say("## Q4 每模型：赢/输动作的 frame0-vs-bind 差（|Δt| 中位、角差中位，单位同网格/度）")
CJ = json.load(open(r"D:\TLGL\.scratch\multi_model\compare_anchors.json"))
for tag in ("yifu", "hmz_yifu", "hmz_lian", "daheixiong", "daomuzei", "baolong", "jiuweihu", "lk_lian", "lk_yifu", "heihou"):
    key = [k for k in CJ if k.split("(")[0] == tag][0]
    D = build(MODELS[tag])
    res = CJ[key]
    rows = res["rows"]
    ws = [(a, rows[a]["f0_vs_bind_dt_med"], rows[a]["f0_vs_bind_ang_med"]) for a in rows if rows[a]["verdict"] == "WIN"]
    ls = [(a, rows[a]["f0_vs_bind_dt_med"], rows[a]["f0_vs_bind_ang_med"]) for a in rows if rows[a]["verdict"] == "LOSS"]
    fmt = lambda xs: ("帧均|Δt| %.2f~%.2f 角 %.0f~%.0f°" % (min(x[1] for x in xs), max(x[1] for x in xs),
                        min(x[2] for x in xs), max(x[2] for x in xs))) if xs else "-"
    say("  %-11s 赢%3d: %s | 输%2d: %s" % (tag, len(ws), fmt(ws), len(ls), fmt(ls)))
    for a, dt, ag in ls:
        say("      输: %-28s |Δt|=%.2f 角=%.0f°" % (a, dt, ag))

open(r"D:\TLGL\.scratch\multi_model\counter_analysis.txt", "w", encoding="utf-8").write("\n".join(OUT) + "\n")
print("saved -> counter_analysis.txt")
