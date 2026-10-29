# -*- coding: utf-8 -*-
"""15 条人工标注选样 v2（只读）：用放宽后的槽位链（mesh_slots.json，2,445 只可标）。

规则（报告里要能回答「为什么标它能带动阈值或带动一大类」）：
  可标注闸门：这只 mesh 有榜（有 UV、有分）+ 组里挂着至少一个干净的悬空贴图名（能落标）。
  对准闸门：优先「槽位名与 mesh 名同干」的（2,015 只天然无歧义），非此情况必须槽位数 ≤3。
  价值分五组，按组配额取，组内按「带动量」排序：
   G1 通吃冠军反证 ×4 —— 榜首次数最多的那几张（一张当 260 只的榜首），分属不同大类；
      标它们不为求真，而为判「度量榜首是不是系统性跑偏」，一条判决几百只。
   G2 阈值刀口 ×5 —— adjusted 卡在 1.2 / 3.0 / 6.0 与 coverage 闸门（≥6 但 cov<0.3）的样本；
      grade() 的四个数从没按 adjusted 刻度重标，只有边界样本能动它。
   G3 退化带 ×2 —— coverage≥0.9 且 adjusted<1.3（263 份）里两种脸色各一条：
      岛外方差=0 与岛外方差>0。判「铺满 = 无信息」这句到底成不成立。
   G4 槽位带动量 ×2 —— 同一个槽位名被 N 只已评分 mesh 共享（宽松口径最高 32 只），
      标 1 条落 N 条，是纯粹的吞吐杠杆。
   G5 类别不交 ×2 —— 前面各组没覆盖到的部件大类各钉一颗钉子，防阈值被单一家族带偏。
"""
import collections
import json
import os
import sqlite3

BS = chr(92)
ROOT = "D:/TLGL"
RES = os.path.join(ROOT, ".scratch/uvfit_batch/results")
SLOTS = os.path.join(ROOT, ".scratch/dyn/texaudit/mesh_slots.json")
CFGKEYS = os.path.join(ROOT, ".scratch/dyn/texaudit/cfg_tex_paths.json")
POOLDIR = os.path.join(ROOT, ".scratch/dyn/texaudit/pool_dir_map.json")
OUT = os.path.join(ROOT, ".scratch/dyn/texaudit/pick15.txt")
CSV = os.path.join(ROOT, ".scratch/dyn/texaudit/pick15.tsv")
L = []


def say(s=""):
    L.append(str(s))


CATS = [("boss", "boss"), ("pets", "宠物"), ("zuoqi", "坐骑"), ("monster", "怪物"), ("npc", "NPC"),
        ("guajian", "挂件"), ("yifu", "衣服"), ("shoutao", "手套"), ("xiuluo", "修罗"),
        ("toukui", "头魁"), ("model", "特效模型"), ("decal", "贴花"), ("caiji", "采集物"),
        ("drop", "掉落物"), ("shanh", "场景"), ("smeh", "场景建筑"), ("bmy", "草木"),
        ("plant", "植物"), ("wq", "武器"), ("jian", "剑"), ("qiang", "枪")]


def cat_of(mesh, slotdir):
    s = mesh.lower()
    for k, zh in CATS:
        if ("_" + k) in s or s.startswith(k + "_") or s == k + ".mesh":
            return zh
    d = (slotdir or "").lower()
    if "effect" in d:
        return "特效"
    if "mobile_maps" in d:
        return "场景"
    if "/player/" in d:
        return "玩家外观"
    return "其它"


def clean(n):
    return ("#" not in n and " " not in n and n.lower().endswith((".tga", ".dds", ".png"))
            and n.lower() != "defaultcompletemap.tga")


