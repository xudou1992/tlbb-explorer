"""任务2+3：全量契约审计（mobile_maps 树全部可解析 .scene，只读）。

对每个实例（复刻 scene.rs 口径走出的头部段）计算：
- 纯偏航：m[1]=m[4]=m[6]=m[9]=0（精确 0 与 1e-5 宽容两口径）
- Y-up：m[4]=m[6]=0（+Y 轴的像仍在 Y 轴上）
- det(3x3) 符号与退化
- 缩放：三列范数 sx/sy/sz，是否逐实例统一（max/min<=1e-3 相对差）
- 正交：列两两夹角余弦 |cos|>1e-3 记违反
- 32 格：floor(m[12]/32)、floor(m[14]/32) 与文件名数字段的三种配对假设
- 偏航角分布：atan2(m[8], m[0])
- m[13] 整数占比 / 高度量级（Y-up 旁证）
- m[5]（契约里当缩放读的那个）分布

异常清单（det<0 / 非纯偏航 / 非统一缩放 / 正交违反 / 格号不吻合）落 JSON 供逐例回查。
输出 .scratch/coord_full_audit.json + coord_full_audit.txt
"""
import json
import math
import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from coord_scene_lib import parse_scene

TREE = Path(r"D:\TLGL\.scratch\out\tree\mobile_maps")
OUT_JSON = Path(r"D:\TLGL\.scratch\coord_full_audit.json")
OUT_TXT = Path(r"D:\TLGL\.scratch\coord_full_audit.txt")

EPS_PITCH = 1e-5
EPS_SCALE_REL = 1e-3
EPS_COS = 1e-3
GR = 32.0

cnt = defaultdict(int)
tag_stat = defaultdict(lambda: defaultdict(int))
scale_hist = defaultdict(int)          # m[5] 量化到 0.01 -> 计数
yaw_hist = defaultdict(int)            # 每 10° 一桶
m13_int = 0
m13_nonint = 0
range_stat = {"x": [1e30, -1e30], "y": [1e30, -1e30], "z": [1e30, -1e30]}

anomalies = {"det_neg": [], "not_pure_yaw": [], "scale_nonuniform": [],
             "orth_violation": [], "grid_mismatch": [], "det_zero": []}

grid_hyp = {"H1_seg2_seg3": 0, "H1_miss": 0,
            "H2_seg1_seg2": 0, "H3_seg1_seg3": 0}
grid_files = 0          # 文件名为全数字段的格子
grid_files_nonnum = 0
grid_mismatch_examples = []

per_map_inst = defaultdict(int)
per_map_grid = defaultdict(lambda: [0, 0])  # [match, total]

Dali = "w1351_ll_dl_002"
dali_stat = defaultdict(int)
dali_files_753 = 0


def col_norm(m, c):
    return math.sqrt(m[c] * m[c] + m[c + 1] * m[c + 1] + m[c + 2] * m[c + 2])


def det3(m):
    a = (m[0], m[1], m[2])
    b = (m[4], m[5], m[6])
    c = (m[8], m[9], m[10])
    return (a[0] * (b[1] * c[2] - b[2] * c[1])
            - a[1] * (b[0] * c[2] - b[2] * c[0])
            + a[2] * (b[0] * c[1] - b[1] * c[0]))


def cos_between(m, c1, c2):
    n1 = col_norm(m, c1)
    n2 = col_norm(m, c2)
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    d = m[c1] * m[c2] + m[c1 + 1] * m[c2 + 1] + m[c1 + 2] * m[c2 + 2]
    return d / (n1 * n2)


def add_anom(bucket, mapname, fname, idx, inst, extra):
    if len(anomalies[bucket]) < 400:
        anomalies[bucket].append({
            "map": mapname, "file": fname, "record": idx,
            "name": inst["name"],
            "matrix": list(inst["m"]),
            **extra,
        })


