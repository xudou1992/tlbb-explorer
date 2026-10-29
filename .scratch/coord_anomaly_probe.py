"""任务3：异常实例深挖（只读，二遍全量走查）。

- 交叉表：纯偏航 × det 符号 × 缩放是否统一
- det<0 实例的模式：XZ 2x2 子块行列式符号 / 负元素位置 / 偏航角
- 非纯偏航实例的模式：m1/m4/m6/m9 谁非零、量级、与列范数比
- 平移离群：|y|>1000 或 |x|>20000 或 |z|>20000
- det≈0 实例：全矩阵落盘
- 同名互证：异常实例的网格名在库内所有出现处的纯偏航比例与 m5 分布
- 大理 53 条 det<0 + 13 条非纯偏航全名单（文件/记录号/矩阵）
输出 coord_anomaly_probe.json / .txt
"""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from coord_scene_lib import parse_scene

TREE = Path(r"D:\TLGL\.scratch\out\tree\mobile_maps")
OUT_JSON = Path(r"D:\TLGL\.scratch\coord_anomaly_probe.json")
OUT_TXT = Path(r"D:\TLGL\.scratch\coord_anomaly_probe.txt")
EPS = 1e-5
Dali = "w1351_ll_dl_002"

crosstab = defaultdict(int)
neg_patterns = defaultdict(int)      # det<0: 哪些元素为负
pitch_patterns = defaultdict(int)    # 非纯偏航: 哪些元素非零
det_zero_dump = []
outliers = []
dali_detneg = []
dali_tilt = []
name_index = defaultdict(lambda: {"n": 0, "pure_yaw": 0, "m5": defaultdict(int)})
anom_names = set()  # (map,file,idx) -> 之后同名互证


def col_norm(m, c):
    return math.sqrt(m[c] ** 2 + m[c + 1] ** 2 + m[c + 2] ** 2)


def det3(m):
    return (m[0] * (m[5] * m[10] - m[6] * m[9])
            - m[1] * (m[4] * m[10] - m[6] * m[8])
            + m[2] * (m[4] * m[9] - m[5] * m[8]))


def rec_key(mapname, fname, i):
    return f"{mapname}/{fname}#{i}"


anomaly_records = []  # (key, name, kind)

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
        is_dali = mapname == Dali
        for i, inst in enumerate(grid["instances"]):
            m = inst["m"]
            name = inst["name"]
            ni = name_index[name]
            ni["n"] += 1
            pure = (m[1] == 0.0 and m[4] == 0.0 and m[6] == 0.0 and m[9] == 0.0)
            if pure:
                ni["pure_yaw"] += 1
            ni["m5"][round(m[5], 3)] += 1

            sx, sy, sz = col_norm(m, 0), col_norm(m, 4), col_norm(m, 8)
            mx_, mn_ = max(sx, sy, sz), min(sx, sy, sz)
            uniform = (mx_ - mn_) <= 1e-3 * mx_ if mx_ > 0 else False
            d = det3(m)
            sign = "neg" if d < 0 else ("zero" if abs(d) < 1e-9 else "pos")
            crosstab[(pure, sign, uniform)] += 1

            key = rec_key(mapname, fname, i)
            if not pure:
                which = tuple(k for k, v in
                              (("m1", m[1]), ("m4", m[4]), ("m6", m[6]), ("m9", m[9]))
                              if abs(v) >= EPS)
                mag = max(abs(m[1]), abs(m[4]), abs(m[6]), abs(m[9]))
                pitch_patterns[which] += 1
                anomaly_records.append((key, name, "tilt"))
                entry = {
                    "key": key, "name": name, "which": which, "max_mag": mag,
                    "m": list(m), "det": d, "sx": sx, "sy": sy, "sz": sz,
                }
                if is_dali and len(dali_tilt) < 100:
                    dali_tilt.append(entry)
            if sign == "neg":
                pat = tuple(k for k, v in
                            (("m0", m[0]), ("m2", m[2]), ("m5", m[5]),
                             ("m8", m[8]), ("m10", m[10])) if v < 0)
                neg_patterns[pat] += 1
                anomaly_records.append((key, name, "det_neg"))
                entry = {
                    "key": key, "name": name, "neg_at": pat, "m": list(m), "det": d,
                    "xz2x2_det": m[0] * m[10] - m[2] * m[8],
                    "yaw": round(math.degrees(math.atan2(m[8], m[0])), 2),
                    "sx": sx, "sy": sy, "sz": sz,
                }
                if is_dali and len(dali_detneg) < 200:
                    dali_detneg.append(entry)
            if sign == "zero" and len(det_zero_dump) < 10:
                det_zero_dump.append({"key": key, "name": name, "m": list(m)})
            if abs(m[13]) > 1000 or abs(m[12]) > 20000 or abs(m[14]) > 20000:
                if len(outliers) < 200:
                    outliers.append({
                        "key": key, "name": name, "pos": [m[12], m[13], m[14]],
                        "m": list(m),
                    })

