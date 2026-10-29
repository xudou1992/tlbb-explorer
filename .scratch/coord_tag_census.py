"""任务1：全量 .scene tag 普查（mobile_maps 树，只读）。

产出（.scratch/coord_tag_census.json + coord_tag_census.txt）：
- 全部出现过的 tag 值及文件数（含已知集合之外的）。
- 已知集合外 tag 的样例文件（前若干个）+ 头 16 字节 hex。
- 对每个 tag：stride=tag+8 判据是否成立（有多少文件按该 stride 从 12 起能走出 >=1 条、
  多少在第 0 条失败、多少中途停）。
- 空格子 / TooShort / 其他分类计数。
- 每张地图的文件数与 tag 集合。
"""
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from coord_scene_lib import KNOWN_TAGS, parse_scene, u32_at

TREE = Path(r"D:\TLGL\.scratch\out\tree\mobile_maps")
OUT_JSON = Path(r"D:\TLGL\.scratch\coord_tag_census.json")
OUT_TXT = Path(r"D:\TLGL\.scratch\coord_tag_census.txt")

tag_files = defaultdict(int)          # tag -> 文件数
tag_maps = defaultdict(set)           # tag -> 地图目录集合
unknown_examples = defaultdict(list)  # tag -> 样例文件
per_tag_walk = defaultdict(lambda: defaultdict(int))  # tag -> 结果 -> 文件数
per_map = {}
total = 0
empty4 = 0
too_short = 0

for mapdir in sorted(TREE.iterdir()):
    if not mapdir.is_dir():
        continue
    scenes = sorted(mapdir.glob("*.scene"))
    m_tagc = defaultdict(int)
    m_other = []
    for f in scenes:
        total += 1
        raw = f.read_bytes()
        if len(raw) < 12:
            if len(raw) == 4 and u32_at(raw, 0) == 0:
                empty4 += 1
                m_tagc["empty4"] += 1
            else:
                too_short += 1
                m_tagc["too_short"] += 1
            continue
        tag = u32_at(raw, 4)
        tag_files[tag] += 1
        tag_maps[tag].add(mapdir.name)
        m_tagc[tag] += 1
        if tag not in KNOWN_TAGS and len(unknown_examples[tag]) < 5:
            unknown_examples[tag].append(
                {"file": str(f.relative_to(TREE)), "head_hex": raw[:16].hex()}
            )
        kind, grid = parse_scene(raw)
        if kind == "ok":
            if grid["instances"]:
                res = f"walked_{len(grid['instances'])}"
                per_tag_walk[tag]["walked>=1"] += 1
                per_tag_walk[tag]["instances_total"] += len(grid["instances"])
            else:
                res = "walked_0"
                per_tag_walk[tag]["walked_0"] += 1
            if grid["has_tail"]:
                per_tag_walk[tag]["with_tail"] += 1
        elif kind == "layout_undetermined":
            res = f"layout_fail_at_{grid['failed_at']}"
            per_tag_walk[tag]["layout_fail_at_0"] += 1
        elif kind == "too_short":
            res = "too_short"
            per_tag_walk[tag]["too_short"] += 1
        else:
            res = "unknown_version"
            per_tag_walk[tag]["unknown_version"] += 1
        m_tagc[f"_res:{res.split('_')[0]}"] += 1
    per_map[mapdir.name] = {
        "scene_files": len(scenes),
        "tag_counts": {str(k): v for k, v in sorted(m_tagc.items(), key=lambda kv: str(kv[0]))},
    }

# ---- stride=tag+8 成立性核对：对未知 tag 用「同 tag 文件里能走出>=1条」作为判据 ----
out = {
    "total_scene_files": total,
    "empty4": empty4,
    "too_short_lt12": too_short,
    "tag_distribution": {
        str(t): {
            "files": n,
            "maps": len(tag_maps[t]),
            "in_known_set": t in KNOWN_TAGS,
            "walk": {k: v for k, v in sorted(per_tag_walk[t].items())},
        }
        for t, n in sorted(tag_files.items())
    },
    "unknown_tag_examples": {
        str(t): v for t, v in sorted(unknown_examples.items())
    },
    "per_map": per_map,
}
OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

lines = []
lines.append(f"mobile_maps 下 .scene 总数: {total}")
lines.append(f"  4 字节空格子: {empty4}")
lines.append(f"  <12B 非空格子: {too_short}")
lines.append("")
lines.append("tag 分布（含 stride=tag+8 走查结果）:")
for t, info in sorted(out["tag_distribution"].items(), key=lambda kv: -kv[1]["files"]):
    mark = "已知" if info["in_known_set"] else "★未知"
    w = info["walk"]
    inst = w.get("instances_total", 0)
    lines.append(
        f"  tag={t:>6}  文件 {info['files']:>6}  地图 {info['maps']:>3}  [{mark}]  "
        f"走>=1条 {w.get('walked>=1', 0):>6}  走0条 {w.get('walked_0', 0):>5}  "
        f"首条即败 {w.get('layout_fail_at_0', 0):>5}  实例合计 {inst:>8}"
    )
if unknown_examples:
    lines.append("")
    lines.append("未知 tag 样例:")
    for t, exs in sorted(unknown_examples.items()):
        for e in exs[:3]:
            lines.append(f"  tag={t}  {e['file']}  head={e['head_hex']}")
lines.append("")
lines.append(f"地图目录数: {len(per_map)}")
OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
print("done")