for mapdir in sorted(TREE.iterdir()):
    if not mapdir.is_dir():
        continue
    mapname = mapdir.name
    for f in sorted(mapdir.glob("*.scene")):
        raw = f.read_bytes()
        kind, grid = parse_scene(raw)
        if kind != "ok":
            continue
        fname = f.name
        stem = fname[: -len(".scene")]
        segs = stem.split("_")
        try:
            isegs = [int(s) for s in segs]
        except ValueError:
            isegs = None

        for i, inst in enumerate(grid["instances"]):
            m = inst["m"]
            per_map_inst[mapname] += 1
            cnt["instances"] += 1
            tag_stat[grid["tag"]]["instances"] += 1

            x, y, z = m[12], m[13], m[14]
            for key, v in (("x", x), ("y", y), ("z", z)):
                r = range_stat[key]
                if v < r[0]:
                    r[0] = v
                if v > r[1]:
                    r[1] = v

            # ---- 纯偏航 / Y-up ----
            pitch_roll = not (m[1] == 0.0 and m[4] == 0.0
                              and m[6] == 0.0 and m[9] == 0.0)
            pitch_roll_loose = not (abs(m[1]) < EPS_PITCH and abs(m[4]) < EPS_PITCH
                                    and abs(m[6]) < EPS_PITCH and abs(m[9]) < EPS_PITCH)
            yup = (m[4] == 0.0 and m[6] == 0.0)
            if pitch_roll:
                cnt["not_pure_yaw_exact"] += 1
                tag_stat[grid["tag"]]["not_pure_yaw"] += 1
                add_anom("not_pure_yaw", mapname, fname, i, inst, {
                    "offenders": {"m1": m[1], "m4": m[4], "m6": m[6], "m9": m[9]},
                    "loose": pitch_roll_loose,
                })
            if pitch_roll_loose:
                cnt["not_pure_yaw_1e5"] += 1
            if yup:
                cnt["yup_ok"] += 1
            else:
                cnt["yup_violation"] += 1

            # ---- det / 正交 ----
            d = det3(m)
            if d < 0:
                cnt["det_neg"] += 1
                add_anom("det_neg", mapname, fname, i, inst, {"det": d})
            elif abs(d) < 1e-9:
                cnt["det_zero"] += 1
                add_anom("det_zero", mapname, fname, i, inst, {"det": d})
            else:
                cnt["det_pos"] += 1
            bad_cos = max(
                abs(cos_between(m, 0, 4)),
                abs(cos_between(m, 0, 8)),
                abs(cos_between(m, 4, 8)),
            )
            if bad_cos > EPS_COS:
                cnt["orth_violation"] += 1
                add_anom("orth_violation", mapname, fname, i, inst,
                         {"max_abs_cos": bad_cos, "det": d})

            # ---- 缩放 ----
            sx, sy, sz = col_norm(m, 0), col_norm(m, 4), col_norm(m, 8)
            mn, mx = min(sx, sy, sz), max(sx, sy, sz)
            rel = (mx - mn) / mx if mx > 0 else 0.0
            if rel <= EPS_SCALE_REL:
                cnt["scale_uniform"] += 1
            else:
                cnt["scale_nonuniform"] += 1
                add_anom("scale_nonuniform", mapname, fname, i, inst,
                         {"sx": sx, "sy": sy, "sz": sz, "rel": rel})
            scale_hist[round(m[5] * 100) / 100] += 1

            # ---- 偏航角 / m[13] ----
            if not pitch_roll:
                yaw = math.degrees(math.atan2(m[8], m[0]))
                yaw_hist[int(math.floor(((yaw + 180.0) % 360.0) / 10.0)) * 10] += 1
            if y == math.floor(y):
                m13_int += 1
            else:
                m13_nonint += 1

            # ---- 32 格对照 ----
            if isegs is not None and len(isegs) == 3:
                grid_files += 1
                gx = math.floor(x / GR)
                gz = math.floor(z / GR)
                gy = math.floor(y / GR)
                per_map_grid[mapname][1] += 1
                ok = False
                if isegs[1] == gx and isegs[2] == gz:
                    grid_hyp["H1_seg2_seg3"] += 1
                    per_map_grid[mapname][0] += 1
                    ok = True
                else:
                    grid_hyp["H1_miss"] += 1
                    if len(grid_mismatch_examples) < 50:
                        grid_mismatch_examples.append({
                            "map": mapname, "file": fname, "record": i,
                            "name": inst["name"],
                            "x": x, "y": y, "z": z,
                            "floor_x32": gx, "floor_y32": gy, "floor_z32": gz,
                            "segs": isegs,
                        })
                if isegs[0] == gx and isegs[1] == gz:
                    grid_hyp["H2_seg1_seg2"] += 1
                if isegs[0] == gx and isegs[2] == gz:
                    grid_hyp["H3_seg1_seg3"] += 1
            else:
                grid_files_nonnum += 1

            # ---- 大理对照口径（与 376 条审计同图）----
            if mapname == Dali:
                dali_stat["instances"] += 1
                if grid["tag"] == 753:
                    dali_stat["tag753_instances"] += 1
                if pitch_roll:
                    dali_stat["not_pure_yaw"] += 1
                if d < 0:
                    dali_stat["det_neg"] += 1