def main():
    con = sqlite3.connect("file:%s?mode=ro" % os.path.join(ROOT, ".scratch/resources.db").replace(BS, "/"), uri=True)
    slots = json.loads(open(SLOTS, encoding="utf-8").read())
    keys = json.loads(open(CFGKEYS, encoding="utf-8").read())["dangling_tex_keys"]
    pdir = json.loads(open(POOLDIR, encoding="utf-8").read())
    dang = dict(con.execute("select name,n_refs from dangling").fetchall())
    cfgpath = json.loads(open(CFGKEYS, encoding="utf-8").read())["cfg_registered_path_for_dangling"]

    rows = {}
    for f in sorted(os.listdir(RES)):
        v = json.loads(open(os.path.join(RES, f), encoding="utf-8").read())
        c = v.get("candidates") or []
        if not c:
            continue
        cands = sorted(c, key=lambda x: -x["adjustedScore"]) if all(x.get("adjustedScore") is not None for x in c) else c
        mesh = v["mesh"]
        ns = sorted(slots.get(mesh, []))
        stem = mesh.lower()[:-5]
        exact = [n for n in ns if n.lower().rsplit(".", 1)[0] == stem]
        pick_slot = exact[0] if exact else (ns[0] if ns else "")
        rows[mesh] = dict(
            mesh=mesh, cands=cands, top=cands[0], cov=v.get("coverage") or 0.0,
            adj=cands[0].get("adjustedScore"), raw=cands[0].get("score"),
            slots=ns, exact=exact,
            slotdir=(cfgpath.get(pick_slot, "") if pick_slot else "").rsplit("/", 1)[0],
        )
        r = rows[mesh]
        r["cat"] = cat_of(mesh, r["slotdir"])
        r["keyable"] = bool(ns) and (len(ns) <= 3 or bool(exact))
        a = r["adj"]
        r["band"] = ("degenerate" if (a is not None and a < 1.3 and r["cov"] >= 0.9) else
                     "lowSignal" if (a is not None and a < 1.2) else
                     "covgate" if (a is not None and a >= 6.0 and r["cov"] < 0.3) else
                     "3to6" if (a is not None and 3.0 <= a < 6.0) else
                     "1.2to3" if (a is not None and 1.2 <= a < 3.0) else
                     "high" if a is not None else "none")

    first = collections.Counter(r["top"]["hash"] for r in rows.values())
    slotfan = collections.Counter()
    for r in rows.values():
        for n in r["slots"]:
            slotfan[n] += 1
    keyable = [r for r in rows.values() if r["keyable"]]
    say("有榜 mesh %d 只；可落标（槽位干净且 ≤3 或同干）%d 只" % (len(rows), len(keyable)))
    say("分带: %s" % collections.Counter(r["band"] for r in keyable).most_common())
    say("榜首通吃冠军前 8: %s" % [(h[:8], n, pdir.get(h, "夹不出目录")) for h, n in first.most_common(8)])

    picks, used = [], set()
    used_cat = collections.Counter()

    def take(r, group, why):
        if r is None or r["mesh"] in used or len(picks) >= 15:
            return False
        used.add(r["mesh"])
        used_cat[r["cat"]] += 1
        picks.append((r, group, why))
        return True

    # G1 通吃冠军 ×4（同类只取一次）
    for h, n in first.most_common(60):
        if sum(1 for p in picks if p[1] == "G1 通吃冠军") >= 4:
            break
        xs = [r for r in keyable if r["top"]["hash"] == h and used_cat[r["cat"]] == 0]
        xs.sort(key=lambda r: -len(r["exact"]))
        if xs:
            r = xs[0]
            take(r, "G1 通吃冠军",
                 "榜首 %s 当了 %d 只模型的冠军（索引顺序把它夹到 %s）；一条判决这一批的榜首可信度" % (
                     h[:16], n, pdir.get(h, "夹不出目录")))

    # G2 阈值刀口 ×5
    def best(pred, key):
        xs = [r for r in keyable if pred(r) and r["mesh"] not in used]
        xs.sort(key=key)
        return xs[0] if xs else None

    specs = [
        ("G2 刀口 1.2 下沿", lambda r: 1.10 <= r["adj"] < 1.2, lambda r: abs(r["adj"] - 1.2)),
        ("G2 刀口 1.2 上沿", lambda r: 1.2 <= r["adj"] <= 1.35, lambda r: abs(r["adj"] - 1.2)),
        ("G2 刀口 3.0", lambda r: 2.75 <= r["adj"] <= 3.25, lambda r: abs(r["adj"] - 3.0)),
        ("G2 刀口 6.0", lambda r: 5.5 <= r["adj"] <= 6.6, lambda r: abs(r["adj"] - 6.0)),
        ("G2 coverage 闸门", lambda r: r["band"] == "covgate", lambda r: -r["adj"]),
    ]
    for g, pred, key in specs:
        cut = {"G2 刀口 1.2 下沿": 1.2, "G2 刀口 1.2 上沿": 1.2, "G2 刀口 3.0": 3.0, "G2 刀口 6.0": 6.0}.get(g)
        r = best(pred, key)
        why = ("adjusted=%.3f 正卡在 grade 的 %s 上，low/mid/high 三档与 2,105 份的归属判定都靠这条线" % (r["adj"], cut)
               if cut else "adjusted 很高但 coverage<0.3 被压档——专治小 UV 岛假高分")
        take(r, g, why)

    # G3 退化带 ×2
    r = best(lambda x: x["band"] == "degenerate" and x["top"].get("outsideVar") == 0, lambda x: -x["raw"])
    take(r, "G3 退化带·岛外零对比", "coverage=%.3f 岛外方差=0，榜只排「谁更忙」；标它才知道这 263 份要不要单独定状态" % r["cov"])
    r = best(lambda x: x["band"] == "degenerate" and (x["top"].get("outsideVar") or 0) > 0, lambda x: -x["cov"])
    take(r, "G3 退化带·比值贴 1", "adjusted=%.3f 且 coverage=%.3f：铺满整图时岛内外无对比，判「铺满=无信息」成不成立" % (r["adj"], r["cov"]))

    # G4 槽位带动量 ×2
    xs = sorted(keyable, key=lambda r: (-max([slotfan[n] for n in r["slots"]], default=1), -max([dang.get(n, 1) for n in r["slots"]], default=1)))
    for r in xs[:60]:
        if sum(1 for p in picks if p[1].startswith("G4")) >= 2:
            break
        n = max(r["slots"], key=lambda x: slotfan[x])
        take(r, "G4 槽位带动", "槽位 %s 被 %d 只已评分 mesh 共用（dangling.n_refs=%s）；标 1 条落 %d 条" % (
            n, slotfan[n], dang.get(n), slotfan[n]))

    # G5 类别不交 ×2
    for cat in ["坐骑", "怪物", "挂件", "衣服", "特效", "贴花", "场景", "玩家外观", "NPC", "其它"]:
        if sum(1 for p in picks if p[1].startswith("G5")) >= 2 or used_cat[cat]:
            continue
        xs = [r for r in keyable if r["cat"] == cat and r["mesh"] not in used]
        if not xs:
            continue
        xs.sort(key=lambda r: (-(len(r["exact"])), -first[r["top"]["hash"]]))
        take(xs[0], "G5 类别不交", "大类「%s」前面一条都没沾到，阈值不能只被一家族带偏" % cat)

    # 补足 15：优先还能带来新榜首 hash 的
    seen = set(p[0]["top"]["hash"] for p in picks)
    for r in sorted(keyable, key=lambda r: -first[r["top"]["hash"]]):
        if len(picks) >= 15:
            break
        if r["mesh"] not in used and r["top"]["hash"] not in seen:
            seen.add(r["top"]["hash"])
            take(r, "G6 新增冠军贴图", "这张榜首还没被覆盖（它同时是 %d 只的榜首）" % first[r["top"]["hash"]])
    for r in sorted(keyable, key=lambda r: -first[r["top"]["hash"]]):
        if len(picks) >= 15:
            break
        take(r, "G6 补量", "剩余榜首覆盖最大的一群")

    say()
    say("=== 15 条（可执行清单）===")
    hdr = ("#", "组", "mesh", "大类", "覆盖表键（标注写这里）", "槽位选择", "榜首hash", "规格",
           "raw", "adjusted", "coverage", "该hash当榜首", "同槽位mesh数", "为什么值钱")
    tab = [hdr]
    inf_hash, inf_mesh = set(), set()
    for i, (r, g, why) in enumerate(picks[:15], 1):
        n = (r["exact"] or r["slots"])[0]
        key = keys.get(n, "bare:%s" % n)
        t = r["top"]
        tab.append((str(i), g, r["mesh"], r["cat"], key,
                    "同干自动对准" if r["exact"] else "槽位 %d 选 1" % len(r["slots"]),
                    t["hash"], "%sx%s %s m%s" % (t.get("w"), t.get("h"), t.get("codec"), t.get("mips")),
                    "%.1f" % (r["raw"] or 0), "%.3f" % (r["adj"] or 0), "%.3f" % (r["cov"] or 0),
                    str(first[t["hash"]]), str(max([slotfan[x] for x in r["slots"]], default=1)), why))
        inf_hash.add(t["hash"])
        hh = t["hash"]
        nn = set(r["slots"])
        inf_mesh |= set(m for m, rr in rows.items() if rr["top"]["hash"] == hh)
        inf_mesh |= set(m for m, rr in rows.items() if nn & set(rr["slots"]))
    for row in tab:
        say(" | ".join(row))
    say()
    say("账面：15 条锁定榜首贴图 %d 张；按「同榜首 / 同槽位」外推影响 mesh %d 只（占有榜 %d 只的 %.1f%%）" % (
        len(inf_hash), len(inf_mesh), len(rows), 100.0 * len(inf_mesh) / len(rows)))
    say("组配额: %s" % collections.Counter(p[1] for p in picks).most_common())
    say("类别覆盖: %s" % collections.Counter(p[0]["cat"] for p in picks).most_common())
    say("槽位无歧义（同干）: %d / 15" % sum(1 for p in picks if p[0]["exact"]))

    with open(CSV, "w", encoding="utf-8") as fh:
        for row in tab:
            fh.write("\t".join(row) + "\n")
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
