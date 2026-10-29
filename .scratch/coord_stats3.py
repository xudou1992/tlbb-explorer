"""任务2 补充统计（一遍全量）+ 候选样本体检。只读。

- 上轴偏离角：col1(=Y 轴的像) 与 Y 轴夹角，分位数 p50/p90/p99/p99.9/max
- 平移 |x|/|y|/|z| 分位数（Y-up 旁证：高度量级 << 水平量级）
- 精确偏航计数：0 / ±90 / 180 的实例数
- 旋转块全零实例数（det≈0 的真身）
- m5<0（上下翻转）实例数
- 非统一缩放实例的网格名 top10
- understated（instances.len() > declared）文件数
- 候选样本文件：字节数 / tag / 实例数 / has_tail / understated / 纯偏航占比 / det<0 数 /
  格号吻合数 / 上偏角 max / understated
输出 coord_stats3.json / .txt
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from coord_scene_lib import parse_scene

TREE = Path(r"D:\TLGL\.scratch\out\tree\mobile_maps")
OUT_JSON = Path(r"D:\TLGL\.scratch\coord_stats3.json")
OUT_TXT = Path(r"D:\TLGL\.scratch\coord_stats3.txt")

CANDS = {
    "grid_749": None,        # (map, file) 后面填
    "w1351_ll_dl_002__1_1_-5.scene": ("w1351_ll_dl_002", "1_1_-5.scene"),
    "w1351_ll_dl_002__1_5_-1.scene": ("w1351_ll_dl_002", "1_5_-1.scene"),
    "w1351_fb_songliao_001__1_-1_-6.scene": ("w1351_fb_songliao_001", "1_-1_-6.scene"),
    "w1351_ll_xh_001__1_5_-9.scene": ("w1351_ll_xh_001", "1_5_-9.scene"),
}

up_dev = []          # 上轴偏离角（度）
ax = []              # |x|
ay = []              # |y|
az = []              # |z|
yaw_exact = defaultdict(int)
zero_rot = 0
m5_neg = 0
nonuni_names = defaultdict(int)
understated_files = 0
untailored = 0

samples = {}
sample_wish = {
    "w1351_ll_dl_002/1_1_-5.scene": "mirror_fence",
    "w1351_ll_dl_002/1_5_-1.scene": "tilt",
    "w1351_fb_songliao_001/1_-1_-6.scene": "grid_miss",
    "w1351_ll_xh_001/1_5_-9.scene": "zero_rot",
}


def col_norm(m, c):
    return math.sqrt(m[c] ** 2 + m[c + 1] ** 2 + m[c + 2] ** 2)


def pct(vals, q):
    vals = sorted(vals)
    i = min(len(vals) - 1, int(q * (len(vals) - 1)))
    return vals[i]


for mapdir in sorted(TREE.iterdir()):
    if not mapdir.is_dir():
        continue
    mapname = mapdir.name
    for f in sorted(mapdir.glob("*.scene")):
        raw = f.read_bytes()
        kind, grid = parse_scene(raw)
        if kind != "ok":
            continue
        if grid["understated"]:
            understated_files += 1
        if not grid["has_tail"]:
            untailored += 1
        rel = f"{mapname}/{f.name}"
        is_sample = rel in sample_wish
        st = {
            "bytes": len(raw), "tag": grid["tag"],
            "instances": len(grid["instances"]), "declared": grid["declared"],
            "has_tail": grid["has_tail"], "tail_bytes": grid["tail_bytes"],
            "understated": grid["understated"],
            "pure_yaw": 0, "det_neg": 0, "grid_match": 0, "grid_total": 0,
            "up_dev_max": 0.0, "zero_rot": 0, "nonuniform": 0,
        } if is_sample else None
        if st:
            st["grid_segs"] = f.name[:-len(".scene")]

        for i, inst in enumerate(grid["instances"]):
            m = inst["m"]
            sx, sy, sz = col_norm(m, 0), col_norm(m, 4), col_norm(m, 8)
            dev = math.degrees(math.acos(max(-1.0, min(1.0, abs(m[5]) / sy)))) if sy > 0 else 90.0
            up_dev.append(dev)
            ax.append(abs(m[12]))
            ay.append(abs(m[13]))
            az.append(abs(m[14]))
            pure = (m[1] == 0.0 and m[4] == 0.0 and m[6] == 0.0 and m[9] == 0.0)
            if pure:
                yaw = math.degrees(math.atan2(m[8], m[0]))
                for target, lbl in ((0.0, "0"), (90.0, "+90"), (-90.0, "-90"),
                                    (180.0, "180"), (-180.0, "-180")):
                    if abs(yaw - target) < 0.005:
                        yaw_exact[lbl] += 1
            if all(v == 0.0 for v in (m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10])):
                zero_rot += 1
                if st:
                    st["zero_rot"] += 1
            if m[5] < 0:
                m5_neg += 1
            mx_, mn_ = max(sx, sy, sz), min(sx, sy, sz)
            uniform = (mx_ - mn_) <= 1e-3 * mx_ if mx_ > 0 else False
            if not uniform:
                nonuni_names[inst["name"]] += 1
                if st:
                    st["nonuniform"] += 1
            if pure:
                if st:
                    st["pure_yaw"] += 1
            d = (m[0] * (m[5] * m[10] - m[6] * m[9])
                 - m[1] * (m[4] * m[10] - m[6] * m[8])
                 + m[2] * (m[4] * m[9] - m[5] * m[8]))
            if d < 0 and st:
                st["det_neg"] += 1
            if st:
                segs = f.name[: -len(".scene")].split("_")
                try:
                    isegs = [int(s) for s in segs]
                except ValueError:
                    isegs = None
                if isegs and len(isegs) == 3:
                    st["grid_total"] += 1
                    if isegs[1] == math.floor(m[12] / 32) and isegs[2] == math.floor(m[14] / 32):
                        st["grid_match"] += 1
                if dev > st["up_dev_max"]:
                    st["up_dev_max"] = dev
        if st:
            samples[rel] = st

# 候选：最小的 749（无尾）与 753（无尾 / 有尾）
small749 = sorted(
    ((p.stat().st_size, p) for mp in TREE.iterdir() if mp.is_dir()
     for p in mp.glob("*.scene")),
    key=lambda t: t[0])
cand_small = []
for size, p in small749:
    raw = p.read_bytes()
    kind, grid = parse_scene(raw)
    if kind != "ok" or not grid["instances"]:
        continue
    cand_small.append({
        "rel": f"{p.parent.name}/{p.name}", "bytes": size, "tag": grid["tag"],
        "instances": len(grid["instances"]), "declared": grid["declared"],
        "has_tail": grid["has_tail"], "understated": grid["understated"],
        "pure_yaw_ratio": round(
            sum(1 for i in grid["instances"]
                if i["m"][1] == 0 and i["m"][4] == 0 and i["m"][6] == 0 and i["m"][9] == 0)
            / len(grid["instances"]), 4),
    })
by_tag = defaultdict(list)
for c in cand_small:
    if not c["understated"] and c["instances"] >= 2:
        by_tag[c["tag"]].append(c)
smallest = {}
for t in (749, 753, 605, 592, 324, 596, 601):
    no_tail = [c for c in by_tag[t] if not c["has_tail"]]
    with_tail = [c for c in by_tag[t] if c["has_tail"]]
    smallest[str(t)] = {
        "no_tail_min": min(no_tail, key=lambda c: c["bytes"]) if no_tail else None,
        "with_tail_min": min(with_tail, key=lambda c: c["bytes"]) if with_tail else None,
    }

out = {
    "up_dev_pct": {
        "p50": pct(up_dev, 0.50), "p90": pct(up_dev, 0.90), "p99": pct(up_dev, 0.99),
        "p999": pct(up_dev, 0.999), "max": up_dev and max(up_dev),
        "over_1deg": sum(1 for v in up_dev if v > 1.0),
        "over_5deg": sum(1 for v in up_dev if v > 5.0),
        "over_45deg": sum(1 for v in up_dev if v > 45.0),
        "over_89deg": sum(1 for v in up_dev if v > 89.0),
    },
    "abs_translation_pct": {
        "x": {q: pct(ax, q) for q in (0.5, 0.99, 0.999)},
        "y": {q: pct(ay, q) for q in (0.5, 0.99, 0.999)},
        "z": {q: pct(az, q) for q in (0.5, 0.99, 0.999)},
        "y_max": max(ay), "x_max": max(ax), "z_max": max(az),
    },
    "yaw_exact_counts": dict(yaw_exact),
    "zero_rotation_block_instances": zero_rot,
    "m5_negative_instances": m5_neg,
    "understated_files": understated_files,
    "nonuniform_top10": sorted(nonuni_names.items(), key=lambda kv: -kv[1])[:10],
    "nonuniform_distinct_names": len(nonuni_names),
    "candidate_samples": smallest,
    "sample_files_detail": samples,
}
OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

lines = []
lines.append(f"上轴偏离角（col1 与 Y 轴夹角）: p50={out['up_dev_pct']['p50']:.4f}°  "
             f"p90={out['up_dev_pct']['p90']:.4f}°  p99={out['up_dev_pct']['p99']:.4f}°  "
             f"p99.9={out['up_dev_pct']['p999']:.4f}°  max={out['up_dev_pct']['max']:.4f}°")
lines.append(f"  >1°: {out['up_dev_pct']['over_1deg']:,}  >5°: {out['up_dev_pct']['over_5deg']:,}  "
             f">45°: {out['up_dev_pct']['over_45deg']:,}  >89°: {out['up_dev_pct']['over_89deg']:,}")
lines.append(f"|x| p50/p99/p99.9: {out['abs_translation_pct']['x']}")
lines.append(f"|y| p50/p99/p99.9: {out['abs_translation_pct']['y']}  max={out['abs_translation_pct']['y_max']}")
lines.append(f"|z| p50/p99/p99.9: {out['abs_translation_pct']['z']}")
lines.append(f"精确偏航计数: {out['yaw_exact_counts']}")
lines.append(f"旋转块全零实例: {out['zero_rotation_block_instances']}")
lines.append(f"m[5]<0 实例: {out['m5_negative_instances']}")
lines.append(f"understated 文件: {out['understated_files']}")
lines.append(f"非统一缩放: {sum(nonuni_names.values()):,} 条 / 不同网格名 {out['nonuniform_distinct_names']}")
for nm, n in out["nonuniform_top10"]:
    lines.append(f"    {nm}: {n}")
lines.append("")
lines.append("候选样本（每 tag 最小、无 understated、>=2 实例）:")
for t, c in smallest.items():
    nt = c["no_tail_min"]
    wt = c["with_tail_min"]
    lines.append(f"  tag={t}: 无尾 {nt and (nt['rel'], nt['bytes'], nt['instances'], nt['pure_yaw_ratio'])}")
    lines.append(f"          有尾 {wt and (wt['rel'], wt['bytes'], wt['instances'])}")
lines.append("")
lines.append("指定样本体检:")
for rel, st in samples.items():
    lines.append(f"  {rel}: bytes={st['bytes']} tag={st['tag']} n={st['instances']} "
                 f"declared={st['declared']} has_tail={st['has_tail']} understated={st['understated']} "
                 f"pure_yaw={st['pure_yaw']}/{st['instances']} det<0={st['det_neg']} "
                 f"grid={st['grid_match']}/{st['grid_total']} up_dev_max={st['up_dev_max']:.2f}° "
                 f"zero_rot={st['zero_rot']} nonuni={st['nonuniform']}")
OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
print("done")