# ---------------- 汇总 ----------------
yaw_values = sorted(yaw_hist.items())
out = {
    "totals": {
        "instances": cnt["instances"],
        "yup_ok": cnt["yup_ok"],
        "yup_violation": cnt["yup_violation"],
        "pure_yaw_exact": cnt["instances"] - cnt["not_pure_yaw_exact"],
        "not_pure_yaw_exact": cnt["not_pure_yaw_exact"],
        "not_pure_yaw_1e5": cnt["not_pure_yaw_1e5"],
        "det_pos": cnt["det_pos"],
        "det_neg": cnt["det_neg"],
        "det_zero": cnt["det_zero"],
        "orth_violation": cnt["orth_violation"],
        "scale_uniform_1e-3": cnt["scale_uniform"],
        "scale_nonuniform_1e-3": cnt["scale_nonuniform"],
        "m13_integer": m13_int,
        "m13_noninteger": m13_nonint,
        "range": range_stat,
        "grid_files_numeric3": grid_files,
        "grid_files_nonnumeric": grid_files_nonnum,
        "grid_H1_seg2seg3_match": grid_hyp["H1_seg2_seg3"],
        "grid_H1_miss": grid_hyp["H1_miss"],
        "grid_H2_seg1seg2_match": grid_hyp["H2_seg1_seg2"],
        "grid_H3_seg1seg3_match": grid_hyp["H3_seg1_seg3"],
    },
    "per_tag": {str(t): dict(v) for t, v in sorted(tag_stat.items())},
    "yaw_hist_10deg": [[k, v] for k, v in yaw_values],
    "scale_hist_m5_top40": sorted(scale_hist.items(), key=lambda kv: -kv[1])[:40],
    "scale_hist_m5_distinct": len(scale_hist),
    "grid_mismatch_examples": grid_mismatch_examples,
    "anomalies": anomalies,
    "per_map_instances_top15": sorted(per_map_inst.items(), key=lambda kv: -kv[1])[:15],
    "dali_w1351_ll_dl_002": dict(dali_stat),
    "dali_grid_match": per_map_grid.get(Dali),
}
OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

T = out["totals"]
lines = []
lines.append(f"实例总数: {T['instances']:,}")
lines.append(f"齐次末行 (0,0,0,1): 由判据 M 构造性保证（解析器只放行满足者），违反 0")
lines.append(f"Y-up (m[4]=m[6]=0): 成立 {T['yup_ok']:,}  违反 {T['yup_violation']:,}")
lines.append(f"纯偏航 (m1=m4=m6=m9=0, 精确): {T['pure_yaw_exact']:,} "
             f"({100.0*T['pure_yaw_exact']/T['instances']:.4f}%)  "
             f"违反 {T['not_pure_yaw_exact']:,}（1e-5 宽容口径违反 {T['not_pure_yaw_1e5']:,}）")
