"""吃 census.tsv，回答：变体判据到底覆盖多少文件、命中是不是真的（链式吻合 + 蒙皮全覆盖），
并按题面要求对 30 份「正常文件」出误命中实测表。只读。"""
import os, csv, statistics as st

OUT = os.path.dirname(os.path.abspath(__file__))
FIVE = {"w1351_model_mj_nan_stone_h01.mesh", "w1351_model_bell_h002.mesh",
        "w1351_model_glass_ani_lf001.mesh", "w1351_model_fazhen_ani_lf001.mesh",
        "w1351_model_ymg01_stone01.mesh"}
rows = list(csv.DictReader(open(os.path.join(OUT, "census.tsv"), encoding="utf-8"), delimiter="\t"))
L = []
def b(p): return p.replace(chr(92), "/").split("/")[-1]
for r in rows:
    for k in ("size", "vc", "bones", "a", "v", "chain_ok", "vpairs", "cov", "wsum1", "scale100"):
        r[k] = int(r[k] or 0)

tot = len(rows)
vpos = [r for r in rows if r["v"] > 0]
L.append(f"全库 .mesh {tot} 份；变体判据命中 >=1 条的文件 {len(vpos)} 份")
pure = [r for r in vpos if r["a"] == 0]
mixed = [r for r in vpos if r["a"] > 0]
L.append(f"  其中 现有解析器 0 条（纯变体）= {len(pure)} 份；与 96B 记录混用 = {len(mixed)} 份")
full = [r for r in vpos if r["vc"] and r["cov"] == r["vc"]]
L.append(f"  变体表把整张网格顶点 100% 覆盖的文件 = {len(full)} 份（能全覆盖说明命中是真的，噪声覆盖不了）")
chained = [r for r in vpos if r["vpairs"] > 0 and r["chain_ok"] == r["vpairs"]]
L.append(f"  记录链 L=228+8N 全吻合（>=2 条且无一失配）= {len(chained)} 份")
strong = [r for r in vpos if r["vc"] and r["cov"] == r["vc"] and r["vpairs"] > 0 and r["chain_ok"] == r["vpairs"]]
L.append(f"  两者都满足（强证据=真记录阵）= {len(strong)} 份")
L.append("")
L.append("### 5 份异常文件在统一口径下的读数")
L.append("  文件名  声明骨  现有A  变体v  链吻合/对  覆盖/顶点  权重和≈1")
for r in rows:
    if b(r["path"]) in FIVE:
        L.append(f"  {b(r['path']):46s} {r['bones']:4d} {r['a']:5d} {r['v']:5d} "
                 f"{r['chain_ok']:4d}/{r['vpairs']:<4d} {r['cov']:6d}/{r['vc']:<6d} {r['wsum1']:6d}")
L.append("")
L.append("### 命中条数分档（全部命中文件）")
c = {}
for r in vpos:
    k = "1 条" if r["v"] == 1 else ("2-4 条" if r["v"] < 5 else ("5-29 条" if r["v"] < 30 else ">=30 条"))
    c[k] = c.get(k, 0) + 1
L.append("  " + str(sorted(c.items())))
c2 = {}
for r in vpos:
    genuine = r["vc"] and r["cov"] == r["vc"]
    k = "全覆盖(真)" if genuine else "未全覆盖(需看)"
    c2[k] = c2.get(k, 0) + 1
L.append("  按覆盖分： " + str(sorted(c2.items())))
L.append("")
# 「疑似误命中」：命中了但一条都没链上、覆盖也不full
susp = [r for r in vpos if r["chain_ok"] == 0 and (r["vc"] == 0 or r["cov"] < r["vc"])]
L.append(f"命中但既没链上、顶点也没全覆盖的文件（最像误命中）= {len(susp)} 份")
for r in sorted(susp, key=lambda x: -x["v"])[:12]:
    L.append(f"   v={r['v']:3d} a={r['a']:4d} bones={r['bones']:4d} cov={r['cov']}/{r['vc']} chain={r['chain_ok']}/{r['vpairs']}  {b(r['path'])}")
L.append("")
L.append("=" * 100)
L.append("### 题面要求的 30 份正常文件误命中实测")
L.append("取样口径：按路径排序，取「现有解析器已认到 >=5 条 96B 记录」的前 30 份（排除那 5 份异常文件）")
norm = [r for r in rows if r["a"] >= 5 and b(r["path"]) not in FIVE][:30]
L.append(f"  实际取样 {len(norm)} 份")
hits = 0
files_hit = 0
L.append("  %-52s %5s %5s %6s %6s %8s %8s" % ("file", "bones", "A", "变体v", "链", "覆盖/顶点", "判定"))
for r in norm:
    if r["v"] > 0:
        files_hit += 1
        hits += r["v"]
        if r["vc"] and r["cov"] == r["vc"] and r["vpairs"] and r["chain_ok"] == r["vpairs"]:
            verdict = "真记录阵"
        elif r["cov"] >= max(1, int(0.9 * r["vc"])):
            verdict = "真(近全覆盖)"
        else:
            verdict = "疑似误命中"
    else:
        verdict = "无命中"
    L.append("  %-52s %5d %5d %6d %6d %8s %10s" % (b(r["path"])[:52], r["bones"], r["a"], r["v"],
             r["chain_ok"], f"{r['cov']}/{r['vc']}", verdict))
L.append(f"  ⇒ 30 份里出现命中的文件 {files_hit} 份，命中条数合计 {hits} 条")
L.append(f"  ⇒ 其中判为「疑似误命中」（链不接且顶点没全覆盖）的文件：")
for r in norm:
    if r["v"] > 0 and not (r["vc"] and r["cov"] == r["vc"] and r["vpairs"] and r["chain_ok"] == r["vpairs"]):
        L.append(f"     {b(r['path'])}  v={r['v']} a={r['a']} bones={r['bones']} cov={r['cov']}/{r['vc']} chain={r['chain_ok']}/{r['vpairs']}")
open(os.path.join(OUT, "census_report.txt"), "w", encoding="utf-8").write("\n".join(L))
print("WROTE census_report.txt")
for x in L[:12]:
    print(x.encode("unicode_escape").decode()[:160])