# 同名互证：异常实例名字在库内的表现
unique_anom_names = sorted({nm for _, nm, _ in anomaly_records})
name_evidence = []
for nm in unique_anom_names:
    ni = name_index.get(nm)
    if not ni:
        continue
    m5s = sorted(ni["m5"].items(), key=lambda kv: -kv[1])[:5]
    name_evidence.append({
        "name": nm, "total": ni["n"],
        "pure_yaw": ni["pure_yaw"],
        "pure_yaw_ratio": round(ni["pure_yaw"] / ni["n"], 4),
        "m5_top": m5s,
    })
name_evidence.sort(key=lambda e: -e["total"])

out = {
    "crosstab_pureyaw_detsign_uniform": [
        {"pure_yaw": k[0], "det": k[1], "uniform": k[2], "count": v}
        for k, v in sorted(crosstab.items(), key=lambda kv: -kv[1])
    ],
    "det_neg_patterns": {"|".join(k) if k else "(无负元素?)": v
                         for k, v in sorted(neg_patterns.items(), key=lambda kv: -kv[1])},
    "tilt_patterns": {"|".join(k): v
                      for k, v in sorted(pitch_patterns.items(), key=lambda kv: -kv[1])},
    "det_zero": det_zero_dump,
    "translation_outliers": outliers,
    "dali_det_neg": dali_detneg,
    "dali_tilt": dali_tilt,
    "anomaly_instance_count": len(anomaly_records),
    "name_evidence_top50": name_evidence[:50],
}
OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

lines = []
lines.append("交叉表（纯偏航 × det × 缩放统一）:")
for e in out["crosstab_pureyaw_detsign_uniform"]:
    lines.append(f"  pure_yaw={e['pure_yaw']!s:5}  det={e['det']:4}  uniform={e['uniform']!s:5}  {e['count']:,}")
lines.append("")
lines.append("det<0 模式（负元素位置）:")
for k, v in sorted(out["det_neg_patterns"].items(), key=lambda kv: -kv[1]):
    lines.append(f"  {k}: {v:,}")
lines.append("")
lines.append("非纯偏航模式（非零元素）:")
for k, v in sorted(out["tilt_patterns"].items(), key=lambda kv: -kv[1]):
    lines.append(f"  {k}: {v:,}")
lines.append("")
lines.append(f"det≈0: {len(det_zero_dump)} 条")
for e in det_zero_dump:
    lines.append(f"  {e['key']}  {e['name']}")
    lines.append(f"    m={[round(x, 6) for x in e['m']]}")
lines.append("")
lines.append(f"平移离群 (|y|>1000 或 |x|>20000 或 |z|>20000): {len(outliers)} 条（截断 200）")
for e in outliers[:20]:
    lines.append(f"  {e['key']}  {e['name']}  pos={e['pos']}")
lines.append("")
lines.append(f"大理 det<0: {len(dali_detneg)} 条;  大理非纯偏航: {len(dali_tilt)} 条")
for e in dali_detneg[:10]:
    lines.append(f"  [det<0] {e['key']} {e['name']} yaw={e['yaw']} neg_at={e['neg_at']} "
                 f"det={e['det']:.3f} sx={e['sx']:.3f} sy={e['sy']:.3f} sz={e['sz']:.3f}")
for e in dali_tilt[:20]:
    lines.append(f"  [tilt] {e['key']} {e['name']} which={e['which']} max_mag={e['max_mag']:.6g}")
lines.append("")
lines.append("同名互证（异常网格名在库内全部出现处）top50:")
for e in name_evidence[:50]:
    lines.append(f"  {e['name']}: 出现 {e['total']} 次, 纯偏航 {e['pure_yaw_ratio']*100:.2f}%, "
                 f"m5 top {e['m5_top'][:3]}")
OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
print("done")