lines.append(f"det: 正 {T['det_pos']:,}  负 {T['det_neg']:,}  近零 {T['det_zero']:,}")
lines.append(f"正交违反 (|cos|>1e-3): {T['orth_violation']:,}")
lines.append(f"逐实例统一缩放 (相对差<=1e-3): {T['scale_uniform_1e-3']:,}  "
             f"非统一 {T['scale_nonuniform_1e-3']:,}")
lines.append(f"m[13] 整数占比: {T['m13_integer']:,}/{T['instances']:,} "
             f"({100.0*T['m13_integer']/T['instances']:.2f}%)")
lines.append(f"平移范围: x[{T['range']['x'][0]:.2f},{T['range']['x'][1]:.2f}]  "
             f"y[{T['range']['y'][0]:.2f},{T['range']['y'][1]:.2f}]  "
             f"z[{T['range']['z'][0]:.2f},{T['range']['z'][1]:.2f}]")
lines.append(f"32格对照（文件名=3段数字的格子）: 文件 {T['grid_files_numeric3']:,}  "
             f"非数字名 {T['grid_files_nonnumeric']:,}")
lines.append(f"  H1 (段2=x格, 段3=z格): 吻合 {T['grid_H1_seg2seg3_match']:,}  "
             f"不吻合 {T['grid_H1_miss']:,} "
             f"({100.0*T['grid_H1_seg2seg3_match']/max(1,T['grid_H1_seg2seg3_match']+T['grid_H1_miss']):.4f}%)")
lines.append(f"  H2 (段1=x格, 段2=z格): 吻合 {T['grid_H2_seg1seg2_match']:,}")
lines.append(f"  H3 (段1=x格, 段3=z格): 吻合 {T['grid_H3_seg1seg3_match']:,}")
lines.append("")
lines.append("按 tag:")
for t, v in sorted(out["per_tag"].items(), key=lambda kv: -kv[1]["instances"]):
    lines.append(f"  tag={t}: 实例 {v['instances']:,}  非纯偏航 {v.get('not_pure_yaw', 0)}")
lines.append("")
lines.append(f"偏航直方图（10°桶, 桶起点=[-180,180) 环绕）:")
for k, v in yaw_values:
    lines.append(f"  [{k - 180:+d}, {k - 170:+d}) {v}")
lines.append("")
lines.append(f"m[5] 取值 top40: {out['scale_hist_m5_top40']}")
lines.append(f"m[5] 不同取值数: {out['scale_hist_m5_distinct']}")
lines.append("")
lines.append(f"大理 {Dali}: 实例 {dali_stat['instances']:,}  其中 753 型 {dali_stat['tag753_instances']:,}  "
             f"非纯偏航 {dali_stat['not_pure_yaw']}  det<0 {dali_stat['det_neg']}  "
             f"格号吻合 {per_map_grid.get(Dali, [0,0])[0]:,}/{per_map_grid.get(Dali, [0,0])[1]:,}")
lines.append("")
lines.append("实例数 top15 地图:")
for mp, n in out["per_map_instances_top15"]:
    lines.append(f"  {mp}  {n:,}")
lines.append("")
lines.append(f"格号不吻合样例（前 {len(grid_mismatch_examples)}）:")
for e in grid_mismatch_examples[:20]:
    lines.append(f"  {e['map']}/{e['file']} #{e['record']} {e['name']} "
                 f"pos=({e['x']:.2f},{e['y']:.2f},{e['z']:.2f}) floor=({e['floor_x32']},{e['floor_y32']},{e['floor_z32']}) segs={e['segs']}")
OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
print("done")
