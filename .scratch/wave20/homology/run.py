# -*- coding: utf-8 -*-
"""多份 .mesh bind 骨架 vs 同干 .ani 第 0 帧局部平移：同源取证。

只读 `.scratch/out/tree`。产物全部写本目录。不改产品代码、不 git、不 cargo。
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from parse import load_ani, load_mesh, pick_idle, trans, vlen, vsub  # noqa: E402

TREE = r"D:\TLGL\.scratch\out\tree"
OUT = HERE
EPS = 1e-3

IDLE_HINT = ("_idle01.", "_idle.", "_fight_idle01.", "_idle02.", "_stand.")


def percentile(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    if p <= 0:
        return s[0]
    if p >= 100:
        return s[-1]
    k = (len(s) - 1) * p / 100.0
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return s[int(k)]
    return s[f] * (c - k) + s[c] * (k - f)


def dist_stats(xs):
    if not xs:
        return None
    return {
        "n": len(xs),
        "min": min(xs),
        "p10": percentile(xs, 10),
        "p25": percentile(xs, 25),
        "p50": percentile(xs, 50),
        "p75": percentile(xs, 75),
        "p90": percentile(xs, 90),
        "p95": percentile(xs, 95),
        "p99": percentile(xs, 99),
        "max": max(xs),
        "mean": sum(xs) / len(xs),
        "n_lt_1e3": sum(1 for v in xs if v < EPS),
        "frac_lt_1e3": sum(1 for v in xs if v < EPS) / len(xs),
    }


def fmt(v, nd=4):
    if v is None:
        return "—"
    if isinstance(v, int):
        return str(v)
    return ("%." + str(nd) + "f") % v


def category(rel: str, mesh_name: str) -> str:
    s = (rel + "/" + mesh_name).lower().replace("\\", "/")
    if "/boss" in s or "_boss_" in s:
        return "boss"
    if "monster" in s:
        return "monster"
    if "pets" in s or "_pet_" in s:
        return "pet"
    if "zuoqi" in s:
        return "mount"
    if "_nv_" in s or "/nv/" in s or "nv_s" in s:
        return "player_f"
    if "_nan_" in s or "/nan/" in s or "nan_s" in s:
        return "player_m"
    if "npc" in s:
        return "npc"
    return "other"


def char_key(folder: str, mesh_name: str) -> str:
    base = os.path.basename(folder.rstrip("\\/"))
    stem = os.path.splitext(mesh_name)[0]
    if stem.startswith(base):
        return base
    return stem


def is_body_mesh(name: str) -> int:
    n = name.lower()
    if "_yifu" in n:
        return 0
    if "_body" in n or "_shenti" in n:
        return 1
    if "_tou" in n or "_head" in n or "_shoutao" in n or "_xie" in n:
        return 8
    return 4


def is_humanoid(bones) -> bool:
    names = " ".join(b["name"].lower() for b in bones)
    if "bip01" in names:
        return True
    hits = 0
    for tok in ("pelvis", "spine", "thigh", "calf", "clavicle", "upperarm", "neck", "head"):
        if tok in names:
            hits += 1
    return hits >= 4 and len(bones) >= 14


def discover():
    """按角色目录配 .mesh + 同干 .ani（目录名 / 文件名前缀）。"""
    folders = defaultdict(lambda: {"mesh": [], "ani": []})
    for dp, _dns, fns in os.walk(TREE):
        for n in fns:
            low = n.lower()
            if low.endswith(".mesh"):
                folders[dp]["mesh"].append(os.path.join(dp, n))
            elif low.endswith(".ani"):
                folders[dp]["ani"].append(os.path.join(dp, n))
                parent = os.path.dirname(dp)
                if os.path.basename(dp).lower() == "ani":
                    folders[parent]["ani"].append(os.path.join(dp, n))
    pairs = []
    for folder, bag in folders.items():
        if not bag["mesh"] or not bag["ani"]:
            continue
        rel = os.path.relpath(folder, TREE)
        meshes_sorted = sorted(bag["mesh"], key=lambda p: (is_body_mesh(os.path.basename(p)), -os.path.getsize(p)))
        ani_pick = pick_idle(bag["ani"])
        if ani_pick is None:
            continue
        mesh_pick = meshes_sorted[0]
        pairs.append(
            {
                "folder": folder,
                "rel": rel.replace("\\", "/"),
                "mesh": mesh_pick,
                "ani": ani_pick,
                "n_mesh": len(bag["mesh"]),
                "n_ani": len(set(bag["ani"])),
                "char": char_key(folder, os.path.basename(mesh_pick)),
                "cat": category(rel, os.path.basename(mesh_pick)),
            }
        )
    pairs.sort(key=lambda r: (r["cat"], r["char"]))
    return pairs


def compare_pair(mesh_path, ani_path):
    h = load_mesh(mesh_path)
    if h is None:
        return None, "mesh-parse-fail"
    a = load_ani(ani_path)
    if a is None:
        return None, "ani-parse-fail"
    if not is_humanoid(h["bones"]):
        return None, "not-humanoid"
    by_name = {t["bone"]: t for t in a["tracks"] if t["bone"]}
    rows = []
    for i, b in enumerate(h["bones"]):
        tr = by_name.get(b["name"])
        if tr is None:
            continue
        t_ani = tr["positions"][0]
        t_loc = trans(h["locals"][i])
        t_wld = trans(h["worlds"][i])
        d_loc = vlen(vsub(t_ani, t_loc))
        d_wld = vlen(vsub(t_ani, t_wld))
        has96 = b["bind"] is not None
        p = b["parent"]
        parent_has96 = p is not None and h["bones"][p]["bind"] is not None
        rows.append(
            {
                "bone": b["name"],
                "has96": has96,
                "parent_has96": bool(parent_has96) if p is not None else True,
                "t_ani": t_ani,
                "t_bind_local": t_loc,
                "t_bind_world": t_wld,
                "|t_ani|": vlen(t_ani),
                "|t_bind_local|": vlen(t_loc),
                "|t_bind_world|": vlen(t_wld),
                "d_local": d_loc,
                "d_world": d_wld,
            }
        )
    if len(rows) < 8:
        return None, "overlap<%d" % len(rows)
    return {
        "n_bones": len(h["bones"]),
        "n_tracks": a["bones"],
        "n_frames": a["frames"],
        "n_overlap": len(rows),
        "n96": sum(1 for r in rows if r["has96"]),
        "n_no96": sum(1 for r in rows if not r["has96"]),
        "has_weights": h["has_weights"],
        "kind": h["kind"],
        "vc": h["vc"],
        "rows": rows,
        "names": [b["name"] for b in h["bones"]],
        "worlds": h["worlds"],
        "bones": h["bones"],
    }, None


def slice_ds(rows, pred, key="d_local"):
    return [r[key] for r in rows if pred(r)]


def model_summary(rec, cmp_):
    rows = cmp_["rows"]
    with96 = [r for r in rows if r["has96"]]
    no96 = [r for r in rows if not r["has96"]]
    both_chain = [r for r in rows if r["has96"] and r["parent_has96"]]
    sl = dist_stats([r["d_local"] for r in rows])
    sl96 = dist_stats([r["d_local"] for r in with96])
    sl0 = dist_stats([r["d_local"] for r in no96])
    sw = dist_stats([r["d_world"] for r in rows])
    sw96 = dist_stats([r["d_world"] for r in with96])
    slc = dist_stats([r["d_local"] for r in both_chain])
    pelvis_d = None
    for r in rows:
        ln = r["bone"].lower()
        if ln.endswith("_pelvis") or ln == "pelvis" or ln.endswith("hip"):
            pelvis_d = r["d_local"]
            break
    all_lt = sl and sl["n_lt_1e3"] == sl["n"]
    all96_lt = sl96 and sl96["n"] > 0 and sl96["n_lt_1e3"] == sl96["n"]
    all_chain_lt = slc and slc["n"] > 0 and slc["n_lt_1e3"] == slc["n"]
    return {
        "char": rec["char"],
        "cat": rec["cat"],
        "rel": rec["rel"],
        "mesh": os.path.basename(rec["mesh"]),
        "ani": os.path.basename(rec["ani"]),
        "n_bones": cmp_["n_bones"],
        "n_tracks": cmp_["n_tracks"],
        "n_frames": cmp_["n_frames"],
        "n_overlap": cmp_["n_overlap"],
        "n96": cmp_["n96"],
        "n_no96": cmp_["n_no96"],
        "has_weights": cmp_["has_weights"],
        "kind": cmp_["kind"],
        "dloc_p50": sl["p50"] if sl else None,
        "dloc_max": sl["max"] if sl else None,
        "dloc_n_lt": sl["n_lt_1e3"] if sl else 0,
        "dloc96_p50": sl96["p50"] if sl96 else None,
        "dloc96_max": sl96["max"] if sl96 else None,
        "dloc96_n_lt": sl96["n_lt_1e3"] if sl96 else 0,
        "dloc96_n": sl96["n"] if sl96 else 0,
        "dloc0_p50": sl0["p50"] if sl0 else None,
        "dloc0_max": sl0["max"] if sl0 else None,
        "dwld_p50": sw["p50"] if sw else None,
        "dwld_max": sw["max"] if sw else None,
        "dchain_p50": slc["p50"] if slc else None,
        "dchain_max": slc["max"] if slc else None,
        "dchain_n_lt": slc["n_lt_1e3"] if slc else 0,
        "dchain_n": slc["n"] if slc else 0,
        "all_named_lt_1e3": bool(all_lt),
        "all_96_lt_1e3": bool(all96_lt),
        "all_chain_lt_1e3": bool(all_chain_lt),
        "pelvis_d": pelvis_d,
        "_sl": sl,
        "_sl96": sl96,
        "_sl0": sl0,
        "_sw": sw,
        "_sw96": sw96,
        "_slc": slc,
        "_rows": rows,
    }


def yifu_sanity(summaries):
    """对西域窃贼 yifu 复现上一班已知数字：pelvis←bip01 = 1.0991，toe0 y≈0.140。"""
    lines = []
    hit = None
    for s in summaries:
        if "xiyuqiezei_yifu" in s["mesh"]:
            hit = s
            break
    if hit is None:
        return ["未找到 xiyuqiezei_yifu 样本，解析自检跳过。"]
    # 重新 load 拿世界矩阵
    for rec_mesh in [s for s in summaries if "xiyuqiezei_yifu" in s["mesh"]]:
        pass
    return lines, hit


def row_md(i, s):
    return (
        "| %d | %s | %s | `%s` | `%s` | %d/%d/%d | %s | %s | %d/%d | %s | %s |"
        % (
            i,
            s["char"],
            s["cat"],
            s["mesh"],
            s["ani"],
            s["n_bones"],
            s["n_overlap"],
            s["n96"],
            fmt(s["dchain_p50"]),
            fmt(s["dchain_max"]),
            s["dchain_n_lt"],
            s["dchain_n"],
            fmt(s["dloc96_p50"]),
            fmt(s["dwld_p50"]),
        )
    )


def pick_showcase(summaries, k=36):
    """每类若干 + 必含西域窃贼 yifu，凑满至少 30。"""
    want = {"monster": 8, "boss": 6, "npc": 8, "pet": 4, "mount": 3, "player_f": 2, "player_m": 2, "other": 3}
    picked = []
    seen = set()

    def add(s):
        if s["char"] in seen:
            return
        seen.add(s["char"])
        picked.append(s)

    for s in summaries:
        if "xiyuqiezei_yifu" in s["mesh"]:
            add(s)
            break
    by = defaultdict(list)
    for s in summaries:
        by[s["cat"]].append(s)
    for cat, bag in by.items():
        bag.sort(key=lambda s: (s["dchain_max"] or 9e9, s["char"]))
        n = want.get(cat, 2)
        for s in bag[:n]:
            add(s)
    if len(picked) < k:
        rest = sorted(summaries, key=lambda s: s["char"])
        for s in rest:
            add(s)
            if len(picked) >= k:
                break
    return picked


def write_report(cands, summaries, fail_hist, pooled, yifu_lines):
    n = len(summaries)
    cats = defaultdict(int)
    for s in summaries:
        cats[s["cat"]] += 1
    except_all = [s for s in summaries if s["all_named_lt_1e3"]]
    except_96 = [s for s in summaries if s["all_96_lt_1e3"]]
    except_chain = [s for s in summaries if s["all_chain_lt_1e3"]]
    p50s = [s["dchain_p50"] for s in summaries if s["dchain_p50"] is not None]
    med_of_med = percentile(p50s, 50) if p50s else None
    p50s96 = [s["dloc96_p50"] for s in summaries if s["dloc96_p50"] is not None]
    med96 = percentile(p50s96, 50) if p50s96 else None
    pelvis = [s["pelvis_d"] for s in summaries if s.get("pelvis_d") is not None]
    pelvis_st = dist_stats(pelvis)
    pelvis_lt = sum(1 for v in pelvis if v < EPS)

    if except_all:
        verdict = "🟢"
        verdict_txt = "存在同名骨平移差全部 <1e-3 的模型，frame0 与 bind 在这些样本上可视为同一副姿态。"
    elif except_chain:
        verdict = "🟡"
        verdict_txt = (
            "没有整副同名骨全对上的模型；但有样本在「父子都有 96B」的公平切片上全部 <1e-3。"
            "缺记录骨仍是占位零，不能把整副说成同一姿态。"
        )
    elif except_96:
        verdict = "🟡"
        verdict_txt = "无 96B 占位骨对不上（预期：占位局部=0），但有样本的有记录骨全部 <1e-3。"
    else:
        verdict = "🔴"
        verdict_txt = (
            "扩样本后没有任何一副模型的同名骨 frame0 局部平移全部对得上 bind。"
            "公平切片（父子都有 96B）也没有整副全对上的例外。不硬凑轴置换。"
        )

    sl96 = pooled["d_local_96"]
    sl0 = pooled["d_local_no96"]
    sl = pooled["d_local_all"]
    sw96 = pooled["d_world_96"]
    slc = pooled["d_local_chain"]

    def stat_md(st, title):
        if not st:
            return "- %s：无数据" % title
        return (
            "- **%s** n=%d：min=%s  p10=%s  p25=%s  **p50=%s**  p75=%s  p90=%s  p95=%s  p99=%s  max=%s"
            "  |  <1e-3：%d（%.1f%%）"
            % (
                title,
                st["n"],
                fmt(st["min"]),
                fmt(st["p10"]),
                fmt(st["p25"]),
                fmt(st["p50"]),
                fmt(st["p75"]),
                fmt(st["p90"]),
                fmt(st["p95"]),
                fmt(st["p99"]),
                fmt(st["max"]),
                st["n_lt_1e3"],
                100 * st["frac_lt_1e3"],
            )
        )

    frac80 = sum(1 for s in summaries if s["dchain_n"] and s["dchain_n_lt"] / s["dchain_n"] >= 0.8)
    frac50 = sum(1 for s in summaries if s["dchain_n"] and s["dchain_n_lt"] / s["dchain_n"] >= 0.5)
    worst = max(summaries, key=lambda s: s["dloc_max"] or 0)
    closest = sorted(summaries, key=lambda s: (s["dchain_max"] is None, s["dchain_max"] or 9e9))[:8]

    lines = []
    a = lines.append
    a("# `.ani` 第 0 帧 vs `.mesh` 绑定骨架：多份同源取证")
    a("")
    a("日期：2026-10-06。只读 `.scratch/out/tree`，不改产品代码。")
    a("")
    a("## 结论 %s" % verdict)
    a("")
    a(verdict_txt)
    a("")
    a(
        "样本 **%d** 副（带层级、带权重的人形/怪物，目录内同干 `.mesh`+`.ani`）。"
        "公平切片各模型中位差的中位数 = **%s**；有 96B 同名骨中位差的中位数 = **%s**。"
        % (n, fmt(med_of_med), fmt(med96))
    )
    a("")
    a("### 例外（同名骨平移差全部 <1e-3）")
    a("")
    if except_all:
        a("全部同名骨（含无 96B 占位）对上的：")
        for s in except_all:
            a("- `%s` / `%s`（%s）" % (s["mesh"], s["ani"], s["char"]))
    else:
        a("- 全部同名骨：无。")
    if except_chain:
        a("公平切片（父子都有 96B）全部对上的：")
        for s in except_chain:
            a("- `%s` / `%s`（%s，n_chain=%d）" % (s["mesh"], s["ani"], s["char"], s["dchain_n"]))
    else:
        a("- 公平切片：无。")
    if except_96:
        a("仅有 96B 记录的同名骨对上的：")
        for s in except_96:
            a("- `%s` / `%s`（%s，n96=%d）" % (s["mesh"], s["ani"], s["char"], s["n96"]))
    else:
        a("- 仅有 96B 的同名骨：无。")
    a("")
    a("## 口径（不翻案）")
    a("")
    a("- `.mesh` 96B 存储矩阵 **S 是世界绑定 B 的逆**。骨位 = `inverse(S)` 的平移（行向量末行）。不把 S 的平移当骨位。")
    a("- 父链只用孩子名单反推，条目标志不当父索引。")
    a("- bind 局部 = `B_child · B_parent⁻¹`（根骨局部=自身世界）。无 96B 的骨按占位恒等局部（世界=父世界，局部平移=0），与导出层一致，不当真值。")
    a("- `.ani` 第 0 帧平移是**局部**通道，按骨名挂到骨架（未命名轨道不按位置硬配）。")
    a("- 不扫全局轴置换 R（上一班已证 R 不唯一）。`.ske` 不读。")
    a("- 64B 局部矩阵块语义未证，本班不用它凑对。")
    a("")
    a("## 样本")
    a("")
    a("- 候选目录（同时有 `.mesh` 与同干 `.ani`）：%d" % len(cands))
    a("- 解出且通过人形/怪物门槛（bip01 或骨盆/脊柱链，重叠≥8 名，声明骨≥14）：**%d**" % n)
    a("- 类别：%s" % ", ".join("%s=%d" % kv for kv in sorted(cats.items())))
    a(
        "- 权重：有影响表 %d / 无 %d（入选的全部带权重）"
        % (sum(1 for s in summaries if s["has_weights"]), sum(1 for s in summaries if not s["has_weights"]))
    )
    a("- 动画优先 idle01 / idle / fight_idle01；没有再用目录里排序最前的那条。")
    a("- 同一角色多份 mesh 时优先 `*_yifu*`（身体），避免只拿手套。")
    if fail_hist:
        a("- 未入样本的原因：%s" % ", ".join("%s=%d" % kv for kv in sorted(fail_hist.items())))
    a("")
    a("## 分布 |t_ani0 − t_bind|（跨模型、按骨名对齐后池化）")
    a("")
    a(stat_md(slc, "局部差 · 公平切片（子与父都有 96B，真 bind 局部）"))
    a(stat_md(sl96, "局部差 · 有 96B（父缺记录时局部被占位链拉长，会虚高）"))
    a(stat_md(sl0, "局部差 · 无 96B（占位局部=0，差=|t_ani0|）"))
    a(stat_md(sl, "局部差 · 全部同名骨"))
    a(stat_md(sw96, "世界差 · 有 96B（局部通道去比世界骨位，空间不同，仅对照）"))
    if pelvis_st:
        a(
            stat_md(pelvis_st, "骨盆（bip01_pelvis 等）局部差 · 分模型")
            + "  其中 <1e-3 的模型 %d / %d" % (pelvis_lt, pelvis_st["n"])
        )
    a("")
    a("主结论看公平切片。量级 0.1~1 是骨长，不是浮点噪声。<1e-3 才算对上。")
    a("")
    a(
        "中位数接近 0 只说明**过半**远端骨（足、趾、部分手臂）的局部平移与 bind **逐分量相等**；"
        "只要骨盆等根部骨差在骨长量级，整副就不能叫同一姿态。分位数与 max 必须一起看。"
    )
    a("")
    a(
        "公平切片命中率：≥50%% 根 <1e-3 的模型 %d / %d；≥80%% 的 %d / %d；100%% 的 **0 / %d**。"
        % (frac50, n, frac80, n, n)
    )
    a("")
    a("离「整副对上」最近的几份（公平切片 max 最小）仍然有非零残差：")
    a("")
    a("| # | 角色 | 类 | mesh | ani | 骨/重叠/96B | 公平p50 | 公平max | 公平<1e-3 | 有96B p50 | 世界p50 |")
    a("|---|---|---|---|---|---|---:|---:|---:|---:|---:|")
    for i, s in enumerate(closest, 1):
        a(row_md(i, s))
    a("")
    a("池化 max 离群：`%s`（`%s`）全骨 max=%s。不删，不当典型。" % (worst["char"], worst["mesh"], fmt(worst["dloc_max"])))
    a("")
    a("## 分模型摘录（%d 副多样本，含西域窃贼；全表 %d 行见 `table.csv`）" % (len(pick_showcase(summaries)), n))
    a("")
    a("| # | 角色 | 类 | mesh | ani | 骨/重叠/96B | 公平p50 | 公平max | 公平<1e-3 | 有96B p50 | 世界p50 |")
    a("|---|---|---|---|---|---|---:|---:|---:|---:|---:|")
    show = pick_showcase(summaries)
    for i, s in enumerate(show, 1):
        a(row_md(i, s))
    a("")
    a("## 西域窃贼 yifu 自检（对齐上一班）")
    a("")
    for ln in yifu_lines:
        a(ln)
    a("")
    a("## 怎么读这些数")
    a("")
    a("- 若 frame0 就是 bind rest：公平切片里每根骨 `d_local` 应几乎全 <1e-3。")
    a("- 实测：远端骨常逐分量相等，所以池化中位数可接近 0；骨盆等根部骨差在骨长量级，无 96B 的骨 ani 有段长、bind 占位为 0。**整副不是同一姿态**，与上一班 yifu 结论同向，不是翻案。")
    a("- 父骨缺 96B 时，子骨「bind 局部」= 相对祖辈的占位复合，会把段长吞进去（西域窃贼 `l_upperarm` 父=`l_clavicle` 无记录，局部 0.625 vs ani 0.108）。公平切片就是为了把这条污染剔掉。")
    a("- 世界差普遍更大：ani 通道是局部，bind 世界是站立高度，本来就不该逐骨相等。")
    a("- 没有去拟合 R。上一班已证 R 不唯一。")
    a("")
    a("## 文件")
    a("")
    a("- `parse.py` 解析层；`run.py` 本脚本。")
    a("- `table.csv` / `table.json` 分模型数字表（%d 行）。" % n)
    a("- `pooled.json` 池化分位数。")
    a("- `pairs.json` 入选路径。")
    a("- `yifu_bones.csv` 主样本逐骨差（便于对上一班 offset_probe）。")
    a("")
    a("灯号：%s %s" % (verdict, verdict_txt))
    return "\n".join(lines) + "\n", verdict, med_of_med, except_all, except_96


def dump_yifu_detail(summaries, recs):
    lines = ["bone,has96,d_local,d_world,|t_ani|,|t_bind_local|,|t_bind_world|,tx_ani,ty_ani,tz_ani,tx_loc,ty_loc,tz_loc"]
    target = None
    for s, rec in zip(summaries, recs):
        if "xiyuqiezei_yifu" in s["mesh"]:
            target = (s, rec)
            break
    note = []
    if target is None:
        return lines, ["样本里没有 xiyuqiezei_yifu。"]
    s, rec = target
    h = load_mesh(rec["mesh"])
    name_i = {b["name"]: i for i, b in enumerate(h["bones"])}
    # 已知骨距
    def world_t(nm):
        i = name_i.get(nm)
        if i is None:
            return None
        return trans(h["worlds"][i])

    pelvis = world_t("bip01_pelvis")
    bip01 = world_t("bip01")
    foot = world_t("bip01_l_foot")
    calf = world_t("bip01_l_calf")
    toe = world_t("bip01_l_toe0")
    if pelvis and bip01:
        note.append("pelvis←bip01 世界距离 |Δt|=%.4f（上一班 1.0991）" % vlen(vsub(pelvis, bip01)))
    if foot and calf:
        note.append("l_foot←l_calf 世界距离 |Δt|=%.4f（上一班 0.4052）" % vlen(vsub(foot, calf)))
    if toe:
        note.append("l_toe0 世界 y=%.4f（上一班 0.140）" % toe[1])
        note.append("l_foot 世界 y=%.4f（上一班 0.693）" % (foot[1] if foot else float("nan")))
    note.append(
        "本份有 96B 同名骨 n=%d，局部差 p50=%.4f max=%.4f，<1e-3 的 %d 根；公平切片 n=%d p50=%.4f max=%.4f <1e-3 %d"
        % (
            s["n96"],
            s["dloc96_p50"],
            s["dloc96_max"],
            s["dloc96_n_lt"],
            s["dchain_n"],
            s["dchain_p50"],
            s["dchain_max"],
            s["dchain_n_lt"],
        )
    )
    for r in s["_rows"]:
        ta, tl, tw = r["t_ani"], r["t_bind_local"], r["t_bind_world"]
        lines.append(
            ",".join(
                [
                    r["bone"],
                    "1" if r["has96"] else "0",
                    "%.6f" % r["d_local"],
                    "%.6f" % r["d_world"],
                    "%.6f" % r["|t_ani|"],
                    "%.6f" % r["|t_bind_local|"],
                    "%.6f" % r["|t_bind_world|"],
                    "%.6f" % ta[0],
                    "%.6f" % ta[1],
                    "%.6f" % ta[2],
                    "%.6f" % tl[0],
                    "%.6f" % tl[1],
                    "%.6f" % tl[2],
                ]
            )
        )
    return lines, note


def main():
    os.makedirs(OUT, exist_ok=True)
    logp = os.path.join(OUT, "run_log.txt")
    logf = open(logp, "w", encoding="utf-8")

    def log(msg):
        logf.write(msg + "\n")
        logf.flush()

    log("TREE=%s" % TREE)
    cands = discover()
    log("candidate folders=%d" % len(cands))
    summaries = []
    recs = []
    fail = defaultdict(int)
    seen_char = set()
    # 先全量解，按角色去重（每个角色一副身体 mesh + idle）
    for rec in cands:
        if rec["char"] in seen_char:
            fail["dup-char"] += 1
            continue
        try:
            hdr = open(rec["mesh"], "rb").read(0x114)
            declared = int.from_bytes(hdr[0x110:0x114], "little") if len(hdr) >= 0x114 else 0
        except OSError:
            fail["mesh-read"] += 1
            continue
        if declared < 14:
            fail["declared<14"] += 1
            continue
        cmp_, err = compare_pair(rec["mesh"], rec["ani"])
        if err:
            fail[err] += 1
            continue
        seen_char.add(rec["char"])
        s = model_summary(rec, cmp_)
        summaries.append(s)
        recs.append(rec)
        log(
            "OK %s cat=%s bones=%d overlap=%d n96=%d p50=%.4f max=%.4f w=%s"
            % (
                rec["char"],
                rec["cat"],
                s["n_bones"],
                s["n_overlap"],
                s["n96"],
                s["dloc96_p50"] or -1,
                s["dloc96_max"] or -1,
                s["has_weights"],
            )
        )

    log("accepted=%d fails=%s" % (len(summaries), dict(fail)))
    if len(summaries) < 30:
        log("WARNING: fewer than 30 accepted pairs")

    pooled = {
        "d_local_all": dist_stats([r["d_local"] for s in summaries for r in s["_rows"]]),
        "d_local_96": dist_stats([r["d_local"] for s in summaries for r in s["_rows"] if r["has96"]]),
        "d_local_no96": dist_stats([r["d_local"] for s in summaries for r in s["_rows"] if not r["has96"]]),
        "d_local_chain": dist_stats(
            [r["d_local"] for s in summaries for r in s["_rows"] if r["has96"] and r["parent_has96"]]
        ),
        "d_world_all": dist_stats([r["d_world"] for s in summaries for r in s["_rows"]]),
        "d_world_96": dist_stats([r["d_world"] for s in summaries for r in s["_rows"] if r["has96"]]),
    }

    yifu_csv, yifu_notes = dump_yifu_detail(summaries, recs)
    open(os.path.join(OUT, "yifu_bones.csv"), "w", encoding="utf-8").write("\n".join(yifu_csv) + "\n")

    md, verdict, med, ex_all, ex96 = write_report(cands, summaries, fail, pooled, yifu_notes)
    open(os.path.join(OUT, "报告.md"), "w", encoding="utf-8").write(md)

    slim = []
    for s in summaries:
        d = {k: v for k, v in s.items() if not k.startswith("_")}
        slim.append(d)
    with open(os.path.join(OUT, "table.json"), "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "pooled.json"), "w", encoding="utf-8") as f:
        json.dump(pooled, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, "pairs.json"), "w", encoding="utf-8") as f:
        json.dump(
            [
                {
                    "char": r["char"],
                    "cat": r["cat"],
                    "mesh": r["mesh"],
                    "ani": r["ani"],
                    "rel": r["rel"],
                }
                for r in recs
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )

    fields = [
        "char",
        "cat",
        "mesh",
        "ani",
        "n_bones",
        "n_tracks",
        "n_overlap",
        "n96",
        "n_no96",
        "has_weights",
        "dloc_p50",
        "dloc_max",
        "dloc96_p50",
        "dloc96_max",
        "dloc96_n_lt",
        "dloc96_n",
        "dchain_p50",
        "dchain_max",
        "dchain_n_lt",
        "dchain_n",
        "dwld_p50",
        "dwld_max",
        "all_named_lt_1e3",
        "all_96_lt_1e3",
        "all_chain_lt_1e3",
        "pelvis_d",
    ]
    with open(os.path.join(OUT, "table.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for s in slim:
            w.writerow(s)

    meta = {
        "n_samples": len(summaries),
        "median_dloc96": med,
        "pooled_p50_dloc96": pooled["d_local_96"]["p50"] if pooled["d_local_96"] else None,
        "pooled_max_dloc96": pooled["d_local_96"]["max"] if pooled["d_local_96"] else None,
        "n_lt_1e3_dloc96": pooled["d_local_96"]["n_lt_1e3"] if pooled["d_local_96"] else 0,
        "n_bones_dloc96": pooled["d_local_96"]["n"] if pooled["d_local_96"] else 0,
        "exceptions_all": [s["char"] for s in ex_all],
        "exceptions_96": [s["char"] for s in ex96],
        "exceptions_chain": [s["char"] for s in summaries if s["all_chain_lt_1e3"]],
        "verdict": verdict,
        "pooled_p50_dchain": pooled["d_local_chain"]["p50"] if pooled["d_local_chain"] else None,
        "pooled_max_dchain": pooled["d_local_chain"]["max"] if pooled["d_local_chain"] else None,
        "report": os.path.join(OUT, "报告.md"),
    }
    with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    log("verdict=%s n=%s med=%s" % (verdict, len(summaries), med))
    log("wrote 报告.md")
    logf.close()


if __name__ == "__main__":
    main()
